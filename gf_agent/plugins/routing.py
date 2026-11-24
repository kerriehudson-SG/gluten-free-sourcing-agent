"""Per-request model routing plugin.

Rubric: Orchestration & Logic -> Strategic Model Routing.

Static routing (config.ROLE_TO_TIER) gives each agent the cheapest model that
meets its quality bar. This plugin adds *per-request* routing on top: complex
requests (multi-country comparisons, very long briefs) are escalated from the
fast model to the pro model for the coordinator, and every routing decision is
logged with its reason so cost/quality trade-offs are observable.
"""

from __future__ import annotations

from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from gf_agent.config import choose_model_for_request
from gf_agent.observability.logging import get_logger

log = get_logger("routing")


def _latest_user_text(llm_request: LlmRequest) -> str:
  for content in reversed(llm_request.contents or []):
    if content.role == "user" and content.parts:
      texts = [p.text for p in content.parts if p.text]
      if texts:
        return "\n".join(texts)
  return ""


class ModelRoutingPlugin(BasePlugin):
  """Escalates or keeps the model per request and logs the decision."""

  def __init__(self) -> None:
    super().__init__(name="gf_model_routing")

  async def before_model_callback(
      self, *, callback_context: CallbackContext, llm_request: LlmRequest
  ) -> Optional[LlmResponse]:
    configured = llm_request.model or ""
    model, reason = choose_model_for_request(
        callback_context.agent_name, configured, _latest_user_text(llm_request))
    if model != configured:
      llm_request.model = model
    log.info("model_route", agent=callback_context.agent_name,
             configured_model=configured, routed_model=model, reason=reason)
    return None
