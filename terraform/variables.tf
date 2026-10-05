variable "project_id" {
  description = "Target Google Cloud Project ID for MedOps Sentinel Agent"
  type        = string
}

variable "region" {
  description = "Primary Google Cloud region for Vertex AI Agent Runtime and Firestore"
  type        = string
  default     = "us-east4"
}
