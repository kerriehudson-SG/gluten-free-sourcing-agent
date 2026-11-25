"""Security test: high-stakes purchase tool can NEVER run without human approval.

Runs the real ADK Runner + real plugins offline with a scripted model that
tries to call submit_group_purchase_request directly.
"""

from __future__ import annotations

import pytest
from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from gf_agent.plugins.audit import AuditPlugin
from gf_agent.plugins.guardrails import GuardrailPlugin
from gf_agent.tools.actions import submit_group_purchase_request_tool
from tests.helpers import ScriptedLlm, function_call, text

PURCHASE_ARGS = {
    "retailer_id": "au-costco",
    "lines": [{"product_id": "au-p3", "packs": 6}],
    "group_size": 6,
    "organiser_region": "Melbourne",
}


def _build(responses):
  llm = ScriptedLlm(model="scripted", responses=list(responses), requests=[])
  agent = LlmAgent(name="hitl_test_agent", model=llm,
                   instruction="test", tools=[submit_group_purchase_request_tool])
  app = App(name="hitl_test", root_agent=agent,
            plugins=[GuardrailPlugin(), AuditPlugin()])
  sessions = InMemorySessionService()
  return Runner(app=app, session_service=sessions), sessions


async def _run(runner, session_id, message):
  events = []
  async for ev in runner.run_async(user_id="u1", session_id=session_id, new_message=message):
    events.append(ev)
  return events


def _confirmation_requests(events):
  calls = []
  for ev in events:
    for fc in ev.get_function_calls():
      if fc.name == "adk_request_confirmation":
        calls.append(fc)
  return calls


def test_purchase_tool_is_configured_for_confirmation():
  assert submit_group_purchase_request_tool._require_confirmation is True


@pytest.mark.asyncio
async def test_purchase_pauses_for_human_confirmation():
  runner, sessions = _build([function_call("submit_group_purchase_request", PURCHASE_ARGS)])
  s = await sessions.create_session(app_name="hitl_test", user_id="u1")
  events = await _run(runner, s.id, types.Content(role="user", parts=[types.Part(text="Order it")]))
  assert _confirmation_requests(events), "ADK must emit adk_request_confirmation"
  s = await sessions.get_session(app_name="hitl_test", user_id="u1", session_id=s.id)
  assert "group_purchase_drafts" not in s.state, "draft must not exist before approval"


async def _respond(runner, sessions, s, confirm: bool):
  events = await _run(runner, s.id, types.Content(role="user", parts=[types.Part(text="Order it")]))
  req = _confirmation_requests(events)[0]
  reply = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
      id=req.id, name="adk_request_confirmation", response={"confirmed": confirm}))])
  await _run(runner, s.id, reply)
  return await sessions.get_session(app_name="hitl_test", user_id="u1", session_id=s.id)


@pytest.mark.asyncio
async def test_rejected_confirmation_does_not_create_draft():
  runner, sessions = _build([
      function_call("submit_group_purchase_request", PURCHASE_ARGS), text("Cancelled.")])
  s = await sessions.create_session(app_name="hitl_test", user_id="u1")
  s = await _respond(runner, sessions, s, confirm=False)
  assert "group_purchase_drafts" not in s.state


@pytest.mark.asyncio
async def test_approved_confirmation_creates_draft_only():
  runner, sessions = _build([
      function_call("submit_group_purchase_request", PURCHASE_ARGS), text("Draft created.")])
  s = await sessions.create_session(app_name="hitl_test", user_id="u1")
  s = await _respond(runner, sessions, s, confirm=True)
  drafts = s.state.get("group_purchase_drafts")
  assert drafts and drafts[0]["state"] == "DRAFT_AWAITING_ORGANISER"
  assert "No payment was taken" in drafts[0]["message"]


def test_region_must_not_be_an_address():
  from gf_agent.tools.actions import submit_group_purchase_request
  r = submit_group_purchase_request(
      retailer_id="au-costco", lines=[{"product_id": "au-p3", "packs": 1}],
      group_size=2, organiser_region="12 Smith Street 3000")
  assert r["error_code"] == "INVALID_REGION"


def test_approved_purchase_returns_confirmation_directly():
  from gf_agent.tools.actions import submit_group_purchase_request

  class Actions:
    skip_summarization = False

  class Ctx:
    def __init__(self):
      self.state = {}
      self.actions = Actions()

  ctx = Ctx()
  r = submit_group_purchase_request(
      retailer_id="au-costco", lines=[{"product_id": "au-p3", "packs": 6}],
      group_size=6, organiser_region="Melbourne", tool_context=ctx)
  assert r["state"] == "DRAFT_AWAITING_ORGANISER"
  assert ctx.actions.skip_summarization is True
  assert ctx.state["group_purchase_drafts"][0]["draft_id"] == r["draft_id"]
