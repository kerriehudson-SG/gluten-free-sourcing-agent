#!/usr/bin/env bash
# One-time Argolis bootstrap with human approval gates.
#
# Usage (in Cloud Shell, from the repo root):
#   ./scripts/bootstrap_argolis.sh <PROJECT_ID> <GITHUB_OWNER/REPO> [REGION]
#
# What it does (each stage asks you to confirm first):
#   1. Sets the gcloud project and enables the bootstrap APIs.
#   2. Creates a private, versioned GCS bucket for Terraform state.
#   3. terraform init + plan -> shows the plan -> asks for approval -> apply.
#   4. Generates the PII salt and stores it ONLY in Secret Manager.
#   5. Creates a Model Armor template for prompt-injection screening.
#   6. Prints the values to paste into GitHub repository variables.
set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <PROJECT_ID> <GITHUB_OWNER/REPO> [REGION]}"
GITHUB_REPO="${2:?Usage: $0 <PROJECT_ID> <GITHUB_OWNER/REPO> [REGION]}"
REGION="${3:-us-central1}"
TF_DIR="$(cd "$(dirname "$0")/../infra/terraform" && pwd)"
STATE_BUCKET="${PROJECT_ID}-tfstate"
SALT_SECRET="gf-agent-pii-hash-salt"
ARMOR_TEMPLATE="gf-agent-template"

confirm() {
  read -r -p "$1 [y/N] " reply
  [[ "${reply}" =~ ^[Yy]$ ]] || { echo "Stopped by user."; exit 1; }
}

echo "== Project: ${PROJECT_ID} | Repo: ${GITHUB_REPO} | Region: ${REGION}"
confirm "Stage 1: set gcloud project and enable bootstrap APIs?"
gcloud config set project "${PROJECT_ID}"
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com \
  storage.googleapis.com iam.googleapis.com

confirm "Stage 2: create private Terraform state bucket gs://${STATE_BUCKET}?"
if ! gcloud storage buckets describe "gs://${STATE_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${STATE_BUCKET}" --location="${REGION}" \
    --uniform-bucket-level-access --public-access-prevention
  gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning
fi

echo "== Stage 3: Terraform"
cat > "${TF_DIR}/terraform.tfvars" <<EOF
project_id        = "${PROJECT_ID}"
region            = "${REGION}"
github_repository = "${GITHUB_REPO}"
EOF
terraform -chdir="${TF_DIR}" init -input=false -backend-config="bucket=${STATE_BUCKET}"
terraform -chdir="${TF_DIR}" plan -input=false -out=tfplan
confirm "Review the plan above. Apply it?"
terraform -chdir="${TF_DIR}" apply -input=false tfplan

confirm "Stage 4: generate a random PII salt and store it in Secret Manager (value is never printed)?"
EXISTING_VERSIONS="$(gcloud secrets versions list "${SALT_SECRET}" --filter="state=ENABLED" --format="value(name)")"
if [[ -z "${EXISTING_VERSIONS}" ]]; then
  openssl rand -hex 32 | gcloud secrets versions add "${SALT_SECRET}" --data-file=-
else
  echo "Salt already present; not rotating."
fi

confirm "Stage 5: create Model Armor template ${ARMOR_TEMPLATE} (prompt-injection + RAI filters)?"
gcloud config set api_endpoint_overrides/modelarmor "https://modelarmor.${REGION}.rep.googleapis.com/"
if ! gcloud model-armor templates describe "${ARMOR_TEMPLATE}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud model-armor templates create "${ARMOR_TEMPLATE}" --location="${REGION}" \
    --pi-and-jailbreak-filter-settings-enforcement=enabled \
    --pi-and-jailbreak-filter-settings-confidence-level=medium-and-above \
    --malicious-uri-filter-settings-enforcement=enabled \
    --rai-settings-filters='[{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"DANGEROUS","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"SEXUALLY_EXPLICIT","confidenceLevel":"MEDIUM_AND_ABOVE"}]'
fi
echo
echo "== Stage 6: add these as GitHub repository VARIABLES (Settings > Secrets and variables > Actions > Variables)"
echo "GCP_PROJECT_ID=${PROJECT_ID}"
echo "GCP_REGION=${REGION}"
echo "GCP_WORKLOAD_IDENTITY_PROVIDER=$(terraform -chdir="${TF_DIR}" output -raw workload_identity_provider)"
echo "GCP_DEPLOY_WORKLOAD_IDENTITY_PROVIDER=$(terraform -chdir="${TF_DIR}" output -raw deploy_workload_identity_provider)"
echo "GCP_CI_SERVICE_ACCOUNT=$(terraform -chdir="${TF_DIR}" output -raw ci_eval_service_account)"
echo "GCP_DEPLOY_SERVICE_ACCOUNT=$(terraform -chdir="${TF_DIR}" output -raw deployer_service_account)"
echo "GCP_RUNTIME_SERVICE_ACCOUNT=$(terraform -chdir="${TF_DIR}" output -raw runtime_service_account)"
echo "GF_MODEL_ARMOR_TEMPLATE=projects/${PROJECT_ID}/locations/${REGION}/templates/${ARMOR_TEMPLATE}"
echo
echo "None of these values are secrets. No keys were created."
