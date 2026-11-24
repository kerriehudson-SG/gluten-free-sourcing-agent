# Security, Privacy and Safety

## Threat model (summary)

| Threat | Control | Evidence |
|---|---|---|
| Unsafe "gluten-free" recommendation (false negative) | Independent deterministic verification per country law; Pro model at temperature 0; uncertain products become `NEEDS_CLARIFICATION`; critic loop checks no EXCLUDED item is recommended | `tools/verification.py`, `tests/unit/test_gluten_verification.py` (49 golden cases) |
| Prompt injection / jailbreak (direct) | `GuardrailPlugin.before_model_callback` (regex policy + optional Model Armor) blocks before the model is called | `tests/security/test_prompt_injection.py` |
| Indirect injection via tool data / web pages | `after_tool_callback` quarantines poisoned tool results; `before_tool_callback` blocks injected tool args; critic treats the draft as untrusted; constitution rule 7 | `test_poisoned_tool_result_is_quarantined`, `test_tool_args_with_injection_are_blocked` |
| CI/CD compromise | Deploy only from `main`; untrusted `workflow_dispatch` input passed via env and regex-validated; tests run in a job without credentials; credentials issued only after environment approval; `concurrency` lock | `.github/workflows/deploy.yml` |
| Unauthorised high-stakes action | `require_confirmation=True` on `submit_group_purchase_request`; draft-only, no payments | `tests/security/test_hitl.py` (end-to-end with real Runner) |
| PII leakage to logs, traces or memory | User message scrubbed **before** session storage; every log record scrubbed; model output scrubbed; Cloud DLP optional; `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`; user IDs HMAC-pseudonymised | `tests/security/test_pii_redaction.py` |
| PII collection | Schemas forbid extra fields; `organiser_region` accepts city/region only | `test_record_requirements_rejects_extra_fields`, `test_region_must_not_be_an_address` |
| Credential leakage | No keys anywhere; Secret Manager; WIF for CI; gitleaks pre-commit and CI; repo secret scan test | `tests/security/test_no_hardcoded_secrets.py`, `.github/workflows/ci.yml` |
| Over-privileged identities | Three service accounts with minimal roles; `serviceAccountUser` scoped to the runtime SA only; secret accessor scoped to one secret; deployer only usable from an approved GitHub Environment | `infra/terraform/iam.tf`, `wif.tf`, `secrets.tf` |
| Supply chain | Pinned version ranges; `pip-audit` in CI; Dependabot for pip, actions, terraform | `.github/dependabot.yml` |
| Tool exceptions crashing the agent or leaking internals | `@guided_errors` returns safe recovery hints; internal details are logged, never returned | `test_unexpected_exception_does_not_crash_and_hides_details` |

## IAM (least privilege)

| Identity | Roles | Scope | Used by |
|---|---|---|---|
| `gf-agent-runtime` | `aiplatform.user`, `logging.logWriter`, `cloudtrace.agent`, `monitoring.metricWriter`, `dlp.user`, `modelarmor.user` | project | Deployed agent |
| | `secretmanager.secretAccessor` | **one secret** | Deployed agent |
| `gf-agent-ci-eval` | custom `gfAgentGeminiInvoker` (`aiplatform.endpoints.predict` only) | project | CI live evals (main branch only, via WIF) |
| `gf-agent-deployer` | `aiplatform.user`, `serviceusage.serviceUsageConsumer` | project | Deploy workflow |
| | `iam.serviceAccountUser` | **runtime SA only** | Attach runtime identity |
| WIF provider | `attribute_condition = repository == '<owner/repo>' && ref == 'refs/heads/main'` | pool | GitHub OIDC; PR jobs never get cloud credentials |
| CI WIF binding | subject `repo:<owner/repo>:ref:refs/heads/main` | SA | Live evals |
| Deployer WIF binding | subject `repo:<owner/repo>:environment:production` | SA | Only after a human approves in GitHub |
| Optional | `iam.serviceAccountTokenCreator` for the Agent Runtime service agent on the runtime SA | runtime SA only | Enabled only if the first deploy requires it |

**Why `aiplatform.user` for runtime and deployer:** Agent Runtime Sessions,
Memory Bank and reasoning-engine management have no narrower predefined role.
A custom role is a possible hardening step once the exact permission set has
been confirmed in your environment from the audit logs. The CI identity, which
only calls Gemini, already uses a single-permission custom role.

No user-managed service account keys exist. Data-access audit logs are on for
Secret Manager.

## Responsible AI
- The constitution requires citations, forbids invented facts, and requires
  a not-medical-advice disclaimer.
- Sample data is synthetic, with no customer or confidential data.
- The model never states a product is GF without a `VERIFIED` tool result.

## Reporting a vulnerability
Open a private security advisory on this repository (GitHub → Security → Advisories).
