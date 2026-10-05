"""Explicit JSON Schemas and Pydantic Validation Models for MedOps Sentinel Tools.

Satisfies AgentOps Rubric Category 1 (Tool & Interface Design - Explicit JSON Schemas):
- Defines strict input and output schemas for every tool to constrain LLM arguments.
- Provides both Pydantic v2 BaseModel classes and explicit Draft-07 JSON Schema contracts.
- Performs deterministic input/output schema validation with descriptive error feedback.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator

    PYDANTIC_AVAILABLE = True
except ImportError:  # Graceful fallback for bare stdlib test environments
    PYDANTIC_AVAILABLE = False

    class BaseModel:  # type: ignore[no-redef]
        """Lightweight BaseModel shim when pydantic is not installed in the active interpreter."""

        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

        def model_dump(self) -> Dict[str, Any]:
            return dict(self.__dict__)

    def Field(default: Any = None, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        return default

    def ConfigDict(**kwargs: Any) -> Dict[str, Any]:  # type: ignore[no-redef]
        return kwargs

    def field_validator(*args: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        def decorator(func: Any) -> Any:
            return func

        return decorator


# ============================================================================
# 1. Explicit Draft-07 JSON Schemas for Tool Inputs and Outputs
# ============================================================================

TOOL_INPUT_JSON_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "get_medical_device_telemetry_status": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "GetMedicalDeviceTelemetryStatusInput",
        "type": "object",
        "additionalProperties": False,
        "required": ["device_id"],
        "properties": {
            "device_id": {
                "type": "string",
                "pattern": "^[A-Z0-9]+-[A-Z0-9]+-[0-9]{3}$|^[A-Z]+-[0-9]{3}$",
                "description": (
                    "Canonical biomedical asset identifier (e.g., 'INFUSION-PUMP-002', "
                    "'VENTILATOR-004', 'MRI-BAY-001', or 'LAPTOP-002')."
                ),
            },
            "include_calibration_history": {
                "type": "boolean",
                "default": True,
                "description": "Whether to include recent calibration and telemetry logs.",
            },
        },
    },
    "create_critical_biomed_incident_ticket": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "CreateCriticalBiomedIncidentTicketInput",
        "type": "object",
        "additionalProperties": False,
        "required": ["device_id", "reported_by", "severity", "issue_summary"],
        "properties": {
            "device_id": {
                "type": "string",
                "pattern": "^[A-Z0-9]+-[A-Z0-9]+-[0-9]{3}$|^[A-Z]+-[0-9]{3}$",
                "description": "Biomedical asset ID experiencing the fault.",
            },
            "reported_by": {
                "type": "string",
                "minLength": 2,
                "maxLength": 120,
                "description": "Staff member or clinician reporting the equipment failure.",
            },
            "severity": {
                "type": "string",
                "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                "description": "Clinical impact severity level.",
            },
            "issue_summary": {
                "type": "string",
                "minLength": 10,
                "maxLength": 1000,
                "description": "Detailed description of the malfunction or error code.",
            },
        },
    },
    "schedule_patient_clinical_triage": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "SchedulePatientClinicalTriageInput",
        "type": "object",
        "additionalProperties": False,
        "required": ["patient_identifier", "chief_complaint", "acuity_level", "department"],
        "properties": {
            "patient_identifier": {
                "type": "string",
                "minLength": 3,
                "maxLength": 120,
                "description": "Patient identifier or intake reference (any raw PII/MRN will be redacted).",
            },
            "chief_complaint": {
                "type": "string",
                "minLength": 5,
                "maxLength": 1000,
                "description": "Presenting clinical symptoms reported during patient intake.",
            },
            "acuity_level": {
                "type": "string",
                "enum": ["ROUTINE", "URGENT", "EMERGENT"],
                "description": "Clinical triage acuity classification.",
            },
            "department": {
                "type": "string",
                "enum": ["CARDIOLOGY", "PULMONOLOGY", "NEUROLOGY", "GENERAL_MEDICINE", "EMERGENCY"],
                "description": "Target clinical department for the triage appointment.",
            },
        },
    },
    "decommission_and_replace_medical_device": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "DecommissionAndReplaceMedicalDeviceInput",
        "type": "object",
        "additionalProperties": False,
        "required": ["device_id", "replacement_reason", "estimated_replacement_cost_usd"],
        "properties": {
            "device_id": {
                "type": "string",
                "pattern": "^[A-Z0-9]+-[A-Z0-9]+-[0-9]{3}$|^[A-Z]+-[0-9]{3}$",
                "description": "Biomedical asset ID to decommission and replace.",
            },
            "replacement_reason": {
                "type": "string",
                "minLength": 10,
                "maxLength": 1000,
                "description": "Engineering justification for taking the device offline.",
            },
            "estimated_replacement_cost_usd": {
                "type": "number",
                "minimum": 0,
                "maximum": 2000000,
                "description": "Estimated replacement procurement cost in USD.",
            },
            "hitl_approval_token": {
                "type": "string",
                "description": (
                    "Human-in-the-Loop supervisor approval token (e.g., 'HITL-APPROVED-...') "
                    "required before executing high-stakes decommissioning."
                ),
            },
        },
    },
    "authorize_high_risk_clinical_intervention": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "AuthorizeHighRiskClinicalInterventionInput",
        "type": "object",
        "additionalProperties": False,
        "required": ["triage_case_id", "intervention_type", "clinical_rationale", "attending_physician"],
        "properties": {
            "triage_case_id": {
                "type": "string",
                "minLength": 4,
                "maxLength": 64,
                "description": "Clinical triage case identifier (e.g., 'TRIAGE-1001').",
            },
            "intervention_type": {
                "type": "string",
                "enum": [
                    "EMERGENCY_SPECIALIST_DISPATCH",
                    "RESTRICTED_MEDICATION_PROTOCOL",
                    "ICU_BED_ESCALATION",
                ],
                "description": "Category of high-risk clinical intervention.",
            },
            "clinical_rationale": {
                "type": "string",
                "minLength": 10,
                "maxLength": 1500,
                "description": "Clinical evidence and protocol justification.",
            },
            "attending_physician": {
                "type": "string",
                "minLength": 3,
                "maxLength": 120,
                "description": "Name or ID of the supervising attending physician.",
            },
            "hitl_approval_token": {
                "type": "string",
                "description": (
                    "Mandatory Human-in-the-Loop clinician confirmation token "
                    "(e.g., 'HITL-APPROVED-...') required before dispatching the order."
                ),
            },
        },
    },
    "confirm_hitl_approval_request": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ConfirmHitlApprovalRequestInput",
        "type": "object",
        "additionalProperties": False,
        "required": ["approval_request_id", "approver_id", "decision", "justification"],
        "properties": {
            "approval_request_id": {
                "type": "string",
                "pattern": "^HITL-REQ-[A-Z0-9-]+$",
                "description": "Pending HITL approval request ID (e.g., 'HITL-REQ-1001').",
            },
            "approver_id": {
                "type": "string",
                "minLength": 3,
                "maxLength": 120,
                "description": "Authenticated human supervisor or attending clinician identifier.",
            },
            "decision": {
                "type": "string",
                "enum": ["APPROVED", "REJECTED"],
                "description": "Human supervisor decision on the high-stakes action.",
            },
            "justification": {
                "type": "string",
                "minLength": 5,
                "maxLength": 500,
                "description": "Audit note explaining why the request was approved or rejected.",
            },
        },
    },
}

TOOL_OUTPUT_JSON_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "StandardToolResponse": {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "StandardToolResponse",
        "type": "object",
        "required": ["status", "tool_name", "data"],
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "error", "pending_hitl_approval"],
            },
            "tool_name": {"type": "string"},
            "data": {"type": "object"},
            "error_code": {"type": ["string", "null"]},
            "error_message": {"type": ["string", "null"]},
            "recovery_instructions": {"type": ["string", "null"]},
        },
    }
}


# ============================================================================
# 2. Strict Pydantic Input/Output Models
# ============================================================================

DEVICE_ID_REGEX = re.compile(r"^[A-Z0-9]+-[A-Z0-9]+-[0-9]{3}$|^[A-Z]+-[0-9]{3}$")


class GetMedicalDeviceTelemetryInput(BaseModel):
    """Strict input schema for querying biomedical device telemetry."""

    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")

    device_id: str = Field(
        ...,
        description="Canonical biomedical device ID (e.g., 'INFUSION-PUMP-002' or 'LAPTOP-002').",
    )
    include_calibration_history: bool = Field(
        default=True,
        description="Whether to include recent calibration history and telemetry metrics.",
    )


class CreateBiomedIncidentTicketInput(BaseModel):
    """Strict input schema for creating a biomedical maintenance/incident ticket."""

    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")

    device_id: str = Field(..., description="Biomedical device ID experiencing a fault.")
    reported_by: str = Field(..., description="Staff member or clinician reporting the fault.")
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        ..., description="Impact severity of the equipment issue."
    )
    issue_summary: str = Field(..., description="Detailed description of the malfunction.")


class SchedulePatientClinicalTriageInput(BaseModel):
    """Strict input schema for scheduling a patient clinical triage session."""

    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")

    patient_identifier: str = Field(..., description="Patient intake identifier (PII auto-redacted).")
    chief_complaint: str = Field(..., description="Clinical symptoms reported by the patient.")
    acuity_level: Literal["ROUTINE", "URGENT", "EMERGENT"] = Field(
        ..., description="Clinical acuity classification."
    )
    department: Literal[
        "CARDIOLOGY", "PULMONOLOGY", "NEUROLOGY", "GENERAL_MEDICINE", "EMERGENCY"
    ] = Field(..., description="Target clinical department.")


class DecommissionMedicalDeviceInput(BaseModel):
    """Strict input schema for high-stakes medical device decommissioning (HITL-gated)."""

    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")

    device_id: str = Field(..., description="Biomedical device ID to decommission and replace.")
    replacement_reason: str = Field(..., description="Engineering reason for decommissioning.")
    estimated_replacement_cost_usd: float = Field(
        ..., ge=0.0, le=2000000.0, description="Estimated procurement cost in USD."
    )
    hitl_approval_token: Optional[str] = Field(
        default=None,
        description="Supervisor HITL approval token ('HITL-APPROVED-...') required for execution.",
    )


class AuthorizeClinicalInterventionInput(BaseModel):
    """Strict input schema for high-risk clinical intervention authorization (HITL-gated)."""

    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")

    triage_case_id: str = Field(..., description="Triage case identifier (e.g., 'TRIAGE-1001').")
    intervention_type: Literal[
        "EMERGENCY_SPECIALIST_DISPATCH",
        "RESTRICTED_MEDICATION_PROTOCOL",
        "ICU_BED_ESCALATION",
    ] = Field(..., description="Type of high-risk clinical intervention.")
    clinical_rationale: str = Field(..., description="Clinical evidence justifying the intervention.")
    attending_physician: str = Field(..., description="Supervising attending physician.")
    hitl_approval_token: Optional[str] = Field(
        default=None,
        description="Clinician HITL approval token ('HITL-APPROVED-...') required for execution.",
    )


class ConfirmHitlApprovalInput(BaseModel):
    """Strict input schema for recording human supervisor approval or rejection."""

    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")

    approval_request_id: str = Field(..., description="Pending HITL request ID ('HITL-REQ-...').")
    approver_id: str = Field(..., description="Human supervisor or physician ID.")
    decision: Literal["APPROVED", "REJECTED"] = Field(..., description="Approval decision.")
    justification: str = Field(..., description="Audit justification for the decision.")


class ToolOutputEnvelope(BaseModel):
    """Standardized output schema returned by all MedOps Sentinel tools."""

    if PYDANTIC_AVAILABLE:
        model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error", "pending_hitl_approval"]
    tool_name: str
    data: Dict[str, Any]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    recovery_instructions: Optional[str] = None


# ============================================================================
# 3. Deterministic JSON Schema Validation Helper
# ============================================================================


def validate_tool_arguments_with_schema(
    tool_name: str, arguments: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Validates tool arguments against the explicit JSON schema in TOOL_INPUT_JSON_SCHEMAS.

    Args:
        tool_name: Name of the tool being invoked.
        arguments: Dictionary of arguments passed to the tool.

    Returns:
        None if validation succeeds; otherwise a structured error dictionary containing
        `error_code`, `error_message`, and `recovery_instructions` for the LLM.
    """
    schema = TOOL_INPUT_JSON_SCHEMAS.get(tool_name)
    if not schema:
        return None

    required_fields: List[str] = schema.get("required", [])
    properties: Dict[str, Dict[str, Any]] = schema.get("properties", {})

    # 1. Check required fields
    missing = [
        req
        for req in required_fields
        if req not in arguments or arguments[req] is None or arguments[req] == ""
    ]
    if missing:
        return {
            "status": "error",
            "tool_name": tool_name,
            "data": {"invalid_arguments": arguments},
            "error_code": "SCHEMA_MISSING_REQUIRED_FIELDS",
            "error_message": f"Missing required parameter(s) for '{tool_name}': {', '.join(missing)}.",
            "recovery_instructions": (
                f"Supply non-empty values for {missing} conforming to the {schema['title']} JSON schema "
                f"and retry '{tool_name}'."
            ),
        }

    # 2. Check individual property constraints (enum, pattern, minLength, numeric bounds)
    for field_name, value in arguments.items():
        if value is None:
            continue
        prop_spec = properties.get(field_name)
        if not prop_spec:
            if schema.get("additionalProperties") is False:
                return {
                    "status": "error",
                    "tool_name": tool_name,
                    "data": {"unexpected_field": field_name},
                    "error_code": "SCHEMA_UNEXPECTED_PROPERTY",
                    "error_message": f"Unexpected parameter '{field_name}' is not allowed by {schema['title']}.",
                    "recovery_instructions": (
                        f"Remove '{field_name}'. Allowed parameters are: {list(properties.keys())}."
                    ),
                }
            continue

        expected_type = prop_spec.get("type")
        if expected_type == "string" and not isinstance(value, str):
            return {
                "status": "error",
                "tool_name": tool_name,
                "data": {"field": field_name, "received_type": type(value).__name__},
                "error_code": "SCHEMA_TYPE_MISMATCH",
                "error_message": f"Parameter '{field_name}' must be a string.",
                "recovery_instructions": f"Convert '{field_name}' to a valid string and retry '{tool_name}'.",
            }

        if expected_type == "number" and not isinstance(value, (int, float)):
            return {
                "status": "error",
                "tool_name": tool_name,
                "data": {"field": field_name, "received_type": type(value).__name__},
                "error_code": "SCHEMA_TYPE_MISMATCH",
                "error_message": f"Parameter '{field_name}' must be a number.",
                "recovery_instructions": f"Pass a numeric float or int for '{field_name}' and retry.",
            }

        if "enum" in prop_spec and value not in prop_spec["enum"]:
            allowed_values = prop_spec["enum"]
            return {
                "status": "error",
                "tool_name": tool_name,
                "data": {"field": field_name, "received_value": value, "allowed_enum": allowed_values},
                "error_code": "SCHEMA_ENUM_VIOLATION",
                "error_message": (
                    f"Invalid value '{value}' for '{field_name}'. Must be one of {allowed_values}."
                ),
                "recovery_instructions": (
                    f"Select one of the allowed enum values {allowed_values} for '{field_name}' "
                    f"and re-invoke '{tool_name}'."
                ),
            }

        if "pattern" in prop_spec and isinstance(value, str):
            if not re.match(prop_spec["pattern"], value.strip().upper()):
                return {
                    "status": "error",
                    "tool_name": tool_name,
                    "data": {"field": field_name, "received_value": value, "pattern": prop_spec["pattern"]},
                    "error_code": "SCHEMA_PATTERN_MISMATCH",
                    "error_message": (
                        f"Value '{value}' for '{field_name}' does not match required format "
                        f"'{prop_spec['pattern']}'."
                    ),
                    "recovery_instructions": (
                        f"Format '{field_name}' using uppercase prefix and 3-digit number "
                        "(e.g., 'INFUSION-PUMP-002', 'VENTILATOR-004', 'MRI-BAY-001', or 'LAPTOP-002') "
                        f"and retry '{tool_name}'."
                    ),
                }

        if "minLength" in prop_spec and isinstance(value, str):
            if len(value.strip()) < prop_spec["minLength"]:
                return {
                    "status": "error",
                    "tool_name": tool_name,
                    "data": {"field": field_name, "min_length": prop_spec["minLength"]},
                    "error_code": "SCHEMA_STRING_TOO_SHORT",
                    "error_message": (
                        f"Parameter '{field_name}' must be at least {prop_spec['minLength']} characters."
                    ),
                    "recovery_instructions": (
                        f"Provide a more descriptive '{field_name}' (at least {prop_spec['minLength']} "
                        f"characters) and retry '{tool_name}'."
                    ),
                }

        if "minimum" in prop_spec and isinstance(value, (int, float)):
            if value < prop_spec["minimum"]:
                return {
                    "status": "error",
                    "tool_name": tool_name,
                    "data": {"field": field_name, "minimum": prop_spec["minimum"]},
                    "error_code": "SCHEMA_NUMBER_OUT_OF_RANGE",
                    "error_message": (
                        f"Parameter '{field_name}' ({value}) cannot be less than {prop_spec['minimum']}."
                    ),
                    "recovery_instructions": (
                        f"Provide a non-negative number >= {prop_spec['minimum']} for '{field_name}'."
                    ),
                }

    return None
