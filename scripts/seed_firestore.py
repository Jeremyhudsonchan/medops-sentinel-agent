"""Seeds initial biomedical and IT devices into Google Cloud Firestore.

Follows Part 2 of Romin Irani's Gemini Enterprise Agent Platform tutorial series:
populates `medical_devices` collection with `INFUSION-PUMP-002`, `VENTILATOR-004`,
`MRI-BAY-001`, and `LAPTOP-002`.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import app  # noqa: F401 - triggers .env auto-load
from app.memory import DEFAULT_MEDICAL_DEVICES, FirestoreSessionAndMemoryStore
from app.observability import get_structured_logger


def seed_medical_devices(project_id: str | None = None) -> int:
    """Seeds canonical hospital biomedical devices into Firestore (or local store)."""
    logger = get_structured_logger("medops_sentinel.seeder")
    target_project = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "")
    store = FirestoreSessionAndMemoryStore(project_id=target_project)

    count = 0
    for device_id, payload in DEFAULT_MEDICAL_DEVICES.items():
        store.upsert_device(device_id, payload)
        count += 1

    logger.info(
        f"Seeded {count} biomedical assets into store (project='{target_project or 'local'}').",
        extra={"event_type": "FIRESTORE_SEED_COMPLETE", "metadata": {"seeded_count": count}},
    )
    return count


if __name__ == "__main__":
    seed_medical_devices()
