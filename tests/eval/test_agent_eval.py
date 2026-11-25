"""Automated agent evaluation against golden eval sets (live Gemini calls).

Two eval sets:
  * gf_agent.evalset.json  - 6 functional cases: tool trajectory, LLM-judged
    response match, and LLM-judged safety/quality rubrics.
  * guardrail/guardrail.evalset.json - prompt-injection case. The guardrail
    blocks it before any model call, so it is scored on trajectory (no tools)
    and LLM-judged response match (the refusal).

Run: GF_RUN_LIVE_EVALS=1 pytest -m live tests/eval   (or: make eval-live)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parent
EVAL_SETS = [EVAL_DIR / "gf_agent.evalset.json", EVAL_DIR / "guardrail" / "guardrail.evalset.json"]


def test_evalsets_are_valid_and_cover_key_behaviours():
  """Offline: both golden sets parse with ADK's schema and cover key behaviours."""
  from google.adk.evaluation.eval_set import EvalSet

  ids = set()
  for path in EVAL_SETS:
    eval_set = EvalSet.model_validate(json.loads(path.read_text()))
    assert eval_set.eval_cases and all(c.rubrics for c in eval_set.eval_cases)
    ids |= {c.eval_id for c in eval_set.eval_cases}
    assert (path.parent / "test_config.json").exists()
  assert {"full_pipeline_au_group", "refuses_prompt_injection",
          "asks_for_missing_country", "quick_check_barley_uk"} <= ids


@pytest.mark.live
@pytest.mark.skipif(os.getenv("GF_RUN_LIVE_EVALS") != "1",
                    reason="Live evals need GCP credentials; set GF_RUN_LIVE_EVALS=1")
@pytest.mark.asyncio
@pytest.mark.parametrize("eval_set", EVAL_SETS, ids=lambda p: p.stem)
async def test_agent_meets_eval_thresholds(eval_set):
  from google.adk.evaluation.agent_evaluator import AgentEvaluator

  await AgentEvaluator.evaluate(
      agent_module="gf_agent",
      eval_dataset_file_path_or_dir=str(eval_set),
      num_runs=1,
  )
