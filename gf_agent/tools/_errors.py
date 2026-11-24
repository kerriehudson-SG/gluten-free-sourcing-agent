"""Guided error handling for agent tools.

Rubric: Tool & Interface Design -> Guided Error Handling.

Tools must NEVER raise uncaught exceptions back into the agent loop. Instead they
return a structured error payload that tells the LLM *what went wrong* and *how to
recover* (which argument to fix, which tool to call next, or what to ask the user).
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from pydantic import ValidationError

from gf_agent.schemas import ToolError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class GuidedToolError(Exception):
  """Raised inside a tool to return a guided, recoverable error to the LLM."""

  def __init__(self, error_code: str, message: str, recovery_hint: str):
    super().__init__(message)
    self.error_code = error_code
    self.message = message
    self.recovery_hint = recovery_hint


def tool_error(error_code: str, message: str, recovery_hint: str) -> dict:
  """Builds the standard error payload returned to the LLM.

  Args:
    error_code: Stable machine-readable code, e.g. "UNSUPPORTED_COUNTRY".
    message: Human-readable description of what went wrong.
    recovery_hint: Concrete instruction for the LLM on how to recover.

  Returns:
    A dict matching the ToolError schema with status="error".
  """
  return ToolError(
      error_code=error_code, message=message, recovery_hint=recovery_hint
  ).model_dump()


def guided_errors(func: F) -> F:
  """Decorator converting exceptions into guided ToolError payloads.

  - GuidedToolError -> its own code, message and recovery hint.
  - pydantic.ValidationError -> INVALID_ARGUMENTS with the offending fields.
  - Any other exception -> INTERNAL_TOOL_ERROR with a safe retry hint
    (details are logged, not leaked to the model).
  """

  @functools.wraps(func)
  def wrapper(*args: Any, **kwargs: Any) -> Any:
    try:
      return func(*args, **kwargs)
    except GuidedToolError as e:
      return tool_error(e.error_code, e.message, e.recovery_hint)
    except ValidationError as e:
      problems = "; ".join(
          f"{'.'.join(str(p) for p in err['loc']) or 'input'}: {err['msg']}"
          for err in e.errors()[:8]
      )
      return tool_error(
          "INVALID_ARGUMENTS",
          f"One or more arguments failed schema validation: {problems}.",
          "Re-read the tool docstring, correct the listed fields to the "
          "documented types/allowed values, and call the tool again. If the "
          "value must come from the user, ask the user for it.",
      )
    except Exception:  # pylint: disable=broad-exception-caught
      logger.exception("Unexpected error in tool %s", func.__name__)
      return tool_error(
          "INTERNAL_TOOL_ERROR",
          f"The tool '{func.__name__}' failed unexpectedly.",
          "Do not retry with identical arguments. Re-check the inputs against "
          "the tool docstring; if they look correct, continue without this "
          "tool and tell the user this step could not be completed.",
      )

  return wrapper  # type: ignore[return-value]
