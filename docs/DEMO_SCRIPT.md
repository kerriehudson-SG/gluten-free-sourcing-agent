# Demo video script (≤ 5 minutes, English)

| Time | Show | Say |
|---|---|---|
| 0:00–0:30 | README hero | "For people with coeliac disease, 'gluten-free' means different things in different countries, and GF food is often less healthy and more expensive. This agent team finds where to buy, independently verifies ingredients against each country's law, scores healthiness against cited national standards, and ranks group-buy value, with a human approving any purchase." |
| 0:30–1:15 | Architecture diagram | Coordinator + Sequential pipeline + writer/critic Loop. Model routing: Pro for safety-critical gluten checks, Flash for dialogue, Flash-Lite for arithmetic. |
| 1:15–2:30 | `adk web` live demo | (1) UK barley malt cereal → EXCLUDED with FSA citation. (2) Same oats product: VERIFIED in UK, EXCLUDED in Australia. (3) Melbourne group request → full report with cost ranking. |
| 2:30–3:00 | HITL | Ask for the group order → approval dialog → reject, then approve → draft only, no payment. |
| 3:00–3:30 | Guardrail | Prompt injection → refused before the model is called. |
| 3:30–4:15 | Observability | Cloud Trace waterfall; Logs Explorer `tool_intent`/`tool_outcome`; PII shown as `[REDACTED_...]`. |
| 4:15–5:00 | Engineering | Rubric table in README; `pytest` (180+ tests, golden dataset, red team); GitHub Actions CI; Terraform least-privilege IAM + WIF; deploy approval gate. |
