# Developer shortcuts. Run `make help`.
.PHONY: help install lint test eval-live evalset playground web tf-init tf-plan tf-apply deploy smoke audit

PROJECT ?= $(GOOGLE_CLOUD_PROJECT)
REGION ?= us-central1

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies into the active venv
	pip install -e ".[dev]" && pre-commit install

lint: ## Ruff lint (incl. bandit security rules)
	ruff check .

test: ## Offline test suite: unit, golden dataset, security, integration
	pytest -q

audit: ## Dependency vulnerability scan
	pip-audit

evalset: ## Regenerate the golden ADK eval set JSON
	python scripts/build_evalset.py

eval-live: ## Live ADK evaluation against Gemini (needs gcloud auth)
	GOOGLE_CLOUD_LOCATION=global GOOGLE_GENAI_USE_ENTERPRISE=TRUE adk eval gf_agent tests/eval/gf_agent.evalset.json --config_file_path tests/eval/test_config.json --print_detailed_results
	GOOGLE_CLOUD_LOCATION=global GOOGLE_GENAI_USE_ENTERPRISE=TRUE adk eval gf_agent tests/eval/guardrail/guardrail.evalset.json --config_file_path tests/eval/guardrail/test_config.json --print_detailed_results

web: ## Local ADK web UI (HITL approval dialog appears in the UI)
	adk web --port 8080

tf-init: ## Terraform init
	cd infra/terraform && terraform init

tf-plan: ## Terraform plan (review before apply)
	cd infra/terraform && terraform plan -out=tfplan

tf-apply: ## Terraform apply the reviewed plan
	cd infra/terraform && terraform apply tfplan

deploy: ## Deploy to Agent Runtime (manual; CI uses deploy.yml with approval)
	adk deploy agent_engine --project $(PROJECT) --region $(REGION) \
	  --display_name gf-sourcing-agent --otel_to_cloud \
	  --service_account gf-agent-runtime@$(PROJECT).iam.gserviceaccount.com gf_agent

smoke: ## Smoke test a deployed agent: make smoke AGENT_ENGINE_ID=123
	python scripts/smoke_test.py --project $(PROJECT) --location $(REGION) --agent-engine-id $(AGENT_ENGINE_ID)
