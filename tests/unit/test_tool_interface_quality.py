"""Interface-quality tests: docstrings, naming, schemas and guided errors.

These enforce the 'Tool & Interface Design' standards on every tool exposed
to an LLM, so a future change cannot silently regress them.
"""

from __future__ import annotations

import inspect
import re

import pytest
from google.adk.tools.function_tool import FunctionTool

from gf_agent import agent as agent_module
from gf_agent.tools._errors import GuidedToolError, guided_errors

_ALL_LLM_AGENTS = [
    agent_module.root_agent, agent_module.sourcing_agent,
    agent_module.gluten_verification_agent, agent_module.health_assessment_agent,
    agent_module.cost_analysis_agent, agent_module.report_critic_agent,
]


def _function_tools():
  seen = {}
  for a in _ALL_LLM_AGENTS:
    for t in a.tools:
      if isinstance(t, FunctionTool) and t.name not in ("exit_loop",):
        seen[t.name] = t.func
      elif callable(t) and inspect.isfunction(t) and t.__name__ != "exit_loop":
        seen[t.__name__] = t
  return seen


TOOLS = _function_tools()


def test_tools_discovered():
  assert len(TOOLS) >= 8


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_tool_has_comprehensive_docstring(name):
  doc = inspect.getdoc(TOOLS[name]) or ""
  assert len(doc.splitlines()[0]) > 20, "first line must describe the purpose"
  assert "Args:" in doc and "Returns:" in doc
  params = [p for p in inspect.signature(TOOLS[name]).parameters if p != "tool_context"]
  for p in params:
    assert re.search(rf"\b{p}\b", doc), f"parameter '{p}' undocumented"


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_tool_name_is_descriptive(name):
  assert re.fullmatch(r"[a-z]+(_[a-z0-9]+){2,}", name), "use verb_object_qualifier names"
  assert name.split("_")[0] in {
      "find", "list", "check", "lookup", "assess", "rank", "calculate",
      "submit", "record"}


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_tool_declaration_has_json_schema(name):
  decl = FunctionTool(TOOLS[name])._get_declaration()
  schema = decl.parameters_json_schema or (decl.parameters and decl.parameters.model_dump())
  assert schema, "tool must expose an explicit parameter schema"


def test_guided_error_from_custom_exception():
  @guided_errors
  def tool():
    raise GuidedToolError("X", "bad", "do y")
  assert tool() == {"status": "error", "error_code": "X", "message": "bad", "recovery_hint": "do y"}


def test_unexpected_exception_does_not_crash_and_hides_details():
  @guided_errors
  def tool():
    raise RuntimeError("secret internal detail")
  r = tool()
  assert r["error_code"] == "INTERNAL_TOOL_ERROR"
  assert "secret internal detail" not in str(r)
  assert r["recovery_hint"]
