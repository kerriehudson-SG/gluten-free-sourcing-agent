"""Offline test doubles: a scripted LLM that replays canned model turns."""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class ScriptedLlm(BaseLlm):
  """Returns pre-defined responses in order; records every request it sees."""

  responses: list[types.Content] = []
  requests: list[LlmRequest] = []

  async def generate_content_async(
      self, llm_request: LlmRequest, stream: bool = False
  ) -> AsyncGenerator[LlmResponse, None]:
    self.requests.append(llm_request)
    if self.responses:
      content = self.responses.pop(0)
    else:
      content = types.Content(role="model", parts=[types.Part(text="Done.")])
    yield LlmResponse(content=content)


def function_call(name: str, args: dict) -> types.Content:
  return types.Content(role="model", parts=[
      types.Part(function_call=types.FunctionCall(name=name, args=args))])


def text(t: str) -> types.Content:
  return types.Content(role="model", parts=[types.Part(text=t)])
