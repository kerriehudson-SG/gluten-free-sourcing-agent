terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.10, < 8.0"
    }
  }

  # Remote state in a versioned, private GCS bucket (created by
  # scripts/bootstrap_argolis.sh). Partial config; bucket supplied at init:
  #   terraform init -backend-config="bucket=<PROJECT_ID>-tfstate"
  backend "gcs" {
    prefix = "gf-sourcing-agent"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
