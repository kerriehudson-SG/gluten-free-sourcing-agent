"""Agent topology and ADK App definition.

Rubric: Orchestration & Logic -> Multi-Agent Patterns.

Pattern: Coordinator + Sequential pipeline + Loop (generator/critic).

    gf_coordinator (LlmAgent, fast model)            <- talks to the user
      tools: record_shopping_requirements,
             check_ingredients_for_gluten_sources (quick single-product check),
             gf_sourcing_pipeline (AgentTool -> SequentialAgent),
             calculate_group_purchase_options,
             submit_group_purchase_request (HITL: require_confirmation=True),
             PreloadMemoryTool (long-term memory recall)

    gf_sourcing_pipeline (SequentialAgent)
      1. sourcing_agent              (fast)  -> state['sourcing_findings']
      2. gluten_verification_agent   (pro)   -> state['gluten_verdicts']
      3. health_assessment_agent     (fast)  -> state['health_assessments']
      4. cost_analysis_agent         (lite)  -> state['cost_ranking']
      5. report_refinement_loop (LoopAgent, max 3)
           a. report_writer_agent    (pro, output_schema=FinalReport)
           b. report_critic_agent    (fast, exit_loop when checks pass)
      6. report_publisher (deterministic BaseAgent) -> returns final_report

The coordinator stays in control of the conversation; specialists are
independent (each re-derives its judgement with its own tools).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.google_llm import Gemini
from google.adk.tools import exit_loop
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.google_search_tool import google_search
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from gf_agent import prompts
from gf_agent.config import MODEL_ROUTING, get_settings
from gf_agent.memory import AsyncMemoryPlugin
from gf_agent.observability.logging import configure_logging
from gf_agent.observability.tracing import init_tracing
from gf_agent.plugins.audit import AuditPlugin
from gf_agent.plugins.guardrails import GuardrailPlugin
from gf_agent.plugins.routing import ModelRoutingPlugin
from gf_agent.report_publisher import ReportPublisherAgent
from gf_agent.schemas import FinalReport
from gf_agent.tools.actions import submit_group_purchase_request_tool
from gf_agent.tools.cost import (
    calculate_group_purchase_options,
    rank_products_by_cost_effectiveness,
)
from gf_agent.tools.health import assess_nutrition_against_national_standard
from gf_agent.tools.sourcing import (
    find_gluten_free_retailers_by_country,
    list_gluten_free_products_by_category,
    record_shopping_requirements,
)
from gf_agent.tools.verification import (
    check_ingredients_for_gluten_sources,
    lookup_product_label_by_barcode,
)

configure_logging()
init_tracing()

_DETERMINISTIC = types.GenerateContentConfig(temperature=0.0)
_FACTUAL = types.GenerateContentConfig(temperature=0.2)


def _sourcing_tools() -> list:
  tools: list = [
      find_gluten_free_retailers_by_country,
      list_gluten_free_products_by_category,
  ]
  if get_settings().enable_live_search:
    # Built-in google_search must live in its own agent; expose it as a tool.
    live_search_agent = LlmAgent(
        name="live_retailer_search_agent",
        model=MODEL_ROUTING.for_role("live_search"),
        description="Finds real gluten-free grocery retailers in a country via Google Search.",
        instruction=prompts.LIVE_SEARCH_INSTRUCTION,
        tools=[google_search],
    )
    tools.append(AgentTool(agent=live_search_agent))
  return tools


sourcing_agent = LlmAgent(
    name="sourcing_agent",
    model=MODEL_ROUTING.for_role("sourcing"),
    description="Finds retailers and candidate gluten-free products for a country.",
    instruction=prompts.SOURCING_INSTRUCTION,
    tools=_sourcing_tools(),
    output_key="sourcing_findings",
    generate_content_config=_FACTUAL,
)

gluten_verification_agent = LlmAgent(
    name="gluten_verification_agent",
    model=MODEL_ROUTING.for_role("gluten_verification"),
    description="Independently verifies each product is gluten-free under the country's law.",
    instruction=prompts.GLUTEN_VERIFICATION_INSTRUCTION,
    tools=[check_ingredients_for_gluten_sources, lookup_product_label_by_barcode],
    output_key="gluten_verdicts",
    generate_content_config=_DETERMINISTIC,
)

health_assessment_agent = LlmAgent(
    name="health_assessment_agent",
    model=MODEL_ROUTING.for_role("health_assessment"),
    description="Scores healthiness against cited national nutrition standards.",
    instruction=prompts.HEALTH_ASSESSMENT_INSTRUCTION,
    tools=[assess_nutrition_against_national_standard],
    output_key="health_assessments",
    generate_content_config=_DETERMINISTIC,
)

cost_analysis_agent = LlmAgent(
    name="cost_analysis_agent",
    model=MODEL_ROUTING.for_role("cost_analysis"),
    description="Ranks verified products by cost effectiveness and group-buy options.",
    instruction=prompts.COST_ANALYSIS_INSTRUCTION,
    tools=[rank_products_by_cost_effectiveness, calculate_group_purchase_options],
    output_key="cost_ranking",
    generate_content_config=_DETERMINISTIC,
)

report_writer_agent = LlmAgent(
    name="report_writer_agent",
    model=MODEL_ROUTING.for_role("report_writer"),
    description="Synthesises specialist outputs into a structured, cited report.",
    instruction=prompts.REPORT_WRITER_INSTRUCTION,
    output_schema=FinalReport,
    output_key="final_report",
    generate_content_config=_FACTUAL,
)

report_critic_agent = LlmAgent(
    name="report_critic_agent",
    model=MODEL_ROUTING.for_role("report_critic"),
    description="Self-evaluation guardrail: checks the report for safety and completeness.",
    instruction=prompts.REPORT_CRITIC_INSTRUCTION,
    tools=[exit_loop],
    output_key="report_critique",
    generate_content_config=_DETERMINISTIC,
)

def _reset_critique(callback_context) -> None:
  """Clears the previous run's critique so the writer starts fresh."""
  callback_context.state["report_critique"] = ""


report_refinement_loop = LoopAgent(
    name="report_refinement_loop",
    before_agent_callback=_reset_critique,
    description="Writer/critic loop that refines the report until all checks pass.",
    sub_agents=[report_writer_agent, report_critic_agent],
    max_iterations=3,
)

gf_sourcing_pipeline = SequentialAgent(
    name="gf_sourcing_pipeline",
    description=(
        "Runs sourcing, independent gluten verification, health assessment, "
        "cost analysis and a self-critiqued report for the saved shopping brief. "
        "Input: a one-line summary of the user's request."
    ),
    sub_agents=[
        sourcing_agent,
        gluten_verification_agent,
        health_assessment_agent,
        cost_analysis_agent,
        report_refinement_loop,
        ReportPublisherAgent(
            name="report_publisher",
            description="Deterministically returns the validated final report.",
        ),
    ],
)

root_agent = LlmAgent(
    name="gf_coordinator",
    model=MODEL_ROUTING.for_role("coordinator"),
    description="Coordinator for gluten-free sourcing, verification, health and cost.",
    instruction=prompts.COORDINATOR_INSTRUCTION,
    tools=[
        PreloadMemoryTool(),
        record_shopping_requirements,
        # Quick single-product checks without running the whole pipeline.
        check_ingredients_for_gluten_sources,
        lookup_product_label_by_barcode,
        AgentTool(agent=gf_sourcing_pipeline),
        calculate_group_purchase_options,
        submit_group_purchase_request_tool,
    ],
    generate_content_config=_FACTUAL,
)

# Rubric: Context & Memory -> History Compaction.
# Sliding-window summarisation every 4 user turns (keeping 1 turn of overlap),
# plus a token-based trigger that keeps the last 10 raw events when the prompt
# exceeds ~60k tokens. Summaries use the cheap 'lite' model. Context caching
# reuses the large static constitution across turns.
app = App(
    name="gf_agent",
    root_agent=root_agent,
    # Order matters: ADK stops at the first plugin that returns a value, so the
    # audit plugin runs first to record intent/outcome even for blocked calls.
    plugins=[
        AuditPlugin(),
        ModelRoutingPlugin(),
        GuardrailPlugin(),
        AsyncMemoryPlugin(root_agent_name="gf_coordinator"),
    ],
    events_compaction_config=EventsCompactionConfig(
        compaction_interval=4,
        overlap_size=1,
        token_threshold=60_000,
        event_retention_size=10,
        summarizer=LlmEventSummarizer(llm=Gemini(model=MODEL_ROUTING.lite)),
    ),
    context_cache_config=ContextCacheConfig(
        min_tokens=4096, ttl_seconds=1800, cache_intervals=10
    ),
)
