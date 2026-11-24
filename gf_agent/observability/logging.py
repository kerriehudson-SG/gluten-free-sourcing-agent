"""Structured JSON logging with trace correlation and PII scrubbing.

Rubric: Observability & Tracing -> Structured JSON Logging.

Uses `structlog` to emit one JSON object per line on stdout. On Agent Runtime /
Cloud Run, Cloud Logging ingests these as structured `jsonPayload` entries, and
the `logging.googleapis.com/trace` and `spanId` fields link each log line to its
Cloud Trace span.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace

from gf_agent.config import get_settings
from gf_agent.observability.pii import redact_obj

_CONFIGURED = False


def _add_trace_context(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
  """Adds Cloud Logging trace-correlation fields from the active OTel span."""
  span = trace.get_current_span()
  ctx = span.get_span_context() if span else None
  if ctx and ctx.is_valid:
    trace_id = format(ctx.trace_id, "032x")
    project = get_settings().project_id
    event_dict["logging.googleapis.com/trace"] = (
        f"projects/{project}/traces/{trace_id}" if project else trace_id
    )
    event_dict["logging.googleapis.com/spanId"] = format(ctx.span_id, "016x")
    event_dict["trace_id"] = trace_id
  return event_dict


def _redact_pii(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
  """Final safety net: scrub PII from every field before it is written."""
  return redact_obj(event_dict)


_SEVERITY = {"debug": "DEBUG", "info": "INFO", "warn": "WARNING",
             "warning": "WARNING", "error": "ERROR", "exception": "ERROR",
             "critical": "CRITICAL"}


def _gcp_severity(_, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
  """Maps the log method to a Cloud Logging severity."""
  event_dict["severity"] = _SEVERITY.get(method_name, "DEFAULT")
  return event_dict


class _StdoutHandler(logging.StreamHandler):
  """StreamHandler that always writes to the *current* sys.stdout."""

  def emit(self, record: logging.LogRecord) -> None:
    self.stream = sys.stdout
    super().emit(record)


def configure_logging() -> None:
  """Configures structlog AND routes stdlib logging through it (idempotent).

  Our own `get_logger()` calls and every third-party/ADK `logging` call are
  rendered by the same pipeline: JSON, Cloud Logging severity, trace
  correlation and PII redaction.
  """
  global _CONFIGURED
  if _CONFIGURED:
    return
  level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
  shared: list[Any] = [
      structlog.contextvars.merge_contextvars,
      structlog.stdlib.add_logger_name,
      structlog.processors.add_log_level,
      _gcp_severity,
      structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
      _add_trace_context,
  ]
  structlog.configure(
      processors=[structlog.stdlib.filter_by_level, *shared,
                  structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
      wrapper_class=structlog.stdlib.BoundLogger,
      logger_factory=structlog.stdlib.LoggerFactory(),
      cache_logger_on_first_use=True,
  )
  formatter = structlog.stdlib.ProcessorFormatter(
      foreign_pre_chain=shared,
      processors=[
          structlog.stdlib.ProcessorFormatter.remove_processors_meta,
          structlog.processors.dict_tracebacks,
          _redact_pii,
          structlog.processors.EventRenamer("message"),
          structlog.processors.JSONRenderer(),
      ],
  )
  handler = _StdoutHandler()
  handler.setFormatter(formatter)
  root = logging.getLogger()
  root.handlers = [handler]
  root.setLevel(level)
  _CONFIGURED = True


def get_logger(name: str = "gf_agent") -> structlog.stdlib.BoundLogger:
  """Returns a structured logger bound with the component name."""
  configure_logging()
  return structlog.get_logger(name).bind(component=name, service="gf-sourcing-agent")
