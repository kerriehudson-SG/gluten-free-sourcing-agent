# Least-privilege identities. Three service accounts, each with only the
# roles it needs. No service account keys are ever created.

# 1. Runtime identity of the deployed agent on Agent Runtime.
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "gf-agent-runtime"
  display_name = "GF Sourcing Agent - runtime"
  description  = "Runs the agent on Agent Runtime. Calls Gemini, Sessions, Memory Bank, DLP, Model Armor; writes logs/traces."
  depends_on   = [google_project_service.apis]
}

locals {
  runtime_roles = [
    "roles/aiplatform.user",         # Gemini + Agent Engine sessions/memory
    "roles/logging.logWriter",       # structured logs
    "roles/cloudtrace.agent",        # trace export (includes telemetry.traces.write for OTel)
    "roles/dlp.user",                # de-identify content
    "roles/modelarmor.user",         # sanitize prompts
    "roles/monitoring.metricWriter", # OTel metrics from --otel_to_cloud
  ]
}

resource "google_project_iam_member" "runtime" {
  for_each = toset(local.runtime_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.runtime.email}"
}

# 2. CI identity: runs live evals only (calls Gemini). Cannot deploy.
resource "google_service_account" "ci_eval" {
  project      = var.project_id
  account_id   = "gf-agent-ci-eval"
  display_name = "GF Sourcing Agent - CI evaluation"
  description  = "Used by GitHub Actions CI to run the ADK evaluation suite."
  depends_on   = [google_project_service.apis]
}

# Custom role: CI only needs to call Gemini (generateContent = endpoints.predict).
resource "google_project_iam_custom_role" "gemini_invoker" {
  project     = var.project_id
  role_id     = "gfAgentGeminiInvoker"
  title       = "GF Agent Gemini invoker (CI evals)"
  description = "Minimum permission to call Gemini models for evaluation."
  permissions = ["aiplatform.endpoints.predict"]
}

resource "google_project_iam_member" "ci_eval_invoker" {
  project = var.project_id
  role    = google_project_iam_custom_role.gemini_invoker.id
  member  = "serviceAccount:${google_service_account.ci_eval.email}"
}

# 3. Deploy identity: creates/updates the Agent Runtime instance. Only usable
#    from the protected GitHub Environment (manual approval) - see wif.tf.
resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "gf-agent-deployer"
  display_name = "GF Sourcing Agent - deployer"
  description  = "Used by the GitHub Actions deploy workflow after human approval."
  depends_on   = [google_project_service.apis]
}

locals {
  deployer_roles = [
    "roles/aiplatform.user",                   # create/update reasoning engines
    "roles/serviceusage.serviceUsageConsumer", # use enabled APIs
  ]
}

resource "google_project_iam_member" "deployer" {
  for_each = toset(local.deployer_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# The deployer may attach ONLY the runtime service account to the agent
# (resource-level binding, not project-wide).
resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

# Agent Runtime runs the container as the custom runtime SA via its Reasoning
# Engine service agent. That service agent only exists after the first
# deployment attempt, so this binding is opt-in (see docs/SETUP_GUIDE.md, Part F).
data "google_project" "this" {
  project_id = var.project_id
}

resource "google_service_account_iam_member" "re_agent_token_creator" {
  count              = var.grant_reasoning_engine_service_agent ? 1 : 0
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}
