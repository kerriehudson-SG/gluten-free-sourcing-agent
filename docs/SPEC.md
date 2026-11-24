# Product Specification: Gluten-Free Sourcing Agent

## 1. Problem

People with coeliac disease or medically required gluten-free (GF) diets, and the
households and community groups who buy for them, face three compounding problems:

1. **Finding where to buy** genuinely GF products in their country is fragmented
   across supermarkets, bulk stores and specialist online retailers.
2. **"Gluten-free" is not uniform**. A product sold as GF may contain oats,
   barley malt or Codex wheat starch that is legal in one country and not
   another (for example, Australia/NZ require *no detectable gluten* and ban
   oats in GF claims, while the EU/UK/Canada allow ≤20 mg/kg). Manual
   ingredient checks are slow and error-prone.
3. **GF is not automatically healthy or affordable**. GF products are often
   higher in sugar, saturated fat and salt, and cost substantially more.
   Groups can save through bulk and multi-buy purchasing, but comparing
   options is tedious.

## 2. Solution

A multi-agent system built with Google's **Agent Development Kit (ADK)** and
deployed to **Gemini Enterprise Agent Platform Agent Runtime** (Vertex AI Agent
Engine). It:

| Step | Specialist agent | Output |
|---|---|---|
| 1 | **Sourcing Agent** | Retailers and candidate GF products for the specified country |
| 2 | **Gluten Verification Agent** (independent) | Each product is `VERIFIED`, `EXCLUDED` or `NEEDS_CLARIFICATION`, with reasons and questions, against the destination country's GF law |
| 3 | **Health Assessment Agent** (independent) | Nutrition scored against cited national standards (UK FSA, Australia HSR, Health Canada FOP, Singapore HPB Nutri-Grade, EU Nutri-Score) |
| 4 | **Cost Analysis Agent** (independent) | Unit pricing, group-purchase options and a cost-effectiveness ranking |
| 5 | **Report Writer + Critic loop** | Self-evaluated final report that cites every standard used |
| 6 | **Coordinator** | Talks to the user, asks clarifying questions, and asks for **human approval** before any group purchase request is submitted |

### Out of scope
- Real payments or real orders. `submit_group_purchase_request` creates a
  *draft* request record only, and only after explicit human confirmation.
- Medical advice. The agent always recommends checking the physical label and
  consulting a healthcare professional or national coeliac society.

### Data
- `gf_agent/data/*.json` contains **illustrative sample data**. Retailer names
  are real public chains; products, brands, prices and nutrition values are
  **synthetic**. No customer or confidential data is used.
- Optional live enrichment: public Open Food Facts API (no key) and Google
  Search grounding.

## 3. Users and key journeys

| Persona | Journey |
|---|---|
| Coeliac individual | "I live in Australia. Where can I buy healthy, truly GF breakfast foods cheaply?" |
| Community group organiser | "We are 8 households in Manchester. Find the most cost-effective GF bulk options and prepare a group order." |
| Carer | "Is this cereal with 'oats, sugar, barley malt extract' safe in Canada?" |

## 4. Success criteria

| Type | Criterion | Target | Measured by |
|---|---|---|---|
| Rubric | All 19 AgentOps criteria have discoverable code evidence | 95/95 | `docs/RUBRIC_EVIDENCE.md`, internal assessor panel, official evaluator |
| Functional | Gluten classification correctness on golden products | 100% | `tests/unit/test_gluten_verification.py` |
| Functional | Agent trajectory and response quality on golden conversations | ≥ 0.8 tool-trajectory, ≥ 0.6 response match | `adk eval` (`tests/eval/`) |
| Safety | Prompt-injection red-team cases blocked | 100% | `tests/security/test_prompt_injection.py` |
| Privacy | PII never written to logs or memory unredacted | 0 leaks | `tests/security/test_pii_redaction.py` |
| HITL | Purchase request never executes without confirmation | 100% | `tests/security/test_hitl.py` |
| Secrets | No secrets in repository | 0 findings | gitleaks in CI, `tests/security/test_no_hardcoded_secrets.py` |
| Deploy | Reproducible provisioning and deploy | Terraform plan clean; Agent Runtime deploy succeeds | GitHub Actions `deploy.yml` with manual approval |
