terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.30"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Enable Required Google Cloud APIs for Gemini Enterprise Agent Platform
resource "google_project_service" "agent_platform_apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "firestore.googleapis.com",
    "secretmanager.googleapis.com",
    "dlp.googleapis.com",
    "cloudtrace.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "modelarmor.googleapis.com",
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# 2. Provision Native Google Cloud Firestore Database for Persistent Sessions, Memories & Assets
resource "google_firestore_database" "medops_firestore_db" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.agent_platform_apis]
}

# 3. Provision Least-Privilege Agent Service Account (Enterprise Governance - Part 4)
resource "google_service_account" "medops_agent_sa" {
  account_id   = "medops-sentinel-agent-sa"
  display_name = "MedOps Sentinel Agent Least-Privilege Identity"
  description  = "Dedicated identity for MedOps Sentinel Agent on Gemini Enterprise Agent Platform"
}

resource "google_project_iam_member" "medops_agent_least_privilege_roles" {
  for_each = toset([
    "roles/datastore.user",
    "roles/secretmanager.secretAccessor",
    "roles/aiplatform.user",
    "roles/cloudtrace.agent",
    "roles/logging.logWriter",
    "roles/dlp.deidentifyTemplatesReader",
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.medops_agent_sa.email}"
}

# 4. Provision Google Cloud Secret Manager Secrets (Zero Hardcoded Keys)
resource "google_secret_manager_secret" "medops_secrets" {
  for_each = toset([
    "medops-pagerduty-webhook-token",
    "medops-ehr-fhir-api-token",
    "medops-hitl-signing-key",
  ])
  secret_id = each.key
  replication {
    auto {}
  }
  depends_on = [google_project_service.agent_platform_apis]
}
