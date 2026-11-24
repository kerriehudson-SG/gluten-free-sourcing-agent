# AGENTS.md: rules for AI coding agents working in this repo

This repository is maintained with AI coding assistants (Antigravity, Gemini
CLI, Gemini Code Assist, Jetski). Any agent editing this repo MUST follow:

1. **Spec first.** Read `docs/SPEC.md` and `docs/ARCHITECTURE.md` before changing
   behaviour. Update them in the same change if behaviour changes.
2. **Tests are the contract.** Every behaviour change needs a test. Run
   `pytest -q` and `ruff check .`; both must pass before proposing a change.
3. **Golden dataset is protected.** Only change `tests/golden/gluten_golden.json`
   when a rule change is intended, and say so explicitly in the PR.
4. **Tool design rules.** New tools need a verb_object_qualifier name,
   a Google-style docstring documenting every parameter, Pydantic-typed inputs,
   and the `@guided_errors` decorator. They must never raise to the LLM.
5. **No secrets, ever.** Never write keys, tokens or passwords to files. Use
   `gf_agent.config.get_secret()` (Secret Manager). Never create service
   account keys.
6. **Least privilege.** IAM changes go in `infra/terraform/`. Prefer
   resource-level bindings and justify any new role in a comment.
7. **High-stakes actions** must be wrapped with `FunctionTool(...,
   require_confirmation=True)` and covered by `tests/security/test_hitl.py`.
8. **Privacy.** Do not log raw user text. Use `get_logger()`, which redacts PII.
   Never add fields that collect names, addresses, emails or phone numbers.
9. **Synthetic data only** in `gf_agent/data/`.
10. Keep changes small and reviewable; one concern per PR.
