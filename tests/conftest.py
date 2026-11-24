"""Shared test fixtures. Tests run fully offline: no GCP project, no secrets."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force offline, deterministic configuration before gf_agent is imported.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "")
os.environ["GF_AGENT_ENGINE_ID"] = ""
os.environ.pop("GOOGLE_CLOUD_AGENT_ENGINE_ID", None)
os.environ["GF_ENABLE_CLOUD_DLP"] = "false"
os.environ["GF_MODEL_ARMOR_TEMPLATE"] = ""
os.environ["GF_ENABLE_CLOUD_TRACE"] = "false"
os.environ["GF_ENABLE_LIVE_SEARCH"] = "false"
