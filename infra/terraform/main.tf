# Enable only the APIs the agent actually needs.
locals {
  required_apis = [
    "aiplatform.googleapis.com",           # Gemini, Agent Runtime, Sessions, Memory Bank
    "secretmanager.googleapis.com",        # PII salt secret
    "dlp.googleapis.com",                  # Sensitive Data Protection (PII de-identification)
    "modelarmor.googleapis.com",           # Prompt / response screening
    "cloudtrace.googleapis.com",           # Distributed tracing
    "telemetry.googleapis.com",            # OpenTelemetry ingestion (--otel_to_cloud)
    "logging.googleapis.com",              # Structured logs
    "iam.googleapis.com",                  # Service accounts
    "iamcredentials.googleapis.com",       # Short-lived tokens for WIF
    "sts.googleapis.com",                  # Workload Identity Federation token exchange
    "cloudresourcemanager.googleapis.com", # IAM bindings
    "serviceusage.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# Data-access audit logs for secret reads (who accessed the salt, and when).
resource "google_project_iam_audit_config" "secretmanager" {
  project = var.project_id
  service = "secretmanager.googleapis.com"
  audit_log_config {
    log_type = "DATA_READ"
  }
}
