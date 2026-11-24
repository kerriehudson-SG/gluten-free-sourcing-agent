"""Deterministic (non-LLM) agent that publishes the final report.

The last step of `gf_sourcing_pipeline`. It reads `final_report` from session
state and emits it as the pipeline's final message, so the coordinator (which
calls the pipeline through AgentTool) always receives the validated report,
not the critic's internal `exit_loop` call. No model call, no extra cost.
"""

from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from gf_agent.observability.logging import get_logger

log = get_logger("report_publisher")

NO_REPORT_TEXT = (
    "The specialist pipeline did not produce a report. Ask the user to confirm "
    "the country and product categories, then try again."
)


def render_report(report: object) -> str:
  """Serialises the report from state into text for the coordinator."""
  if report is None or report == "":
    return NO_REPORT_TEXT
  if isinstance(report, str):
    return report
  return json.dumps(report, ensure_ascii=False, indent=2)


class ReportPublisherAgent(BaseAgent):
  """Emits state['final_report'] as the pipeline's final response."""

  async def _run_async_impl(
      self, ctx: InvocationContext
  ) -> AsyncGenerator[Event, None]:
    report = ctx.session.state.get("final_report")
    if ctx.session.state.get("guardrail_last_block") and not report:
      report = ("A safety guardrail blocked part of the specialist pipeline, so no "
                "report was produced. Tell the user and ask them to rephrase.")
    log.info("report_published", has_report=report is not None,
             critique_pending=bool(ctx.session.state.get("report_critique")))
    yield Event(
        author=self.name,
        invocation_id=ctx.invocation_id,
        branch=ctx.branch,
        content=types.Content(role="model", parts=[types.Part(text=render_report(report))]),
    )
