"""Live Local Model Test Runner for MedOps Sentinel (ADK + Vertex AI on Argolis GCP).

Runs real multi-turn LLM interactions against Vertex AI (`gemini-2.5-flash` and `gemini-2.5-pro`)
using the Google Agent Development Kit (`google.adk.runners.InMemoryRunner`) and `google-genai`.

Prerequisites for Argolis GCP Sandbox:
  1. Authenticate ADC: `gcloud auth application-default login`
  2. Set project: `export GOOGLE_CLOUD_PROJECT=<your-argolis-project-id>`
  3. Run: `.venv/bin/python scripts/run_live_model_test.py`
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.agent import execute_medops_agent_turn, medops_app, root_agent
from app.observability import get_structured_logger
from scripts.seed_firestore import seed_medical_devices


async def run_live_adk_runner_session(project_id: str, location: str = "us-east4") -> None:
    """Executes live multi-turn prompts through Google ADK InMemoryRunner with Vertex AI."""
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = location
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"

    logger = get_structured_logger("medops_sentinel.live_test")

    try:
        from google.adk.runners import InMemoryRunner  # type: ignore[import-untyped]
        from google.genai import types  # type: ignore[import-untyped]
    except ImportError as exc:
        sys.stderr.write(
            f"google-adk / google-genai not found in active interpreter ({exc}). "
            "Run via `.venv/bin/python scripts/run_live_model_test.py`.\n"
        )
        sys.exit(1)

    # Ensure canonical device statuses are seeded before the live multi-turn scenario
    seed_medical_devices(project_id=project_id)

    runner = (
        InMemoryRunner(app=medops_app)
        if not isinstance(medops_app, dict)
        else InMemoryRunner(agent=root_agent, app_name="medops-sentinel-agent")
    )
    session = await runner.session_service.create_session(
        app_name="medops-sentinel-agent",
        user_id="argolis-clinician-01",
    )

    test_prompts = [
        "Check the current telemetry status and warranty for INFUSION-PUMP-002 and LAPTOP-002.",
        "Triage patient MRN-776655 (SSN 123-45-6789, phone 415-555-0199) with emergent chest pain in Cardiology.",
        "Decommission and replace INFUSION-PUMP-002 ($6,800) due to repeated occlusion sensor failure.",
        (
            "I am Dr. Elena Vance (Biomedical Engineering Supervisor). I approve that pending "
            "HITL request for INFUSION-PUMP-002 with decision 'APPROVED' and clinical justification "
            "'Confirmed repeated occlusion sensor drift in ICU-WEST-BED-04; immediate replacement authorized.' "
            "Please record my HITL approval and then complete the decommissioning and replacement of INFUSION-PUMP-002."
        ),
    ]

    sys.stdout.write(
        f"\n=== Running Live ADK Model Session on Vertex AI (Project: {project_id}, Region: {location}) ===\n"
    )
    for idx, prompt in enumerate(test_prompts, start=1):
        sys.stdout.write(f"\n--- [Turn {idx}] User Prompt ---\n{prompt}\n")
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        sys.stdout.write(f"--- [Turn {idx}] MedOps Sentinel Live Response ---\n")
        async for event in runner.run_async(
            user_id="argolis-clinician-01",
            session_id=session.id,
            new_message=content,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if getattr(part, "text", None):
                        sys.stdout.write(part.text + "\n")
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        sys.stdout.write(f"  [Tool Call] -> {fc.name}({dict(fc.args)})\n")

    logger.info(
        "Completed live Vertex AI ADK model test run.",
        extra={"event_type": "LIVE_ADK_TEST_COMPLETE", "metadata": {"project_id": project_id}},
    )


def main() -> None:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-east4").strip()
    if not project_id or project_id == "your-gcp-project-id":
        sys.stdout.write(
            "NOTE: GOOGLE_CLOUD_PROJECT is not set yet. Running local deterministic orchestrator preview first.\n"
            "To run against live Vertex AI Gemini models on your Argolis project, set:\n"
            "  export GOOGLE_CLOUD_PROJECT=<your-argolis-project-id>\n"
            "  .venv/bin/python scripts/run_live_model_test.py\n\n"
        )
        preview = execute_medops_agent_turn(
            "What is the telemetry and warranty status of INFUSION-PUMP-002?",
            session_id="local-preview",
        )
        sys.stdout.write(f"Local Orchestrator Preview Output:\n  {preview['response_text']}\n")
        return

    asyncio.run(run_live_adk_runner_session(project_id=project_id, location=location))


if __name__ == "__main__":
    main()
