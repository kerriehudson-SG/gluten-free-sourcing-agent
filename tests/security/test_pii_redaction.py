"""Privacy tests: PII is scrubbed from user messages, logs and memory inputs."""

from __future__ import annotations

import json

import pytest
from google.genai import types

from gf_agent import config
from gf_agent.observability import pii
from gf_agent.observability.logging import get_logger
from gf_agent.plugins.guardrails import GuardrailPlugin

PII_SAMPLES = {
    "EMAIL_ADDRESS": "contact me at jane.citizen@example.com please",
    "PHONE_NUMBER": "call +61 412 345 678 tonight",
    "CREDIT_CARD_NUMBER": "card 4111 1111 1111 1111 exp 12/29",
    "SG_NRIC_FIN": "my NRIC is S1234567D",
    "UK_NATIONAL_INSURANCE": "NI number AB 12 34 56 C",
    "STREET_ADDRESS": "deliver to 42 Wallaby Way Sydney",
}


@pytest.mark.parametrize("info_type,sample", PII_SAMPLES.items())
def test_regex_redaction(info_type, sample):
  out = pii.redact_text(sample)
  assert f"[REDACTED_{info_type}]" in out, out


@pytest.mark.parametrize("safe", [
    "Brown Rice Penne 3000 g for AUD 18.99",
    "barcode 4006381333931",          # valid EAN-13 must survive
    "group of 8 households in Manchester",
    "health star rating 4.5 and 20 mg/kg threshold",
])
def test_non_pii_preserved(safe):
  assert pii.redact_text(safe) == safe


def test_invalid_luhn_number_not_treated_as_card():
  assert "REDACTED_CREDIT_CARD" not in pii.redact_text("order 1234 5678 9012 3456")


def test_redact_obj_nested():
  data = {"a": ["x jane@example.com"], "b": {"c": "S1234567D"}, "n": 5}
  out = pii.redact_obj(data)
  assert "jane@example.com" not in json.dumps(out) and "S1234567D" not in json.dumps(out)
  assert out["n"] == 5


def test_structured_log_output_is_json_and_redacted(capsys):
  log = get_logger("test")
  log.info("user_said", text="email jane@example.com", group_size=4)
  line = [ln for ln in capsys.readouterr().out.splitlines() if "user_said" in ln][-1]
  record = json.loads(line)
  assert record["message"] == "user_said"
  assert record["severity"] == "INFO"
  assert "timestamp" in record and record["group_size"] == 4
  assert "jane@example.com" not in line


@pytest.mark.asyncio
async def test_user_message_redacted_before_session_storage():
  plugin = GuardrailPlugin()

  class Ctx:
    invocation_id = "inv-1"

  msg = types.Content(role="user", parts=[types.Part(text="I'm at jane@example.com, 42 Wallaby Way")])
  out = await plugin.on_user_message_callback(invocation_context=Ctx(), user_message=msg)
  assert out is not None
  assert "jane@example.com" not in out.parts[0].text
  assert "Wallaby Way" not in out.parts[0].text


def test_cloud_dlp_disabled_falls_back_to_regex():
  assert "[REDACTED_EMAIL_ADDRESS]" in pii.redact_with_cloud_dlp("x@y.com")


def test_pseudonymize_masks_without_secret(monkeypatch):
  monkeypatch.setattr(pii, "get_secret", lambda *_: None)
  assert pii.pseudonymize_user_id("user-123") == "u_masked"


def test_pseudonymize_stable_with_secret(monkeypatch):
  monkeypatch.setattr(pii, "get_secret", lambda *_: "test-salt-not-a-real-secret")
  a, b = pii.pseudonymize_user_id("user-123"), pii.pseudonymize_user_id("user-123")
  assert a == b and a.startswith("u_") and "user-123" not in a


def test_get_secret_returns_none_without_project(monkeypatch):
  monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "")
  config.get_secret.cache_clear()
  assert config.get_secret("anything") is None
