"""MedOps Sentinel: Smart Healthcare Clinical Triage & Biomedical Asset Operations Agent.

Built on the Gemini Enterprise Agent Platform using the Google Agent Development Kit (ADK).
Exposes `root_agent` for `agents-cli playground`, `adk web`, and `adk eval`.
"""

from pathlib import Path
import os

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _stripped = _line.strip()
        if _stripped and not _stripped.startswith("#") and "=" in _stripped:
            _k, _v = _stripped.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from app.agent import (
    biomed_asset_triage_agent,
    clinical_diagnostic_pipeline_agent,
    clinical_escalation_specialist_agent,
    create_medops_coordinator_agent,
    root_agent,
)

__all__ = [
    "root_agent",
    "create_medops_coordinator_agent",
    "biomed_asset_triage_agent",
    "clinical_escalation_specialist_agent",
    "clinical_diagnostic_pipeline_agent",
]
