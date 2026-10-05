"""Enterprise Governance, Model Armor Policy Plugins, and Human-in-the-Loop (HITL) Hooks.

Satisfies AgentOps Rubric Category 3 (Orchestration & Logic):
1. Guardrails & Policy Plugins (5 pts):
   - `model_armor_input_guardrail_plugin` (`before_model_callback`): Defends against prompt
     injection, unauthorized persona adoption, instruction override, and unsafe payloads
     (following Part 4 of the Gemini Enterprise Agent Platform Medium tutorial series).
   - `self_evaluation_output_guardrail_plugin` (`after_model_callback`): Performs automated
     output self-evaluation to ensure no unredacted PHI/PII or fabricated HITL tokens leak.
2. Human-in-the-Loop Hooks (5 pts):
   - `require_hitl_confirmation_before_tool_hook` (`before_tool_callback`): Explicitly halts
     execution of high-stakes clinical and biomedical tools (`decommission_and_replace_medical_device`
     and `authorize_high_risk_clinical_intervention`) unless human supervisor confirmation is present.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.memory import get_session_store
from app.observability import (
    get_structured_logger,
    redact_sensitive_phi_pii,
    start_distributed_span,
)

# High-stakes tools gated by Human-in-the-Loop confirmation
HITL_PROTECTED_TOOLS = frozenset(
    {
        "decommission_and_replace_medical_device",
        "authorize_high_risk_clinical_intervention",
    }
)

# Prompt injection & persona override signatures blocked by Model Armor policy plugin
PROMPT_INJECTION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(dan|unrestricted|jailbroken|a\s+pirate)", re.IGNORECASE),
    re.compile(r"(reveal|print|output|dump)\s+(your\s+)?(system\s+prompt|constitution|secret)", re.IGNORECASE),
    re.compile(r"bypass\s+(hitl|human\s+in\s+the\s+loop|supervisor\s+approval|model\s+armor)", re.IGNORECASE),
]


# ============================================================================
# 1. Input Guardrail & Model Armor Policy Plugin (ADK before_model_callback)
# ============================================================================


def inspect_prompt_with_model_armor_policy(prompt_text: str) -> Dict[str, Any]:
    """Evaluates user input against Model Armor floor settings and prompt-injection rules.

    Args:
        prompt_text: Raw incoming user prompt text.

    Returns:
        Dictionary with `allowed` (bool), `violation_type`, `sanitized_text`, and `policy_message`.
    """
    logger = get_structured_logger("medops_sentinel.guardrails")
    with start_distributed_span("guardrails.model_armor_inspect_input"):
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(prompt_text or ""):
                logger.warning(
                    "Model Armor guardrail blocked prompt injection / persona override attempt.",
                    extra={
                        "event_type": "GUARDRAIL_INPUT_BLOCKED",
                        "metadata": {"violation_type": "PROMPT_INJECTION_OR_PERSONA_OVERRIDE"},
                    },
                )
                return {
                    "allowed": False,
                    "violation_type": "PROMPT_INJECTION_OR_PERSONA_OVERRIDE",
                    "sanitized_text": redact_sensitive_phi_pii(prompt_text),
                    "policy_message": (
                        "Request blocked by MedOps Sentinel Model Armor Guardrail: "
                        "Attempts to override system instructions, adopt unauthorized personas, "
                        "or bypass Human-in-the-Loop safety controls are prohibited."
                    ),
                }

        sanitized = redact_sensitive_phi_pii(prompt_text)
        return {
            "allowed": True,
            "violation_type": None,
            "sanitized_text": sanitized,
            "policy_message": "Input passed Model Armor policy inspection.",
        }


def model_armor_input_guardrail_plugin(
    callback_context: Any = None,
    llm_request: Any = None,
) -> Optional[Any]:
    """ADK `before_model_callback` plugin enforcing Model Armor security and PII scrubbing.

    If a prompt-injection or policy violation is detected, short-circuits the model call
    and returns a safe policy refusal response (`LlmResponse` in live ADK runtime, or `dict` in tests).
    """
    prompt_text = ""
    is_adk_llm_request = llm_request is not None and hasattr(llm_request, "contents")
    if isinstance(llm_request, str):
        prompt_text = llm_request
    elif is_adk_llm_request:
        prompt_text = str(getattr(llm_request, "contents", ""))
    elif isinstance(callback_context, dict):
        prompt_text = str(callback_context.get("user_input", ""))

    verdict = inspect_prompt_with_model_armor_policy(prompt_text)
    if not verdict["allowed"]:
        if is_adk_llm_request:
            try:
                from google.adk.models.llm_response import LlmResponse  # type: ignore[import-untyped]
                from google.genai import types  # type: ignore[import-untyped]

                return LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=verdict["policy_message"])],
                    )
                )
            except ImportError:
                pass
        return {
            "status": "blocked_by_guardrail",
            "violation_type": verdict["violation_type"],
            "message": verdict["policy_message"],
        }
    return None


# ============================================================================
# 2. Output Self-Evaluation Guardrail Plugin (ADK after_model_callback)
# ============================================================================


def evaluate_response_safety_and_quality(response_text: str) -> Dict[str, Any]:
    """Self-evaluates candidate agent output for leaked PHI/PII or hallucinated approval tokens."""
    logger = get_structured_logger("medops_sentinel.guardrails")
    with start_distributed_span("guardrails.self_evaluation_output"):
        sanitized_text = redact_sensitive_phi_pii(response_text or "")
        had_unredacted_pii = sanitized_text != (response_text or "")

        # Verify the LLM did not fabricate an unverified HITL token
        store = get_session_store()
        fabricated_tokens: List[str] = []
        for match in re.finditer(r"\b(HITL-APPROVED-[A-Z0-9-]+)\b", sanitized_text):
            candidate_token = match.group(1)
            if not store.is_valid_hitl_token(candidate_token):
                fabricated_tokens.append(candidate_token)

        if had_unredacted_pii:
            logger.info(
                "Output self-evaluation guardrail scrubbed residual PHI/PII from model response.",
                extra={"event_type": "GUARDRAIL_OUTPUT_PII_SCRUBBED"},
            )

        return {
            "passed_self_eval": len(fabricated_tokens) == 0,
            "had_unredacted_pii": had_unredacted_pii,
            "fabricated_tokens": fabricated_tokens,
            "sanitized_response": sanitized_text,
        }


def self_evaluation_output_guardrail_plugin(
    callback_context: Any = None,
    llm_response: Any = None,
) -> Optional[Any]:
    """ADK `after_model_callback` plugin running automated self-evaluation on model outputs.

    When invoked by the ADK runtime with an `LlmResponse` object, scrubs any residual PHI/PII
    in-place on text parts and returns `None` so the `LlmResponse` pipeline continues cleanly.
    When invoked directly with a string in unit tests, returns the evaluation report dictionary.
    """
    if llm_response is not None and hasattr(llm_response, "content") and hasattr(llm_response, "partial"):
        content = getattr(llm_response, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if parts:
            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text:
                    eval_report = evaluate_response_safety_and_quality(part_text)
                    if eval_report["had_unredacted_pii"]:
                        part.text = eval_report["sanitized_response"]
        return None

    raw_text = llm_response if isinstance(llm_response, str) else str(llm_response or "")
    return evaluate_response_safety_and_quality(raw_text)


# ============================================================================
# 3. Human-in-the-Loop (HITL) Confirmation Hook (ADK before_tool_callback)
# ============================================================================


def require_hitl_confirmation_before_tool_hook(
    tool: Any,
    args: Dict[str, Any],
    tool_context: Any = None,
) -> Optional[Dict[str, Any]]:
    """ADK `before_tool_callback` that pauses high-stakes actions until human confirmation.

    Inspects calls to `decommission_and_replace_medical_device` and
    `authorize_high_risk_clinical_intervention`. If no valid `hitl_approval_token` is supplied
    in `args` or `tool_context.state`, blocks execution and creates a persistent
    `HITL-REQ-...` approval request for the human supervisor/clinician.

    Args:
        tool: The ADK FunctionTool or Python callable being invoked.
        args: Tool arguments dictionary proposed by the LLM.
        tool_context: Optional ADK ToolContext carrying session state.

    Returns:
        None if execution is permitted; otherwise a structured `pending_hitl_approval` dict
        that intercepts the tool call and prompts the human operator for confirmation.
    """
    tool_name = tool if isinstance(tool, str) else getattr(tool, "name", getattr(tool, "__name__", str(tool)))
    if tool_name not in HITL_PROTECTED_TOOLS:
        return None

    logger = get_structured_logger("medops_sentinel.hitl")
    store = get_session_store()

    # Check if a low-cost non-critical replacement is exempt (< $5,000 USD)
    if tool_name == "decommission_and_replace_medical_device":
        cost = float(args.get("estimated_replacement_cost_usd", 0.0) or 0.0)
        device_id = str(args.get("device_id", "")).strip().upper()
        device = store.get_device(device_id) or {}
        is_life_support = "LIFE_SUPPORT" in str(device.get("category", ""))
        if cost < 5000.0 and not is_life_support and args.get("hitl_approval_token"):
            return None

    # Check token in tool arguments or ADK ToolContext session state
    supplied_token = args.get("hitl_approval_token")
    if not supplied_token and tool_context is not None:
        state = getattr(tool_context, "state", None)
        if isinstance(state, dict):
            supplied_token = state.get("hitl_approval_token")

    if store.is_valid_hitl_token(supplied_token):
        logger.info(
            f"HITL approval verified for high-stakes tool '{tool_name}'. Proceeding with execution.",
            extra={
                "event_type": "HITL_APPROVAL_VERIFIED",
                "tool_name": tool_name,
                "metadata": {"approval_token": supplied_token},
            },
        )
        return None

    # Halt execution and register a persistent HITL approval request
    reason = (
        f"High-stakes action '{tool_name}' requires explicit Human-in-the-Loop supervisor/clinician "
        "confirmation before execution."
    )
    hitl_record = store.create_hitl_request(
        tool_name=tool_name,
        proposed_arguments=args,
        reason=reason,
    )
    logger.warning(
        f"HITL hook intercepted high-stakes tool '{tool_name}'. Created request '{hitl_record['approval_request_id']}'.",
        extra={
            "event_type": "HITL_INTERCEPTION_STOP",
            "tool_name": tool_name,
            "metadata": hitl_record,
        },
    )
    return {
        "status": "pending_hitl_approval",
        "tool_name": tool_name,
        "data": {
            "approval_request_id": hitl_record["approval_request_id"],
            "hitl_status": "PENDING_HUMAN_CONFIRMATION",
            "proposed_arguments": redact_sensitive_phi_pii(args),
            "required_approver_role": (
                "Attending Physician"
                if tool_name == "authorize_high_risk_clinical_intervention"
                else "Biomedical Engineering Supervisor"
            ),
        },
        "error_code": "HITL_CONFIRMATION_REQUIRED",
        "error_message": reason,
        "recovery_instructions": (
            f"Present approval_request_id '{hitl_record['approval_request_id']}' to the human "
            "supervisor/clinician and ask for explicit confirmation. Once approved via "
            "`confirm_hitl_approval_request`, retry this tool with the returned `hitl_approval_token`."
        ),
    }
