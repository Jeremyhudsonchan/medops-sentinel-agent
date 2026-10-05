#!/usr/bin/env bash
# ==============================================================================
# MedOps Sentinel — Turnkey Argolis GCP Project, IAM, Firestore & Secrets Setup
# ==============================================================================
# Usage:
#   1. Authenticate your Argolis admin account first:
#        gcloud auth login
#   2. Run this script with your desired new (or existing) Project ID:
#        bash scripts/bootstrap_argolis_gcp.sh <PROJECT_ID> [REGION]
# ==============================================================================

set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-${GOOGLE_CLOUD_LOCATION:-us-east4}}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Usage: bash scripts/bootstrap_argolis_gcp.sh <PROJECT_ID> [REGION]"
  echo "Example: bash scripts/bootstrap_argolis_gcp.sh medops-sentinel-jchan-01 us-east4"
  exit 1
fi

ACTIVE_ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
if [[ -z "${ACTIVE_ACCOUNT}" ]]; then
  echo "ERROR: No active gcloud account detected. Run 'gcloud auth login --no-launch-browser' with your Argolis admin account first."
  exit 1
fi

if [[ "${ACTIVE_ACCOUNT}" == *"@google.com" ]]; then
  echo "ERROR: Active gcloud account is '${ACTIVE_ACCOUNT}' (@google.com)."
  echo "Please authenticate with your Argolis admin account (e.g., admin@<ldap>.altostrat.com) first:"
  echo "  gcloud auth login --no-launch-browser"
  exit 1
fi

ORG_ID="$(gcloud organizations list --format='value(ID)' --limit=1 2>/dev/null || true)"
ORG_NAME="$(gcloud organizations list --format='value(DISPLAY_NAME)' --limit=1 2>/dev/null || true)"

echo "=================================================================="
echo " Bootstrapping Argolis GCP Project for MedOps Sentinel"
echo "   Admin Account : ${ACTIVE_ACCOUNT}"
echo "   Argolis Org   : ${ORG_NAME:-unknown} (ID: ${ORG_ID:-none})"
echo "   Project ID    : ${PROJECT_ID}"
echo "   Region        : ${REGION}"
echo "=================================================================="

# ------------------------------------------------------------------------------
# 1. Create GCP Project inside Argolis Organization (if it doesn't already exist)
# ------------------------------------------------------------------------------
if gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "==> [1/7] Project '${PROJECT_ID}' already exists."
else
  echo "==> [1/7] Creating new GCP project '${PROJECT_ID}' in Argolis Org ${ORG_NAME:-} (${ORG_ID:-})..."
  if [[ -n "${ORG_ID}" ]]; then
    gcloud projects create "${PROJECT_ID}" \
      --name="MedOps Sentinel Agent" \
      --organization="${ORG_ID}"
  else
    gcloud projects create "${PROJECT_ID}" \
      --name="MedOps Sentinel Agent"
  fi
fi

gcloud config set project "${PROJECT_ID}"

# ------------------------------------------------------------------------------
# 2. Link Active Billing Account
# ------------------------------------------------------------------------------
echo "==> [2/7] Checking & linking Billing Account..."
CURRENT_BILLING="$(gcloud billing projects describe "${PROJECT_ID}" --format='value(billingEnabled)' 2>/dev/null || echo 'false')"
if [[ "${CURRENT_BILLING}" == "True" || "${CURRENT_BILLING}" == "true" ]]; then
  echo "    Billing is already enabled on '${PROJECT_ID}'."
else
  BILLING_ACCOUNT_ID="$(gcloud billing accounts list --filter='open=true' --format='value(ACCOUNT_ID)' --limit=1)"
  if [[ -z "${BILLING_ACCOUNT_ID}" ]]; then
    echo "ERROR: No open billing account found for ${ACTIVE_ACCOUNT}. Please link billing in the Cloud Console."
    exit 1
  fi
  echo "    Linking billing account ${BILLING_ACCOUNT_ID} to '${PROJECT_ID}'..."
  gcloud billing projects link "${PROJECT_ID}" --billing-account="${BILLING_ACCOUNT_ID}"
fi

# ------------------------------------------------------------------------------
# 3. Enable Required Google Cloud APIs
# ------------------------------------------------------------------------------
echo "==> [3/7] Enabling Vertex AI, Firestore, Secret Manager, Cloud Trace, Logging, DLP & Cloud Run APIs..."
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  iam.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  dlp.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project="${PROJECT_ID}"

# ------------------------------------------------------------------------------
# 4. Grant Explicit Admin User IAM Roles (Local ADK Dev, Secret Access, Firestore)
# ------------------------------------------------------------------------------
echo "==> [4/7] Assigning IAM roles to admin user (${ACTIVE_ACCOUNT})..."
ADMIN_ROLES=(
  "roles/aiplatform.admin"
  "roles/datastore.owner"
  "roles/secretmanager.admin"
  "roles/secretmanager.secretAccessor"
  "roles/cloudtrace.admin"
  "roles/logging.admin"
  "roles/dlp.user"
  "roles/run.admin"
  "roles/iam.serviceAccountUser"
)

for ROLE in "${ADMIN_ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="user:${ACTIVE_ACCOUNT}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet >/dev/null
done
echo "    Assigned ${#ADMIN_ROLES[@]} developer/admin roles to ${ACTIVE_ACCOUNT}."

# ------------------------------------------------------------------------------
# 5. Create Least-Privilege Agent Service Account & Bind Runtime Roles (Part 4)
# ------------------------------------------------------------------------------
SA_NAME="medops-sentinel-agent-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "==> [5/7] Setting up Least-Privilege Agent Service Account (${SA_EMAIL})..."

if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="MedOps Sentinel Agent Least-Privilege Identity" \
    --description="Dedicated least-privilege identity for MedOps Sentinel Agent" \
    --project="${PROJECT_ID}"
  sleep 3
fi

AGENT_RUNTIME_ROLES=(
  "roles/aiplatform.user"
  "roles/datastore.user"
  "roles/secretmanager.secretAccessor"
  "roles/cloudtrace.agent"
  "roles/logging.logWriter"
  "roles/dlp.user"
)

for ROLE in "${AGENT_RUNTIME_ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None \
    --quiet >/dev/null
done
echo "    Assigned least-privilege runtime roles to ${SA_EMAIL}."

# ------------------------------------------------------------------------------
# 6. Provision Firestore (default) Native Database & Secret Manager Secrets
# ------------------------------------------------------------------------------
echo "==> [6/7] Provisioning Firestore Native Database & Secret Manager secrets..."
if gcloud firestore databases describe --database="(default)" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "    Firestore (default) database already exists."
else
  gcloud firestore databases create \
    --database="(default)" \
    --location="${REGION}" \
    --type=firestore-native \
    --project="${PROJECT_ID}"
fi

SECRETS=(
  "medops-pagerduty-webhook-token"
  "medops-ehr-fhir-api-token"
  "medops-hitl-signing-key"
)

for SECRET_ID in "${SECRETS[@]}"; do
  if ! gcloud secrets describe "${SECRET_ID}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${SECRET_ID}" \
      --replication-policy="automatic" \
      --project="${PROJECT_ID}"
    printf "argolis-live-secret-%s-%s" "${SECRET_ID}" "$(date +%s)" | \
      gcloud secrets versions add "${SECRET_ID}" --data-file=- --project="${PROJECT_ID}"
  fi
done
echo "    Secret Manager secrets verified."

# ------------------------------------------------------------------------------
# 7. Write Local .env File & Seed Firestore medical_devices Collection
# ------------------------------------------------------------------------------
echo "==> [7/7] Writing local .env and seeding Firestore 'medical_devices' collection..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cat > "${REPO_ROOT}/.env" <<EOF
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=${REGION}
GOOGLE_GENAI_USE_VERTEXAI=TRUE
MEDOPS_USE_LIVE_FIRESTORE=true
MEDOPS_ENABLE_CLOUD_TRACE=true
MEDOPS_ENABLE_CLOUD_DLP=false
EOF

echo ""
echo "=================================================================="
echo " Bootstrap Complete! Final Step — Set Application Default Credentials:"
echo "   gcloud auth application-default login"
echo "   gcloud auth application-default set-quota-project ${PROJECT_ID}"
echo ""
echo " Then seed Firestore & run live Gemini model tests:"
echo "   cd ${REPO_ROOT}"
echo "   GOOGLE_CLOUD_PROJECT=${PROJECT_ID} MEDOPS_USE_LIVE_FIRESTORE=true .venv/bin/python -m scripts.seed_firestore"
echo "   GOOGLE_CLOUD_PROJECT=${PROJECT_ID} .venv/bin/python scripts/run_live_model_test.py"
echo "=================================================================="
