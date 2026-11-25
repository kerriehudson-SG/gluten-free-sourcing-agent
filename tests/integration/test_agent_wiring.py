"""Integration tests: agent topology, model routing, plugins and memory wiring."""

from __future__ import annotations

import pytest
from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.memory import InMemoryMemoryService
from google.adk.sessions import DatabaseSessionService

from gf_agent import agent as A
from gf_agent import services
from gf_agent.config import MODEL_ROUTING, choose_model_for_request
from gf_agent.memory import AsyncMemoryPlugin
from gf_agent.plugins.audit import AuditPlugin
from gf_agent.plugins.guardrails import GuardrailPlugin
from gf_agent.plugins.routing import ModelRoutingPlugin
from gf_agent.schemas import FinalReport


def test_app_exposes_root_and_plugins():
  assert A.app.root_agent is A.root_agent
  kinds = [type(p) for p in A.app.plugins]
  assert {GuardrailPlugin, AuditPlugin, AsyncMemoryPlugin, ModelRoutingPlugin} <= set(kinds)
  assert kinds[0] is AuditPlugin, "audit must run first so blocked calls are still logged"


@pytest.mark.parametrize("text,expected_tier,reason", [
    ("Find GF bread in Australia", "fast", "static_role_tier"),
    ("Compare GF pasta prices in Canada and Singapore", "pro", "escalated_multi_country(2)"),
    ("x" * 700, "pro", "escalated_long_request"),
])
def test_per_request_model_routing(text, expected_tier, reason):
  model, why = choose_model_for_request("gf_coordinator", MODEL_ROUTING.fast, text)
  assert model == getattr(MODEL_ROUTING, expected_tier) and why == reason


def test_specialists_keep_static_tier():
  model, why = choose_model_for_request(
      "cost_analysis_agent", MODEL_ROUTING.lite, "Canada and Singapore")
  assert model == MODEL_ROUTING.lite and why == "static_role_tier"


def test_pipeline_is_sequential_with_expected_order():
  p = A.gf_sourcing_pipeline
  assert isinstance(p, SequentialAgent)
  assert [a.name for a in p.sub_agents] == [
      "sourcing_agent", "gluten_verification_agent", "health_assessment_agent",
      "cost_analysis_agent", "report_refinement_loop", "report_publisher"]


def test_report_loop_is_writer_critic():
  loop = A.report_refinement_loop
  assert isinstance(loop, LoopAgent) and loop.max_iterations == 3
  assert [a.name for a in loop.sub_agents] == ["report_writer_agent", "report_critic_agent"]
  assert A.report_writer_agent.output_schema is FinalReport


def test_coordinator_uses_pipeline_as_tool():
  names = {getattr(t, "name", None) for t in A.root_agent.tools}
  assert {"gf_sourcing_pipeline", "submit_group_purchase_request", "preload_memory"} <= names


@pytest.mark.parametrize("agent,tier", [
    (A.root_agent, "fast"), (A.sourcing_agent, "fast"),
    (A.gluten_verification_agent, "pro"), (A.health_assessment_agent, "fast"),
    (A.cost_analysis_agent, "lite"), (A.report_writer_agent, "pro"),
    (A.report_critic_agent, "fast"),
])
def test_strategic_model_routing(agent, tier):
  assert agent.model.model == getattr(MODEL_ROUTING, tier)


def test_safety_critical_agent_uses_strongest_model_and_zero_temperature():
  a = A.gluten_verification_agent
  assert a.model.model == MODEL_ROUTING.pro
  assert a.generate_content_config.temperature == 0.0


def test_every_specialist_writes_to_state():
  keys = {a.output_key for a in [A.sourcing_agent, A.gluten_verification_agent,
                                 A.health_assessment_agent, A.cost_analysis_agent,
                                 A.report_writer_agent]}
  assert keys == {"sourcing_findings", "gluten_verdicts", "health_assessments",
                  "cost_ranking", "final_report"}


def test_compaction_and_context_cache_configured():
  c = A.app.events_compaction_config
  assert c.compaction_interval and c.overlap_size is not None
  assert c.token_threshold and c.event_retention_size
  assert A.app.context_cache_config is not None


def test_instructions_include_constitution():
  for a in [A.root_agent, A.sourcing_agent, A.gluten_verification_agent,
            A.health_assessment_agent, A.cost_analysis_agent, A.report_writer_agent]:
    assert isinstance(a, LlmAgent)
    assert "CONSTITUTION" in a.instruction and "Non-negotiable constraints" in a.instruction


def test_offline_services_are_persistent_fallbacks():
  assert isinstance(services.build_session_service(), DatabaseSessionService)
  assert isinstance(services.build_memory_service(), InMemoryMemoryService)


def _memory_ctx(memory, *, agent_name="gf_coordinator", nested=False):
  from google.adk.events import Event
  from google.genai import types

  events = [
      Event(author="user", invocation_id="inv", content=types.Content(
          role="user", parts=[types.Part(text="email me at jane@example.com")])),
      Event(author="gf_coordinator", invocation_id="inv", content=types.Content(
          role="model", parts=[types.Part(function_call=types.FunctionCall(
              name="record_shopping_requirements",
              args={"requirements": {"dietary_notes": "call +61 412 345 678"}}))])),
      Event(author="user", invocation_id="older", content=types.Content(
          role="user", parts=[types.Part(text="previous turn")])),
  ]

  class Session:
    app_name, user_id, id = "gf_agent", "u", "s1"

  Session.events = events

  class Agent:
    name = agent_name

  class Ctx:
    memory_service = memory
    session = Session()
    invocation_id = "inv"
    agent = Agent()
    _parent_invocation_id = "parent" if nested else None

  return Ctx()


class _RecordingMemory:
  def __init__(self):
    import asyncio
    self.calls = []
    self._sleep = asyncio.sleep

  async def add_events_to_memory(self, *, app_name, user_id, events, session_id=None):
    await self._sleep(0.05)
    self.calls.append(events)


@pytest.mark.asyncio
async def test_async_memory_runs_in_background_with_only_new_redacted_events():
  memory = _RecordingMemory()
  plugin = AsyncMemoryPlugin()
  await plugin.after_run_callback(invocation_context=_memory_ctx(memory))
  assert memory.calls == [], "memory generation must not block the response"
  await plugin.drain()
  assert len(memory.calls) == 1
  ingested = memory.calls[0]
  assert len(ingested) == 2, "only this turn's events are ingested (incremental)"
  dumped = str([e.model_dump() for e in ingested])
  assert "jane@example.com" not in dumped and "412 345 678" not in dumped


@pytest.mark.asyncio
async def test_async_memory_skips_nested_pipeline_runs():
  memory = _RecordingMemory()
  plugin = AsyncMemoryPlugin()
  await plugin.after_run_callback(invocation_context=_memory_ctx(memory, nested=True))
  await plugin.after_run_callback(
      invocation_context=_memory_ctx(memory, agent_name="gf_sourcing_pipeline"))
  await plugin.drain()
  assert memory.calls == []


@pytest.mark.asyncio
async def test_report_publisher_returns_final_report_from_state():
  from google.adk.runners import Runner
  from google.adk.sessions import InMemorySessionService
  from google.genai import types

  from gf_agent.report_publisher import ReportPublisherAgent

  sessions = InMemorySessionService()
  runner = Runner(app_name="pub", agent=ReportPublisherAgent(name="report_publisher"),
                  session_service=sessions)
  s = await sessions.create_session(app_name="pub", user_id="u",
                                    state={"final_report": {"country_code": "AU"}})
  texts = []
  async for ev in runner.run_async(user_id="u", session_id=s.id, new_message=types.Content(
      role="user", parts=[types.Part(text="go")])):
    texts += [p.text for p in (ev.content.parts if ev.content else []) if p.text]
  assert '"country_code": "AU"' in " ".join(texts)


def test_agents_cli_manifest_points_at_this_agent():
  from pathlib import Path

  import yaml

  m = yaml.safe_load((Path(__file__).resolve().parents[2] / "agents-cli-manifest.yaml").read_text())
  assert m["agent_directory"] == "gf_agent"
  assert m["create_params"]["deployment_target"] == "agent_runtime"
  assert m["create_params"]["root_agent_name"] == A.root_agent.name


def test_model_calls_use_vertex_ai_global_location():
  for a in [A.root_agent, A.gluten_verification_agent, A.cost_analysis_agent,
            A.report_writer_agent]:
    assert a.model.client_kwargs["enterprise"] is True, "Vertex AI only, never API keys"
    assert a.model.client_kwargs["location"] == "global"
