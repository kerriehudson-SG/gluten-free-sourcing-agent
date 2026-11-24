# Secret container only. The secret VALUE is added out-of-band so it never
# appears in Terraform state or in git:
#   openssl rand -hex 32 | gcloud secrets versions add gf-agent-pii-hash-salt --data-file=-

resource "google_secret_manager_secret" "pii_salt" {
  project   = var.project_id
  secret_id = var.pii_salt_secret_id

  replication {
    auto {}
  }

  labels = {
    app       = "gf-sourcing-agent"
    data_type = "crypto-salt"
  }

  depends_on = [google_project_service.apis]
}

# Only the runtime identity can read this one secret.
resource "google_secret_manager_secret_iam_member" "runtime_reads_salt" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.pii_salt.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
