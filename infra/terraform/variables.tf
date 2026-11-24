variable "project_id" {
  description = "Argolis / Google Cloud project ID that hosts the agent."
  type        = string
}

variable "region" {
  description = "Region for Agent Runtime (Agent Engine) and regional APIs."
  type        = string
  default     = "us-central1"
}

variable "github_repository" {
  description = "GitHub repository allowed to authenticate via Workload Identity Federation, as 'owner/name'."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must look like 'owner/repo'."
  }
}

variable "github_deploy_environment" {
  description = "GitHub Environment (with required reviewers) that is allowed to deploy."
  type        = string
  default     = "production"
}

variable "pii_salt_secret_id" {
  description = "Secret Manager secret ID for the log pseudonymisation salt (value is added out-of-band, never in Terraform state)."
  type        = string
  default     = "gf-agent-pii-hash-salt"
}

variable "grant_reasoning_engine_service_agent" {
  description = "Grant the Agent Runtime (Reasoning Engine) service agent token-creator on the runtime SA. Enable after the first deploy if it reports a getAccessToken permission error."
  type        = bool
  default     = false
}
