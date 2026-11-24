# Evaluation and Test Harness

| Layer | What it proves | Command | Runs in CI |
|---|---|---|---|
| Golden dataset (49 cases) | Gluten classification per country never regresses (25 catalogue products + 24 edge cases such as buckwheat, GF oats in AU vs UK, wheat starch, malt vinegar, "may contain") | `pytest tests/unit/test_gluten_verification.py` | ✅ every PR |
| Unit | Health thresholds (UK FSA boundaries, Canada FOP, SG Nutri-Grade, HSR, Nutri-Score), cost maths, bulk tiers, delivery thresholds, guided errors | `pytest tests/unit` | ✅ |
| Interface quality | Every tool has docstrings for all params, descriptive verb-object names and a JSON schema | `pytest tests/unit/test_tool_interface_quality.py` | ✅ |
| Security | Red-team injection set (14 attacks blocked, 8 look-alikes allowed), PII redaction, end-to-end HITL, secret scan | `pytest tests/security` | ✅ |
| Integration | Topology, model routing, plugins, compaction, persistence, non-blocking memory | `pytest tests/integration` | ✅ |
| Agent evaluation (live) | Tool trajectory (IN_ORDER), response match, rubric-based quality (LLM judge), safety on 7 golden conversations | `make eval-live` or `GF_RUN_LIVE_EVALS=1 pytest -m live` | ✅ on `main` (WIF) |
| Post-deploy smoke | Deployed agent answers correctly and refuses injection | `make smoke AGENT_ENGINE_ID=...` | ✅ deploy workflow |
| Static | Ruff (incl. bandit `S` rules), `pip-audit`, gitleaks, `terraform validate` | see CI | ✅ |

## Live eval metrics (`tests/eval/test_config.json`)
- `tool_trajectory_avg_score` ≥ 0.8 (`IN_ORDER`, args ignored, so key tools must be called in order)
- `response_match_score` ≥ 0.3 (ROUGE vs reference)
- `rubric_based_final_response_quality_v1` ≥ 0.7 (per-case rubrics, e.g. "cites FSANZ")
- `safety_v1` ≥ 0.8

Regenerate the eval set after editing cases: `python scripts/build_evalset.py`.
