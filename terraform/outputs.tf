output "agent_service_account_email" {
  description = "Least-privilege service account email for MedOps Sentinel Agent"
  value       = google_service_account.medops_agent_sa.email
}

output "firestore_database_name" {
  description = "Firestore Native database name storing sessions, memories, and biomedical assets"
  value       = google_firestore_database.medops_firestore_db.name
}
