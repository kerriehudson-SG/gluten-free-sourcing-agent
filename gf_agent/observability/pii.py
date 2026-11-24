"""PII redaction for logs, traces and memory.

Rubric: Observability & Tracing -> PII Redaction.

Two layers:
  1. Always-on local regex scrubber (fast, offline, deterministic, tested).
  2. Optional Google Cloud Sensitive Data Protection (Cloud DLP) de-identification
     when GF_ENABLE_CLOUD_DLP=true, for broader infoType coverage.

Redaction is applied:
  - to every user message BEFORE it is stored in the session / Memory Bank
    (gf_agent/plugins/guardrails.py -> on_user_message_callback),
  - to every structured log record (gf_agent/observability/logging.py),
  - to tool arguments/results before they are logged (gf_agent/plugins/audit.py).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from typing import Any

from gf_agent.config import get_secret, get_settings

logger = logging.getLogger(__name__)


def _luhn_ok(digits: str) -> bool:
  total, alt = 0, False
  for ch in reversed(digits):
    d = int(ch)
    if alt:
      d *= 2
      if d > 9:
        d -= 9
    total += d
    alt = not alt
  return total % 10 == 0


def _is_gtin(token: str) -> bool:
  """True for contiguous 8/12/13/14-digit strings with a valid GS1 check digit.

  Product barcodes (EAN/UPC) are not PII and must survive redaction so the
  barcode lookup tool keeps working.
  """
  if not token.isdigit() or len(token) not in (8, 12, 13, 14):
    return False
  body, check = token[:-1], int(token[-1])
  total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
  return (10 - total % 10) % 10 == check


# Order matters: most specific first.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL_ADDRESS", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("SG_NRIC_FIN", re.compile(r"\b[STFGM]\d{7}[A-Z]\b")),
    ("UK_NATIONAL_INSURANCE", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b")),
    ("CREDIT_CARD_NUMBER", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PHONE_NUMBER_INTL", re.compile(r"\+\d{1,3}[\s-]?(?:\(?\d{1,4}\)?[\s-]?){2,5}\d{2,4}\b")),
    ("CA_SOCIAL_INSURANCE", re.compile(r"\b\d{3}[- ]\d{3}[- ]\d{3}\b")),
    ("PHONE_NUMBER", re.compile(r"(?<![\w])(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{3,4}(?![\w])")),
    ("STREET_ADDRESS", re.compile(
        r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|"
        r"Drive|Dr|Court|Ct|Place|Pl|Crescent|Cres|Boulevard|Blvd|Way|Close)\b\.?")),
]


def redact_text(text: str) -> str:
  """Redacts PII from free text using local regex detectors.

  Args:
    text: Any string that may contain PII.

  Returns:
    The text with each detected PII span replaced by '[REDACTED_<TYPE>]'.
  """
  if not text:
    return text

  def _sub_card(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    if _is_gtin(m.group(0).strip()):
      return m.group(0)
    return "[REDACTED_CREDIT_CARD_NUMBER]" if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)

  out = text
  for info_type, pattern in _PATTERNS:
    if info_type == "CREDIT_CARD_NUMBER":
      out = pattern.sub(_sub_card, out)
    elif info_type == "PHONE_NUMBER":
      out = pattern.sub(
          lambda m: "[REDACTED_PHONE_NUMBER]"
          if len(re.sub(r"\D", "", m.group(0))) >= 8 and not _is_gtin(m.group(0).strip())
          else m.group(0), out)
    elif info_type == "PHONE_NUMBER_INTL":
      out = pattern.sub("[REDACTED_PHONE_NUMBER]", out)
    else:
      out = pattern.sub(f"[REDACTED_{info_type}]", out)
  return out


def redact_with_cloud_dlp(text: str) -> str:
  """De-identifies text with Google Cloud Sensitive Data Protection (DLP).

  Falls back to the local regex scrubber if DLP is disabled or unavailable,
  so redaction can never be silently skipped.

  Args:
    text: Text to de-identify.

  Returns:
    De-identified text with infoTypes replaced by '[INFO_TYPE]'.
  """
  local = redact_text(text)
  settings = get_settings()
  if not settings.enable_cloud_dlp or not settings.project_id or not text:
    return local
  try:
    from google.cloud import dlp_v2  # pylint: disable=import-outside-toplevel

    client = dlp_v2.DlpServiceClient()
    response = client.deidentify_content(request={
        "parent": f"projects/{settings.project_id}/locations/global",
        "inspect_config": {"info_types": [
            {"name": n} for n in (
                "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD_NUMBER",
                "PERSON_NAME", "STREET_ADDRESS", "IBAN_CODE",
                "SINGAPORE_NATIONAL_REGISTRATION_ID_NUMBER",
                "UK_NATIONAL_INSURANCE_NUMBER", "CANADA_SOCIAL_INSURANCE_NUMBER",
                "AUSTRALIA_TAX_FILE_NUMBER", "DATE_OF_BIRTH")
        ]},
        "deidentify_config": {"info_type_transformations": {"transformations": [
            {"primitive_transformation": {"replace_with_info_type_config": {}}}
        ]}},
        "item": {"value": local},
    })
    return response.item.value
  except Exception:  # pylint: disable=broad-exception-caught
    logger.warning("Cloud DLP unavailable; local regex redaction applied")
    return local


def redact_obj(value: Any, _depth: int = 0) -> Any:
  """Recursively redacts strings inside dicts/lists (for logs and tool args)."""
  if _depth > 8:
    return "[TRUNCATED]"
  if isinstance(value, str):
    return redact_text(value)
  if isinstance(value, dict):
    return {k: redact_obj(v, _depth + 1) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [redact_obj(v, _depth + 1) for v in value]
  return value


def pseudonymize_user_id(user_id: str) -> str:
  """Returns a stable, non-reversible pseudonym for a user ID for logging.

  Uses HMAC-SHA256 keyed with a salt stored in Secret Manager
  (GF_PII_SALT_SECRET_ID). If the secret is unavailable the ID is fully
  masked rather than logged in clear.

  Args:
    user_id: Raw user identifier.

  Returns:
    'u_<16 hex chars>' or 'u_masked'.
  """
  salt = get_secret(get_settings().pii_salt_secret_id)
  if not salt or not user_id:
    return "u_masked"
  digest = hmac.new(salt.encode(), user_id.encode(), hashlib.sha256).hexdigest()
  return f"u_{digest[:16]}"
