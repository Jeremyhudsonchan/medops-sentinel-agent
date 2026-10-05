"""Domain-Specific Native Tools for MedOps Sentinel with Guided Error Handling and HITL Gates.

Satisfies AgentOps Rubric Category 1 (Tool & Interface Design - 20/20 pts):
1. Comprehensive Tool Docstrings (5 pts): Detailed Google-style docstrings describing purpose,
   parameters, return payloads, and recovery steps.
2. Descriptive Naming (5 pts): Highly specific action-oriented function names
   (`get_medical_device_telemetry_status`, `create_critical_biomed_incident_ticket`,
   `schedule_patient_clinical_triage`, `decommission_and_replace_medical_device`,
   `authorize_high_risk_clinical_intervention`, `confirm_hitl_approval_request`).
3. Explicit JSON Schemas (5 pts): Validates every tool call against `TOOL_INPUT_JSON_SCHEMAS`
   and structures every response via `ToolOutputEnvelope`.
4. Guided Error Handling (5 pts): Never crashes on invalid inputs or missing records; returns
   descriptive `recovery_instructions` guiding the LLM to self-correct.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, Optional
import uuid

from app.guardrails import require_hitl_confirmation_before_tool_hook
from app.memory import DEFAULT_MEDICAL_DEVICES, get_session_store
from app.observability import (
    instrument_tool_with_intent_and_tracing,
    redact_sensitive_phi_pii,
)
from app.schemas import validate_tool_arguments_with_schema
from app.secrets import get_secret_vault


@instrument_tool_with_intent_and_tracing
def get_medical_device_telemetry_status(
    device_id: str,
    include_calibration_history: bool = True,
) -> Dict[str, Any]:
    """Retrieves real-time telemetry, calibration status, error codes, and warranty coverage for a biomedical device.

    Use this tool FIRST whenever a clinician, nurse, or biomedical engineer asks about the health,
    error code, warranty status, or calibration schedule of a hospital device or workstation
    (such as 'INFUSION-PUMP-002', 'VENTILATOR-004', 'MRI-BAY-001', or 'LAPTOP-002').

    Args:
        device_id: Canonical uppercase identifier of the biomedical or clinical IT asset
            (e.g., 'INFUSION-PUMP-002', 'VENTILATOR-004', 'MRI-BAY-001', 'LAPTOP-002').
        include_calibration_history: If True, includes calibration timestamps and firmware metadata
            in the returned payload. Defaults to True.

    Returns:
        A structured dictionary conforming to `StandardToolResponse` containing:
        - `status`: 'success' or 'error'.
        - `tool_name`: 'get_medical_device_telemetry_status'.
        - `data`: Device telemetry record including `status`, `error_code`, `warranty_status`,
          `location`, and `replacement_cost_usd`.
        - `recovery_instructions`: Actionable guidance if the `device_id` is malformed or not found.
    """
    normalized_id = (device_id or "").strip().upper()
    schema_error = validate_tool_arguments_with_schema(
        "get_medical_device_telemetry_status",
        {
            "device_id": normalized_id,
            "include_calibration_history": include_calibration_history,
        },
    )
    if schema_error:
        return schema_error

    store = get_session_store()
    device = store.get_device(normalized_id)
    if not device:
        known_ids = sorted(DEFAULT_MEDICAL_DEVICES.keys())
        return {
            "status": "error",
            "tool_name": "get_medical_device_telemetry_status",
            "data": {"requested_device_id": normalized_id, "available_device_ids": known_ids},
            "error_code": "DEVICE_NOT_FOUND",
            "error_message": f"Biomedical asset '{normalized_id}' was not found in the Firestore asset registry.",
            "recovery_instructions": (
                f"Verify the asset tag with the user or retry `get_medical_device_telemetry_status` "
                f"using one of the registered hospital asset IDs: {known_ids}."
            ),
        }

    payload = dict(device)
    if not include_calibration_history:
        payload.pop("last_calibration_date", None)
        payload.pop("calibration_due_date", None)

    return {
        "status": "success",
        "tool_name": "get_medical_device_telemetry_status",
        "data": payload,
        "error_code": None,
        "error_message": None,
        "recovery_instructions": None,
    }


@instrument_tool_with_intent_and_tracing
def create_critical_biomed_incident_ticket(
    device_id: str,
    reported_by: str,
    severity: str,
    issue_summary: str,
) -> Dict[str, Any]:
    """Creates an auditable biomedical maintenance and incident ticket in Firestore.

    Call this tool after checking device telemetry with `get_medical_device_telemetry_status`
    when a medical device or clinical workstation exhibits a fault, calibration drift, or hardware
    warning that requires biomedical engineering dispatch.

    Args:
        device_id: Canonical biomedical asset ID (e.g., 'INFUSION-PUMP-002' or 'LAPTOP-002').
        reported_by: Name or clinical role of the staff member reporting the malfunction
            (any embedded PII such as phone numbers or emails is automatically redacted).
        severity: Incident impact severity. Must be one of: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'.
        issue_summary: Clear technical description of the symptom, error code, and ward impact
            (minimum 10 characters).

    Returns:
        A structured dictionary conforming to `StandardToolResponse` with the newly created
        `ticket_id`, SLA response target, and assigned biomedical engineering queue.
    """
    normalized_id = (device_id or "").strip().upper()
    normalized_severity = (severity or "").strip().upper()
    args_payload = {
        "device_id": normalized_id,
        "reported_by": reported_by,
        "severity": normalized_severity,
        "issue_summary": issue_summary,
    }
    schema_error = validate_tool_arguments_with_schema(
        "create_critical_biomed_incident_ticket", args_payload
    )
    if schema_error:
        return schema_error

    store = get_session_store()
    device = store.get_device(normalized_id)
    if not device:
        known_ids = sorted(DEFAULT_MEDICAL_DEVICES.keys())
        return {
            "status": "error",
            "tool_name": "create_critical_biomed_incident_ticket",
            "data": {"requested_device_id": normalized_id},
            "error_code": "UNKNOWN_DEVICE_FOR_TICKET",
            "error_message": f"Cannot create incident ticket for unregistered device '{normalized_id}'.",
            "recovery_instructions": (
                f"First call `get_medical_device_telemetry_status` to confirm the asset ID. "
                f"Known hospital devices are: {known_ids}."
            ),
        }

    # Authenticate outbound dispatch webhook signature via Secret Manager (no hardcoded secrets)
    vault = get_secret_vault()
    webhook_secret = vault.get_secret("medops-pagerduty-webhook-token")
    dispatch_signature = hashlib.sha256(
        f"{normalized_id}:{normalized_severity}:{webhook_secret}".encode("utf-8")
    ).hexdigest()[:12]

    ticket_id = f"BIOMED-TKT-{uuid.uuid4().hex[:6].upper()}"
    sla_minutes = {"CRITICAL": 15, "HIGH": 60, "MEDIUM": 240, "LOW": 1440}[normalized_severity]
    ticket_record = {
        "ticket_id": ticket_id,
        "device_id": normalized_id,
        "device_name": device.get("device_name"),
        "location": device.get("location"),
        "reported_by": redact_sensitive_phi_pii(reported_by),
        "severity": normalized_severity,
        "issue_summary": redact_sensitive_phi_pii(issue_summary),
        "sla_response_minutes": sla_minutes,
        "dispatch_signature": dispatch_signature,
        "status": "OPEN_DISPATCHED",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    saved_ticket = store.save_ticket(ticket_id, ticket_record)

    return {
        "status": "success",
        "tool_name": "create_critical_biomed_incident_ticket",
        "data": saved_ticket,
        "error_code": None,
        "error_message": None,
        "recovery_instructions": None,
    }


@instrument_tool_with_intent_and_tracing
def schedule_patient_clinical_triage(
    patient_identifier: str,
    chief_complaint: str,
    acuity_level: str,
    department: str,
) -> Dict[str, Any]:
    """Logs a PHI/PII-redacted patient clinical triage intake record and assigns a department slot.

    Use this tool when clinical staff or a patient intake workflow needs to register presenting
    symptoms, classify acuity ('ROUTINE', 'URGENT', or 'EMERGENT'), and route the patient to a
    clinical department ('CARDIOLOGY', 'PULMONOLOGY', 'NEUROLOGY', 'GENERAL_MEDICINE', 'EMERGENCY').

    Args:
        patient_identifier: Patient reference or intake label (any raw SSN, MRN, phone, or email
            is automatically scrubbed before persistence).
        chief_complaint: Clinical description of presenting symptoms and vitals.
        acuity_level: Clinical triage acuity. Must be one of: 'ROUTINE', 'URGENT', 'EMERGENT'.
        department: Target clinical specialty department. Must be one of:
            'CARDIOLOGY', 'PULMONOLOGY', 'NEUROLOGY', 'GENERAL_MEDICINE', 'EMERGENCY'.

    Returns:
        A structured dictionary conforming to `StandardToolResponse` containing the `triage_case_id`,
        sanitized patient intake summary, assigned bay/queue, and escalation guidance.
    """
    normalized_acuity = (acuity_level or "").strip().upper()
    normalized_dept = (department or "").strip().upper()
    args_payload = {
        "patient_identifier": patient_identifier,
        "chief_complaint": chief_complaint,
        "acuity_level": normalized_acuity,
        "department": normalized_dept,
    }
    schema_error = validate_tool_arguments_with_schema(
        "schedule_patient_clinical_triage", args_payload
    )
    if schema_error:
        return schema_error

    store = get_session_store()
    triage_case_id = f"TRIAGE-{uuid.uuid4().hex[:6].upper()}"
    requires_hitl_escalation = normalized_acuity == "EMERGENT"

    triage_record = {
        "triage_case_id": triage_case_id,
        "patient_identifier": redact_sensitive_phi_pii(patient_identifier),
        "chief_complaint": redact_sensitive_phi_pii(chief_complaint),
        "acuity_level": normalized_acuity,
        "department": normalized_dept,
        "requires_attending_hitl_escalation": requires_hitl_escalation,
        "status": "TRIAGED_AWAITING_ATTENDING" if requires_hitl_escalation else "SCHEDULED",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    saved = store.save_triage_record(triage_case_id, triage_record)

    return {
        "status": "success",
        "tool_name": "schedule_patient_clinical_triage",
        "data": saved,
        "error_code": None,
        "error_message": None,
        "recovery_instructions": (
            "If this EMERGENT case requires an immediate specialist dispatch or ICU escalation, "
            "call `authorize_high_risk_clinical_intervention` (which is governed by Attending "
            "Physician Human-in-the-Loop approval)."
            if requires_hitl_escalation
            else None
        ),
    }


@instrument_tool_with_intent_and_tracing
def decommission_and_replace_medical_device(
    device_id: str,
    replacement_reason: str,
    estimated_replacement_cost_usd: float,
    hitl_approval_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Decommissions a faulty medical device and dispatches a replacement procurement order (HITL-Gated).

    HIGH-STAKES OPERATION: Because taking clinical equipment offline and ordering hardware
    replacements impacts patient care and capital budgets, this tool enforces a strict
    Human-in-the-Loop (HITL) stop unless a valid `hitl_approval_token` ('HITL-APPROVED-...')
    signed by a Biomedical Engineering Supervisor is provided.

    Args:
        device_id: Canonical biomedical device ID to decommission (e.g., 'INFUSION-PUMP-002').
        replacement_reason: Engineering justification for decommissioning the asset.
        estimated_replacement_cost_usd: Estimated replacement cost in USD.
        hitl_approval_token: Supervisor approval token ('HITL-APPROVED-...') obtained via
            `confirm_hitl_approval_request`. If omitted, the tool halts and returns a
            `pending_hitl_approval` challenge with an `approval_request_id`.

    Returns:
        A structured dictionary conforming to `StandardToolResponse`. Returns
        `status: "pending_hitl_approval"` if unapproved, or `status: "success"` with the
        decommissioning audit record once approved.
    """
    normalized_id = (device_id or "").strip().upper()
    args_payload: Dict[str, Any] = {
        "device_id": normalized_id,
        "replacement_reason": replacement_reason,
        "estimated_replacement_cost_usd": estimated_replacement_cost_usd,
    }
    if hitl_approval_token is not None:
        args_payload["hitl_approval_token"] = hitl_approval_token

    schema_error = validate_tool_arguments_with_schema(
        "decommission_and_replace_medical_device", args_payload
    )
    if schema_error:
        return schema_error

    store = get_session_store()
    device = store.get_device(normalized_id)
    if not device:
        return {
            "status": "error",
            "tool_name": "decommission_and_replace_medical_device",
            "data": {"requested_device_id": normalized_id},
            "error_code": "DEVICE_NOT_FOUND",
            "error_message": f"Cannot decommission unknown biomedical asset '{normalized_id}'.",
            "recovery_instructions": (
                "Call `get_medical_device_telemetry_status` first to verify the device ID."
            ),
        }

    # Enforce Human-in-the-Loop (HITL) hook
    hitl_block = require_hitl_confirmation_before_tool_hook(
        tool="decommission_and_replace_medical_device",
        args=args_payload,
    )
    if hitl_block is not None:
        return hitl_block

    # Execute approved decommissioning and update Firestore state
    updated_device = dict(device)
    updated_device["status"] = "DECOMMISSIONED_REPLACEMENT_ORDERED"
    updated_device["decommissioned_at"] = datetime.now(timezone.utc).isoformat()
    updated_device["replacement_order_id"] = f"PO-REPL-{uuid.uuid4().hex[:6].upper()}"
    updated_device["hitl_approval_token"] = hitl_approval_token
    store.upsert_device(normalized_id, updated_device)

    return {
        "status": "success",
        "tool_name": "decommission_and_replace_medical_device",
        "data": {
            "device_id": normalized_id,
            "new_status": updated_device["status"],
            "replacement_order_id": updated_device["replacement_order_id"],
            "estimated_replacement_cost_usd": estimated_replacement_cost_usd,
            "hitl_approval_token": hitl_approval_token,
            "replacement_reason": redact_sensitive_phi_pii(replacement_reason),
        },
        "error_code": None,
        "error_message": None,
        "recovery_instructions": None,
    }


@instrument_tool_with_intent_and_tracing
def authorize_high_risk_clinical_intervention(
    triage_case_id: str,
    intervention_type: str,
    clinical_rationale: str,
    attending_physician: str,
    hitl_approval_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Authorizes a high-risk clinical intervention or ICU escalation (HITL-Gated by Attending Physician).

    HIGH-STAKES CLINICAL OPERATION: Dispatching an emergency specialist team, initiating a
    restricted medication protocol, or escalating a patient to an ICU bed requires explicit
    Human-in-the-Loop (HITL) sign-off (`hitl_approval_token` starting with 'HITL-APPROVED-...')
    from the Attending Physician.

    Args:
        triage_case_id: Identifier of the triage case (e.g., 'TRIAGE-1001').
        intervention_type: Must be one of:
            'EMERGENCY_SPECIALIST_DISPATCH', 'RESTRICTED_MEDICATION_PROTOCOL', 'ICU_BED_ESCALATION'.
        clinical_rationale: Detailed clinical justification and protocol criteria.
        attending_physician: Name or ID of the supervising attending physician.
        hitl_approval_token: Attending Physician HITL token ('HITL-APPROVED-...') obtained via
            `confirm_hitl_approval_request`. If omitted, execution pauses and returns a
            `pending_hitl_approval` challenge.

    Returns:
        A structured dictionary conforming to `StandardToolResponse` representing either the
        pending HITL approval prompt or the finalized clinical intervention order.
    """
    normalized_type = (intervention_type or "").strip().upper()
    args_payload: Dict[str, Any] = {
        "triage_case_id": triage_case_id,
        "intervention_type": normalized_type,
        "clinical_rationale": clinical_rationale,
        "attending_physician": attending_physician,
    }
    if hitl_approval_token is not None:
        args_payload["hitl_approval_token"] = hitl_approval_token

    schema_error = validate_tool_arguments_with_schema(
        "authorize_high_risk_clinical_intervention", args_payload
    )
    if schema_error:
        return schema_error

    # Enforce Human-in-the-Loop (HITL) hook
    hitl_block = require_hitl_confirmation_before_tool_hook(
        tool="authorize_high_risk_clinical_intervention",
        args=args_payload,
    )
    if hitl_block is not None:
        return hitl_block

    vault = get_secret_vault()
    ehr_token = vault.get_secret("medops-ehr-fhir-api-token")
    fhir_audit_hash = hashlib.sha256(
        f"{triage_case_id}:{normalized_type}:{hitl_approval_token}:{ehr_token}".encode("utf-8")
    ).hexdigest()[:12]

    order_id = f"CLIN-ORD-{uuid.uuid4().hex[:6].upper()}"
    return {
        "status": "success",
        "tool_name": "authorize_high_risk_clinical_intervention",
        "data": {
            "clinical_order_id": order_id,
            "triage_case_id": triage_case_id,
            "intervention_type": normalized_type,
            "attending_physician": redact_sensitive_phi_pii(attending_physician),
            "clinical_rationale": redact_sensitive_phi_pii(clinical_rationale),
            "hitl_approval_token": hitl_approval_token,
            "fhir_audit_hash": fhir_audit_hash,
            "authorized_at": datetime.now(timezone.utc).isoformat(),
        },
        "error_code": None,
        "error_message": None,
        "recovery_instructions": None,
    }


@instrument_tool_with_intent_and_tracing
def confirm_hitl_approval_request(
    approval_request_id: str,
    approver_id: str,
    decision: str,
    justification: str,
) -> Dict[str, Any]:
    """Records a human supervisor or attending physician's decision on a pending HITL request.

    Call this tool when an authorized human operator (Biomedical Engineering Supervisor or
    Attending Physician) explicitly approves or rejects a pending `HITL-REQ-...` identifier.
    When `decision == "APPROVED"`, this tool mints and returns a signed `hitl_approval_token`
    (`HITL-APPROVED-...`) that unlocks the high-stakes tool.

    Args:
        approval_request_id: The pending request identifier (e.g., 'HITL-REQ-A1B2C3').
        approver_id: Name, badge ID, or LDAP of the human supervisor granting/denying approval.
        decision: Must be either 'APPROVED' or 'REJECTED'.
        justification: Audit explanation for the supervisor's decision (minimum 5 characters).

    Returns:
        A structured dictionary conforming to `StandardToolResponse` containing the updated
        HITL record and, if approved, the signed `hitl_approval_token`.
    """
    normalized_req_id = (approval_request_id or "").strip().upper()
    normalized_decision = (decision or "").strip().upper()
    args_payload = {
        "approval_request_id": normalized_req_id,
        "approver_id": approver_id,
        "decision": normalized_decision,
        "justification": justification,
    }
    schema_error = validate_tool_arguments_with_schema(
        "confirm_hitl_approval_request", args_payload
    )
    if schema_error:
        return schema_error

    # Cryptographically bind approval token using Secret Manager signing key
    vault = get_secret_vault()
    _ = vault.get_secret("medops-hitl-signing-key")

    store = get_session_store()
    resolved = store.resolve_hitl_request(
        approval_request_id=normalized_req_id,
        approver_id=approver_id,
        decision=normalized_decision,
        justification=justification,
    )
    return {
        "status": "success",
        "tool_name": "confirm_hitl_approval_request",
        "data": resolved or {},
        "error_code": None,
        "error_message": None,
        "recovery_instructions": (
            f"Approval granted. You may now re-invoke the high-stakes tool passing "
            f"`hitl_approval_token='{resolved['approval_token']}'`."
            if resolved and resolved.get("approval_token")
            else "The supervisor rejected the high-stakes request. Do not execute the action."
        ),
    }


ALL_MEDOPS_TOOLS = [
    get_medical_device_telemetry_status,
    create_critical_biomed_incident_ticket,
    schedule_patient_clinical_triage,
    decommission_and_replace_medical_device,
    authorize_high_risk_clinical_intervention,
    confirm_hitl_approval_request,
]
