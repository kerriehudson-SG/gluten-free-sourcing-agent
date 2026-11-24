"""Runtime configuration: model routing and secure secret access.

Rubric:
  - Orchestration & Logic -> Strategic Model Routing (MODEL_ROUTING below).
  - Infrastructure & CI/CD -> Secure Secret Management (get_secret below).

No secrets are hardcoded. Non-secret settings come from environment variables
(see `.env.example`). Secrets are fetched at runtime from Google Cloud Secret
Manager using the runtime service account's Application Default Credentials;
the service account is granted `roles/secretmanager.secretAccessor` on the
individual secret only (see infra/terraform/secrets.tf).
"""

from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategic model routing
# ---------------------------------------------------------------------------
# Each agent role is mapped to the cheapest model that meets its quality bar.
# All models are overridable per environment without code changes.


@dataclass(frozen=True)
class ModelRouting:
  """Maps agent roles to Gemini models by task complexity."""

  # Fast, low-cost: high-volume routing, extraction, arithmetic summaries.
  lite: str = os.getenv("GF_MODEL_LITE", "gemini-2.5-flash-lite")
  # Balanced: conversational coordination, tool use, search, critique.
  fast: str = os.getenv("GF_MODEL_FAST", "gemini-3.5-flash")
  # Strongest reasoning: safety-critical gluten judgement and final synthesis.
  pro: str = os.getenv("GF_MODEL_PRO", "gemini-3.1-pro-preview")

  def for_role(self, role: str) -> str:
    """Returns the model for an agent role.

    Args:
      role: One of the keys in ROLE_TO_TIER.

    Returns:
      The model name for the role's tier.
    """
    tier = ROLE_TO_TIER.get(role, "fast")
    return getattr(self, tier)


# Rationale is documented in docs/ARCHITECTURE.md#model-routing.
ROLE_TO_TIER: dict[str, str] = {
    "coordinator": "fast",            # multi-turn dialogue + tool calling
    "sourcing": "fast",               # tool use over catalogue + search
    "live_search": "fast",            # Google Search grounding
    "gluten_verification": "pro",     # safety-critical: false negatives harm users
    "health_assessment": "fast",      # deterministic tool does the scoring
    "cost_analysis": "lite",          # arithmetic is done by tools; cheap model
    "report_writer": "pro",           # long-context synthesis with citations
    "report_critic": "fast",          # rubric-style self-evaluation
}

MODEL_ROUTING = ModelRouting()

_COUNTRY_WORDS = (
    "australia", "new zealand", "united kingdom", " uk ", "britain", "england",
    "ireland", "germany", "france", "canada", "singapore",
)
COMPLEX_REQUEST_CHARS = 600


def choose_model_for_request(agent_name: str, configured_model: str, user_text: str
                             ) -> tuple[str, str]:
  """Per-request routing on top of the static role tiers.

  Escalates the coordinator from the fast to the pro model when a request is
  complex (compares several countries or is a very long brief). All other
  agents keep their statically routed model.

  Args:
    agent_name: Name of the agent about to call the model.
    configured_model: Model statically assigned to that agent.
    user_text: The user's latest message (may be empty).

  Returns:
    (model, reason) - the model to use and a short reason for logging.
  """
  if agent_name != "gf_coordinator" or configured_model != MODEL_ROUTING.fast:
    return configured_model, "static_role_tier"
  text = f" {user_text.lower()} "
  countries = sum(1 for w in _COUNTRY_WORDS if w in text)
  if countries >= 2:
    return MODEL_ROUTING.pro, f"escalated_multi_country({countries})"
  if len(user_text) > COMPLEX_REQUEST_CHARS:
    return MODEL_ROUTING.pro, "escalated_long_request"
  return configured_model, "static_role_tier"


# ---------------------------------------------------------------------------
# Non-secret settings
# ---------------------------------------------------------------------------


def _env(name: str, default: str = "") -> Callable[[], str]:
  return lambda: os.getenv(name, default)


def _flag(name: str) -> Callable[[], bool]:
  return lambda: os.getenv(name, "false").lower() == "true"


@dataclass(frozen=True)
class Settings:
  """Non-secret settings, read from the environment each time get_settings() is called."""

  project_id: str = field(default_factory=_env("GOOGLE_CLOUD_PROJECT"))
  location: str = field(default_factory=_env("GOOGLE_CLOUD_LOCATION", "us-central1"))
  # Agent Runtime sets GOOGLE_CLOUD_AGENT_ENGINE_ID automatically when deployed.
  agent_engine_id: str = field(default_factory=lambda: os.getenv("GF_AGENT_ENGINE_ID")
                               or os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", ""))
  enable_cloud_dlp: bool = field(default_factory=_flag("GF_ENABLE_CLOUD_DLP"))
  model_armor_template: str = field(default_factory=_env("GF_MODEL_ARMOR_TEMPLATE"))
  # If Model Armor is configured but unreachable: block (true) or fall back to
  # the local policy (false). Default false keeps the agent available.
  model_armor_fail_closed: bool = field(default_factory=_flag("GF_MODEL_ARMOR_FAIL_CLOSED"))
  enable_live_search: bool = field(default_factory=_flag("GF_ENABLE_LIVE_SEARCH"))
  pii_salt_secret_id: str = field(
      default_factory=_env("GF_PII_SALT_SECRET_ID", "gf-agent-pii-hash-salt"))
  log_level: str = field(default_factory=_env("GF_LOG_LEVEL", "INFO"))


def get_settings() -> Settings:
  """Returns settings read from the environment at call time."""
  return Settings()


# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=16)
def get_secret(secret_id: str, version: str = "latest") -> str | None:
  """Fetches a secret value from Google Cloud Secret Manager.

  Values are cached in memory for the life of the process and never logged.

  Args:
    secret_id: The Secret Manager secret ID (not the value).
    version: Secret version, defaults to "latest".

  Returns:
    The secret payload as a string, or None if Secret Manager is not
    configured/reachable (callers must degrade safely).
  """
  project = get_settings().project_id
  if not project:
    logger.warning("GOOGLE_CLOUD_PROJECT not set; secret %s unavailable", secret_id)
    return None
  try:
    from google.cloud import secretmanager  # pylint: disable=import-outside-toplevel

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")
  except Exception:  # pylint: disable=broad-exception-caught
    logger.warning("Could not access secret %s; using safe fallback", secret_id)
    return None
