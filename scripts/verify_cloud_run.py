"""Verifies the live Cloud Run deployment of MedOps Sentinel in Argolis (us-east4).

Authenticates with a Google Cloud OIDC Identity Token (`gcloud auth print-identity-token`)
and exercises the deployed ADK FastAPI endpoints (`/list-apps`, session creation, and `/run`)
to prove the least-privilege service account (`medops-sentinel-agent-sa`) can invoke Vertex AI
and query Cloud Firestore in production.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

DEFAULT_SERVICE_URL = os.getenv(
    "CLOUD_RUN_SERVICE_URL",
    "https://medops-sentinel-agent.us-east4.run.app",
)


def get_identity_token() -> str:
    """Fetches an OIDC identity token from the active gcloud configuration."""
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def http_json(url: str, token: str, method: str = "GET", payload: dict | None = None) -> object:
    """Sends an authenticated HTTP request to Cloud Run and parses JSON output."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify_cloud_run_service(service_url: str = DEFAULT_SERVICE_URL) -> None:
    """Verifies `/list-apps`, session creation, and live `/run` execution on Cloud Run."""
    base_url = service_url.rstrip("/")
    token = get_identity_token()

    print(f"=== Verifying Deployed Cloud Run Service: {base_url} ===")
    apps = http_json(f"{base_url}/list-apps", token=token)
    print(f"1. GET /list-apps -> {apps}")

    session_resp = http_json(
        f"{base_url}/apps/app/users/cloud-verifier/sessions",
        token=token,
        method="POST",
        payload={},
    )
    assert isinstance(session_resp, dict)
    session_id = session_resp["id"]
    print(f"2. POST /apps/app/users/cloud-verifier/sessions -> session_id={session_id}")

    run_payload = {
        "appName": "app",
        "userId": "cloud-verifier",
        "sessionId": session_id,
        "newMessage": {
            "role": "user",
            "parts": [{"text": "What is the current telemetry status and location of VENTILATOR-004?"}],
        },
    }
    events = http_json(f"{base_url}/run", token=token, method="POST", payload=run_payload)
    assert isinstance(events, list)
    print(f"3. POST /run -> received {len(events)} ADK events from Cloud Run:")
    for ev in events:
        content = ev.get("content") or {}
        for part in content.get("parts") or []:
            if "functionCall" in part:
                fc = part["functionCall"]
                print(f"   [Remote Cloud Run Tool Call] -> {fc.get('name')}({fc.get('args')})")
            elif "text" in part and part["text"]:
                print(f"   [Remote Cloud Run Agent Response] -> {part['text'].strip()}")


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERVICE_URL
    verify_cloud_run_service(url_arg)
