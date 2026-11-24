"""Security test: no hardcoded credentials anywhere in the repository."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".terraform", "node_modules", ".pytest_cache"}
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Private key block": re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    "Service account key JSON": re.compile(r'"private_key_id"\s*:\s*"[0-9a-f]{20,}"'),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "Generic assignment": re.compile(
        r"(?i)\b(api_key|apikey|secret|password|token)\s*=\s*['\"][A-Za-z0-9/+_\-]{16,}['\"]"),
}


def _files():
  for p in ROOT.rglob("*"):
    if p.is_file() and not (set(p.parts) & SKIP_DIRS) and p.stat().st_size < 1_000_000:
      if p.suffix in {".py", ".json", ".md", ".tf", ".yml", ".yaml", ".toml", ".txt", ".example", ".cfg", ""}:
        yield p


def test_no_hardcoded_secrets():
  findings = []
  for path in _files():
    if path.name == Path(__file__).name:
      continue
    content = path.read_text(encoding="utf-8", errors="ignore")
    for label, pattern in SECRET_PATTERNS.items():
      if pattern.search(content):
        findings.append(f"{path.relative_to(ROOT)}: {label}")
  assert not findings, findings


def test_env_files_are_git_ignored():
  ignore = (ROOT / ".gitignore").read_text()
  for entry in (".env", "*.tfvars", "*.tfstate", "*-key.json"):
    assert entry in ignore, f"{entry} must be in .gitignore"
