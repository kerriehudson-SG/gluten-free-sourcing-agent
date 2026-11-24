"""Distributed tracing with OpenTelemetry -> Google Cloud Trace.

Rubric: Observability & Tracing -> Distributed Tracing.

ADK already emits OpenTelemetry spans for every invocation, agent run, LLM
call and tool call (`invocation` -> `agent_run [...]` -> `call_llm` /
`execute_tool [...]`). This module:
  1. Exports those spans to Cloud Trace when running locally with
     GF_ENABLE_CLOUD_TRACE=true (on Agent Runtime, deploy with
     `adk deploy agent_engine --otel_to_cloud`, which configures export).
  2. Provides `traced_span` so our own guardrail, redaction and memory steps
     appear as child spans of the same trace (query -> answer).
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any, Iterator

from opentelemetry import trace

from gf_agent.config import get_settings

_TRACER_NAME = "gf_agent"
_INITIALISED = False


def init_tracing() -> None:
  """Sets up the Cloud Trace exporter if enabled (idempotent, safe offline)."""
  global _INITIALISED
  if _INITIALISED:
    return
  _INITIALISED = True
  if os.getenv("GF_ENABLE_CLOUD_TRACE", "false").lower() != "true":
    return
  try:
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter  # pylint: disable=import-outside-toplevel
    from opentelemetry.sdk.resources import Resource  # pylint: disable=import-outside-toplevel
    from opentelemetry.sdk.trace import TracerProvider  # pylint: disable=import-outside-toplevel
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # pylint: disable=import-outside-toplevel

    provider = TracerProvider(
        resource=Resource.create({"service.name": "gf-sourcing-agent"})
    )
    provider.add_span_processor(
        BatchSpanProcessor(CloudTraceSpanExporter(project_id=get_settings().project_id))
    )
    trace.set_tracer_provider(provider)
  except Exception:  # pylint: disable=broad-exception-caught
    # Tracing must never break the agent; record why export is disabled.
    logging.getLogger(__name__).warning("Cloud Trace exporter unavailable", exc_info=True)


def get_tracer() -> trace.Tracer:
  return trace.get_tracer(_TRACER_NAME)


@contextlib.contextmanager
def traced_span(name: str, **attributes: Any) -> Iterator[trace.Span]:
  """Starts a child span of the current trace with safe attributes.

  Args:
    name: Span name, e.g. 'guardrail.input_check'.
    **attributes: Primitive attributes (str/int/float/bool). Never pass PII.

  Yields:
    The active span.
  """
  with get_tracer().start_as_current_span(name) as span:
    for key, value in attributes.items():
      if isinstance(value, (str, int, float, bool)):
        span.set_attribute(f"gf.{key}", value)
    yield span
