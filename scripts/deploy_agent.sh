#!/usr/bin/env bash
# Deploys MedOps Sentinel to Gemini Enterprise Agent Platform & runs ADK Evaluation Suite
# Follows Romin Irani's 5-Part Gemini Enterprise Agent Platform Tutorial Series

set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-east4}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -z "${PROJECT_ID}" ]] && [[ -f ".env" ]]; then
  PROJECT_ID="$(grep -E '^GOOGLE_CLOUD_PROJECT=' .env | cut -d'=' -f2- | tr -d '[:space:]')"
fi

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Usage: bash scripts/deploy_agent.sh <PROJECT_ID> [REGION]"
  exit 1
fi

PYTHON_BIN="python3"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

SA_EMAIL="medops-sentinel-agent-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> [1/4] Seeding Firestore medical_devices collection in project ${PROJECT_ID}..."
GOOGLE_CLOUD_PROJECT="${PROJECT_ID}" MEDOPS_USE_LIVE_FIRESTORE=true "${PYTHON_BIN}" -m scripts.seed_firestore

echo "==> [2/4] Running deterministic unit tests & golden evaluation suite..."
"${PYTHON_BIN}" -m unittest discover -s tests -v
"${PYTHON_BIN}" -m eval.run_evaluation_harness

if command -v agents-cli >/dev/null 2>&1; then
  echo "==> [3/4] Deploying MedOps Sentinel to Gemini Enterprise Agent Runtime..."
  agents-cli deploy --project "${PROJECT_ID}" --region "${REGION}"
elif command -v google-agents >/dev/null 2>&1; then
  echo "==> [3/4] Deploying MedOps Sentinel via google-agents CLI..."
  google-agents deploy --project "${PROJECT_ID}" --region "${REGION}"
else
  echo "==> [3/4] Ensuring Argolis Cloud Build service account permissions..."
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
  COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  for BUILD_ROLE in "roles/storage.admin" "roles/artifactregistry.writer" "roles/logging.logWriter"; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${COMPUTE_SA}" \
      --role="${BUILD_ROLE}" \
      --condition=None \
      --quiet >/dev/null || true
  done

  echo "==> [3/4] Deploying MedOps Sentinel to Cloud Run (${REGION}) with least-privilege SA (${SA_EMAIL})..."
  gcloud run deploy medops-sentinel-agent \
    --source . \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --service-account "${SA_EMAIL}" \
    --min-instances 0 \
    --max-instances 2 \
    --memory 1Gi \
    --cpu 1 \
    --no-allow-unauthenticated \
    --quiet \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=TRUE,MEDOPS_USE_LIVE_FIRESTORE=true,MEDOPS_ENABLE_CLOUD_TRACE=true"
fi

echo "==> [4/4] Deployment workflow complete."
