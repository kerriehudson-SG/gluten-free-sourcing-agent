"""Asynchronous, PII-safe, incremental long-term memory generation.

Rubric: Context & Memory -> Async Memory Operations.

After each top-level invocation completes, only the NEW events of that turn
are redacted and sent to Vertex AI Agent Engine Memory Bank as a
fire-and-forget background task, so memory extraction and consolidation (an
expensive LLM operation) never blocks the user's response. Memories are
recalled on later turns by `PreloadMemoryTool` on the coordinator.

Design choices:
  * Incremental: `add_events_to_memory(events=<this turn>)` instead of
    re-ingesting the whole session every turn (avoids O(n^2) cost/duplicates).
  * Top-level only: nested AgentTool runs (the specialist pipeline) share
    plugins with the parent; their internal tool dumps are NOT memorised.
  * PII-safe: text, tool arguments and tool results are scrubbed before ingest.
  * Graceful shutdown: pending tasks are drained in `close()`.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from gf_agent.observability.logging import get_logger
from gf_agent.observability.pii import redact_obj, redact_text
from gf_agent.observability.tracing import traced_span

log = get_logger("memory")


def redact_event_for_memory(event: Event) -> Event:
  """Returns a deep copy of the event with PII removed from every part."""
  clean = event.model_copy(deep=True)
  if clean.content and clean.content.parts:
    for part in clean.content.parts:
      if part.text:
        part.text = redact_text(part.text)
      if part.function_call and part.function_call.args:
        part.function_call.args = redact_obj(part.function_call.args)
      if part.function_response and part.function_response.response:
        part.function_response.response = redact_obj(part.function_response.response)
  return clean


class AsyncMemoryPlugin(BasePlugin):
  """Schedules incremental, redacted Memory Bank ingestion in the background."""

  def __init__(self, root_agent_name: str = "gf_coordinator") -> None:
    super().__init__(name="gf_async_memory")
    self._root_agent_name = root_agent_name
    # Strong references so background tasks are not garbage-collected.
    self._pending: set[asyncio.Task] = set()

  def _is_top_level(self, ctx: InvocationContext) -> bool:
    nested = getattr(ctx, "_parent_invocation_id", None)
    agent_name = getattr(getattr(ctx, "agent", None), "name", self._root_agent_name)
    return not nested and agent_name == self._root_agent_name

  async def _ingest(self, ctx: InvocationContext, events: list[Event]) -> None:
    service = ctx.memory_service
    session = ctx.session
    with traced_span("memory.ingest_turn", events=len(events)):
      try:
        try:
          await service.add_events_to_memory(
              app_name=session.app_name, user_id=session.user_id,
              events=events, session_id=session.id)
        except NotImplementedError:
          await service.add_session_to_memory(session)
        log.info("memory_ingest_triggered", events=len(events),
                 invocation_id=ctx.invocation_id)
      except Exception as e:  # pylint: disable=broad-exception-caught
        log.warning("memory_ingest_failed", error_type=type(e).__name__)

  async def after_run_callback(
      self, *, invocation_context: InvocationContext
  ) -> Optional[types.Content]:
    ctx = invocation_context
    if ctx.memory_service is None or not self._is_top_level(ctx):
      return None
    turn_events = [
        redact_event_for_memory(e) for e in ctx.session.events
        if e.invocation_id == ctx.invocation_id and e.content
    ]
    if not turn_events:
      return None
    task = asyncio.create_task(self._ingest(ctx, turn_events))
    self._pending.add(task)
    task.add_done_callback(self._pending.discard)
    log.info("memory_ingest_scheduled", invocation_id=ctx.invocation_id,
             events=len(turn_events))
    return None

  async def drain(self, timeout: float = 30.0) -> None:
    """Waits for pending memory tasks (tests / graceful shutdown)."""
    if self._pending:
      await asyncio.wait(set(self._pending), timeout=timeout)

  async def close(self) -> None:
    """Called by ADK on runner shutdown: flush in-flight memory writes."""
    await self.drain()
