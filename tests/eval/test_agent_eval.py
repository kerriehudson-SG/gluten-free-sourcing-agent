"""Automated agent evaluation against the golden eval set (live Gemini calls).

Run locally or in CI (after Workload Identity Federation auth):
    GF_RUN_LIVE_EVALS=1 pytest tests/eval -m live
or with the ADK CLI:
    adk eval gf_agent tests/eval/gf_agent.evalset.json --config_file_path tests/eval/test_config.json

Thresholds live in tests/eval/test_config.json. A drop below threshold fails
the build, catching prompt/model/tool regressions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent


def test_evalset_is_valid_and_has_coverage():
  """Offline: the golden set parses with ADK's schema and covers key behaviours."""
  from google.adk.evaluation.eval_set import EvalSet

  data = json.loads((EVAL_DIR / "gf_agent.evalset.json").read_text())
  eval_set = EvalSet.model_validate(data)
  ids = {c.eval_id for c in eval_set.eval_cases}
  assert {"full_pipeline_au_group", "refuses_prompt_injection",
          "asks_for_missing_country", "quick_check_barley_uk"} <= ids
  assert all(c.rubrics for c in eval_set.eval_cases)


@pytest.mark.live
@pytest.mark.skipif(os.getenv("GF_RUN_LIVE_EVALS") != "1",
                    reason="Live evals need GCP credentials; set GF_RUN_LIVE_EVALS=1")
@pytest.mark.asyncio
async def test_agent_meets_eval_thresholds():
  from google.adk.evaluation.agent_evaluator import AgentEvaluator

  await AgentEvaluator.evaluate(
      agent_module="gf_agent",
      eval_dataset_file_path_or_dir=str(EVAL_DIR / "gf_agent.evalset.json"),
      num_runs=1,
  )
