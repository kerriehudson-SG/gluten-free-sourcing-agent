output "runtime_service_account" {
  description = "Pass to: adk deploy agent_engine --service_account=..."
  value       = google_service_account.runtime.email
}

output "ci_eval_service_account" {
  description = "GitHub secret/variable GCP_CI_SERVICE_ACCOUNT."
  value       = google_service_account.ci_eval.email
}

output "deployer_service_account" {
  description = "GitHub variable GCP_DEPLOY_SERVICE_ACCOUNT."
  value       = google_service_account.deployer.email
}

output "workload_identity_provider" {
  description = "GitHub variable GCP_WORKLOAD_IDENTITY_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "pii_salt_secret" {
  description = "Secret ID to populate out-of-band."
  value       = google_secret_manager_secret.pii_salt.secret_id
}
