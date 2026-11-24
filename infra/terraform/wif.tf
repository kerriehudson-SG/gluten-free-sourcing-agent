# Workload Identity Federation: GitHub Actions authenticates with short-lived
# OIDC tokens. No long-lived JSON keys exist anywhere.

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "gf-agent-github"
  display_name              = "GF agent GitHub Actions"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
    "attribute.event_name" = "assertion.event_name"
  }

  # Only tokens from THIS repository's main branch are accepted at all.
  # (PR jobs never receive cloud credentials; they run fully offline.)
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/main'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Bindings use the exact GitHub OIDC subject (always present in the token):
#   main-branch jobs:        repo:<owner>/<repo>:ref:refs/heads/main
#   protected environment:   repo:<owner>/<repo>:environment:<env>
locals {
  wif_pool = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/subject"
}

# CI jobs on main may impersonate the eval-only identity (predict-only custom role).
resource "google_service_account_iam_member" "ci_wif" {
  service_account_id = google_service_account.ci_eval.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_pool}/repo:${var.github_repository}:ref:refs/heads/main"
}

# Only jobs running in the protected GitHub Environment (required reviewers =
# human approval) of THIS repo may impersonate the deployer.
resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "${local.wif_pool}/repo:${var.github_repository}:environment:${var.github_deploy_environment}"
}
