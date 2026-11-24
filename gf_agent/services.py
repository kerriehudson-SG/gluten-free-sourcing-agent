"""Persistent session and memory service factory.

Rubric: Context & Memory -> Persistent Session State.

| Environment            | Sessions                              | Long-term memory               |
|------------------------|---------------------------------------|--------------------------------|
| Agent Runtime (prod)   | Agent Engine Sessions (managed)        | Agent Engine Memory Bank       |
| Local dev with GCP     | VertexAiSessionService (agentengine://)| VertexAiMemoryBankService      |
| Local dev offline/CI   | DatabaseSessionService (SQLite file)   | InMemoryMemoryService          |

For `adk web` / `adk api_server` the equivalent CLI flags are:
  --session_service_uri=agentengine://$GF_AGENT_ENGINE_ID
  --memory_service_uri=agentengine://$GF_AGENT_ENGINE_ID
"""

from __future__ import annotations

from google.adk.memory import BaseMemoryService, InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, DatabaseSessionService

from gf_agent.config import get_settings


def build_session_service() -> BaseSessionService:
  """Returns a persistent session service for the current environment."""
  s = get_settings()
  if s.project_id and s.agent_engine_id:
    from google.adk.sessions import VertexAiSessionService  # pylint: disable=import-outside-toplevel

    return VertexAiSessionService(
        project=s.project_id, location=s.location, agent_engine_id=s.agent_engine_id
    )
  # Durable local fallback: survives process restarts (unlike in-memory).
  return DatabaseSessionService(db_url="sqlite+aiosqlite:///./.gf_sessions.db")


def build_memory_service() -> BaseMemoryService:
  """Returns Memory Bank when configured, else an in-memory store."""
  s = get_settings()
  if s.project_id and s.agent_engine_id:
    from google.adk.memory import VertexAiMemoryBankService  # pylint: disable=import-outside-toplevel

    return VertexAiMemoryBankService(
        project=s.project_id, location=s.location, agent_engine_id=s.agent_engine_id
    )
  return InMemoryMemoryService()


def build_runner(app) -> Runner:
  """Builds a Runner for programmatic use (scripts, tests, notebooks)."""
  return Runner(
      app=app,
      session_service=build_session_service(),
      memory_service=build_memory_service(),
  )
