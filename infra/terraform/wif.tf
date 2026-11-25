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

# CI: jobs from THIS repository's main branch (enforced by the provider's
# attribute_condition above) may impersonate the eval-only identity.
resource "google_service_account_iam_member" "ci_wif" {
  service_account_id = google_service_account.ci_eval.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# Deploy: a SEPARATE pool whose provider only accepts tokens from jobs that
# run in the protected GitHub Environment (human approval) on main.
resource "google_iam_workload_identity_pool" "github_deploy" {
  project                   = var.project_id
  workload_identity_pool_id = "gf-agent-github-deploy"
  display_name              = "GF agent GitHub deploy"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github_deploy" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_deploy.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc-deploy"
  display_name                       = "GitHub OIDC production env"

  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.repository"  = "assertion.repository"
    "attribute.environment" = "assertion.environment"
  }

  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/main' && assertion.environment == '${var.github_deploy_environment}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_deploy.name}/attribute.repository/${var.github_repository}"
}
