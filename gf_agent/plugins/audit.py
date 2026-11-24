"""Audit plugin: intent-before / outcome-after logging for every action.

Rubric: Observability & Tracing -> Intent vs. Outcome Capture.

For each tool call we log:
  - `tool_intent`  BEFORE execution: which agent intends to call which tool,
    with (redacted) arguments and the reason the model stated, if any.
  - `tool_outcome` AFTER execution: success/error, error_code, duration and a
    compact result summary.
The same pattern is applied to agent runs and model calls (with model name,
which evidences model routing, and token usage).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from gf_agent.observability.logging import get_logger
from gf_agent.observability.pii import pseudonymize_user_id, redact_obj

log = get_logger("audit")


def summarize_result(result: Any) -> dict[str, Any]:
  """Builds a compact, PII-safe summary of a tool result for logging."""
  if not isinstance(result, dict):
    return {"type": type(result).__name__}
  summary: dict[str, Any] = {"status": result.get("status", "unknown")}
  for key in ("error_code", "gluten_status", "health_score", "is_healthy_choice",
              "draft_id", "state"):
    if key in result:
      summary[key] = result[key]
  for key in ("retailers", "products", "ranked_options", "options"):
    if isinstance(result.get(key), list):
      summary[f"{key}_count"] = len(result[key])
  if "error" in result and "status" not in result:
    err = str(result["error"])
    if "requires confirmation" in err:
      summary["status"] = "PENDING_HUMAN_APPROVAL"
    elif "rejected" in err:
      summary["status"] = "REJECTED_BY_HUMAN"
    else:
      summary["status"] = "error"
      summary["error"] = err[:200]
  return summary


class AuditPlugin(BasePlugin):
  """Logs intent and outcome for agent runs, model calls and tool calls."""

  def __init__(self) -> None:
    super().__init__(name="gf_audit")
    self._starts: dict[str, float] = {}

  # ---- Agents -------------------------------------------------------------
  async def before_agent_callback(self, *, agent: Any, callback_context: CallbackContext):
    log.info("agent_intent", agent=agent.name,
             invocation_id=callback_context.invocation_id,
             user=pseudonymize_user_id(callback_context.user_id))
    return None

  async def after_agent_callback(self, *, agent: Any, callback_context: CallbackContext):
    log.info("agent_outcome", agent=agent.name,
             invocation_id=callback_context.invocation_id,
             state_keys=sorted(k for k in callback_context.state.to_dict().keys()
                               if not k.startswith("temp:")))
    return None

  # ---- Models (evidence of strategic routing) ------------------------------
  async def before_model_callback(
      self, *, callback_context: CallbackContext, llm_request: LlmRequest
  ) -> Optional[LlmResponse]:
    log.info("model_intent", agent=callback_context.agent_name,
             model=llm_request.model,
             tools=sorted((llm_request.tools_dict or {}).keys()))
    return None

  async def after_model_callback(
      self, *, callback_context: CallbackContext, llm_response: LlmResponse
  ) -> Optional[LlmResponse]:
    usage = llm_response.usage_metadata
    log.info("model_outcome", agent=callback_context.agent_name,
             model=getattr(llm_response, "model_version", None),
             prompt_tokens=getattr(usage, "prompt_token_count", None),
             output_tokens=getattr(usage, "candidates_token_count", None),
             error_code=llm_response.error_code)
    return None

  # ---- Tools ---------------------------------------------------------------
  async def before_tool_callback(
      self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any
  ) -> Optional[dict]:
    call_id = getattr(tool_context, "function_call_id", None) or f"{tool.name}-{time.time_ns()}"
    self._starts[call_id] = time.perf_counter()
    log.info("tool_intent", agent=tool_context.agent_name, tool=tool.name,
             function_call_id=call_id, args=redact_obj(tool_args),
             requires_confirmation=bool(getattr(tool, "_require_confirmation", False)))
    return None

  async def after_tool_callback(
      self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any,
      result: dict[str, Any]
  ) -> Optional[dict]:
    call_id = getattr(tool_context, "function_call_id", None) or ""
    started = self._starts.pop(call_id, None)
    duration_ms = round((time.perf_counter() - started) * 1000, 1) if started else None
    log.info("tool_outcome", agent=tool_context.agent_name, tool=tool.name,
             function_call_id=call_id, duration_ms=duration_ms,
             outcome=summarize_result(result))
    return None

  async def on_tool_error_callback(
      self, *, tool: Any, tool_args: dict[str, Any], tool_context: Any,
      error: Exception
  ) -> Optional[dict]:
    log.error("tool_outcome", agent=tool_context.agent_name, tool=tool.name,
              outcome={"status": "exception", "error_type": type(error).__name__})
    return {
        "status": "error",
        "error_code": "TOOL_EXCEPTION",
        "message": f"{tool.name} failed with {type(error).__name__}.",
        "recovery_hint": "Check the arguments against the tool docstring and "
                         "retry once; otherwise continue without this tool and "
                         "tell the user.",
    }
