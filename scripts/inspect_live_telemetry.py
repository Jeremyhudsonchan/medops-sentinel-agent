"""Inspects live Cloud Logging telemetry, OpenTelemetry traces, and Firestore state in Argolis GCP.

Queries Cloud Logging for structured JSON events emitted by the `medops-sentinel-agent`
Cloud Run revision and verifies live Firestore documents in `medical_devices`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import app  # noqa: F401 - loads .env
from app.memory import FirestoreSessionAndMemoryStore


def inspect_cloud_run_logs(
    project_id: str | None = None,
    limit: int = 80,
) -> None:
    """Reads recent structured telemetry logs from Cloud Run in Cloud Logging."""
    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")
    print(f"=== 1. Querying Cloud Logging for 'medops-sentinel-agent' in {project_id} ===")
    cmd = [
        "gcloud",
        "logging",
        "read",
        'resource.type="cloud_run_revision" AND resource.labels.service_name="medops-sentinel-agent"',
        f"--project={project_id}",
        f"--limit={limit}",
        "--format=json",
    ]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    entries = json.loads(res.stdout or "[]")
    print(f"Retrieved {len(entries)} recent log entries from Cloud Run.\n")

    structured_events = []
    http_requests = []

    for entry in reversed(entries):
        if "httpRequest" in entry:
            req = entry["httpRequest"]
            http_requests.append(
                f"  HTTP {req.get('requestMethod')} {req.get('requestUrl')} -> {req.get('status')} ({req.get('latency')})"
            )
        jp = entry.get("jsonPayload")
        tp = entry.get("textPayload", "")
        if isinstance(jp, dict) and ("event_type" in jp or "logger" in jp):
            structured_events.append(jp)
        elif isinstance(tp, str) and tp.strip().startswith("{") and "event_type" in tp:
            try:
                structured_events.append(json.loads(tp.strip()))
            except Exception:
                pass

    print(f"--- Structured MedOps Sentinel Telemetry Events ({len(structured_events)} found) ---")
    for idx, ev in enumerate(structured_events, start=1):
        etype = ev.get("event_type", "LOG")
        sev = ev.get("severity", "INFO")
        msg = ev.get("message", "")
        trace_id = ev.get("trace_id", "")
        tool_name = ev.get("tool_name", "")
        latency = ev.get("latency_ms", "")
        extra_info = f" | tool={tool_name}" if tool_name else ""
        if latency != "":
            extra_info += f" | latency={latency}ms"
        print(f"  [{idx:02d}] [{sev}] {etype}{extra_info} (trace={trace_id[:10]}) -> {msg}")


def inspect_live_firestore_devices(project_id: str | None = None) -> None:
    """Checks the current state of all collections in live Cloud Firestore."""
    from google.cloud import firestore  # type: ignore[import-untyped]

    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")
    print(f"\n=== 2. Inspecting Live Cloud Firestore Collections ({project_id}) ===")
    db = firestore.Client(project=project_id)
    db._database_string_internal = f"projects/{project_id}/databases/(default)"
    for col_name in (
        "medical_devices",
        "biomed_tickets",
        "clinical_triage_records",
        "hitl_approval_requests",
        "medops_memories",
    ):
        docs = list(db.collection(col_name).stream())
        print(f"\n  Collection '{col_name}' ({len(docs)} documents):")
        for d in docs:
            data = d.to_dict() or {}
            print(f"    - {d.id}: {json.dumps(data)}")


if __name__ == "__main__":
    inspect_cloud_run_logs()
    inspect_live_firestore_devices()
