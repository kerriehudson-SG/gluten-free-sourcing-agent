"""High-stakes action tools. Every tool here is wrapped with mandatory
human-in-the-loop (HITL) confirmation in gf_agent/agent.py.

Rubric: Orchestration & Logic -> Human-in-the-Loop Hooks.
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from gf_agent.schemas import GroupBasketLine, GroupPurchaseDraft
from gf_agent.tools._errors import GuidedToolError, guided_errors
from gf_agent.tools.sourcing import get_product, get_retailer

_REGION_RE = re.compile(r"^[A-Za-z][A-Za-z .,'-]{1,59}$")


@guided_errors
def submit_group_purchase_request(
    retailer_id: str,
    lines: list[GroupBasketLine],
    group_size: int,
    organiser_region: str,
    tool_context: Optional[ToolContext] = None,
) -> dict:
  """Creates a DRAFT group-purchase request for the organiser to place.

  HIGH-STAKES ACTION: this tool is configured with require_confirmation=True,
  so ADK pauses and asks the human to approve or reject before it runs. It
  never takes payment or places a real order; it records a draft that the
  group organiser completes on the retailer's own website.

  Only include products whose gluten_status is VERIFIED.

  Args:
    retailer_id: Retailer to buy from, e.g. 'au-costco'.
    lines: Basket lines [{'product_id': str, 'packs': int}], all from this
      retailer.
    group_size: Number of people/households in the group (1-50).
    organiser_region: City or region only (e.g. 'Melbourne'). Never a street
      address, email or phone number.
    tool_context: Injected by ADK; used to save the draft in session state.

  Returns:
    A GroupPurchaseDraft dict (state DRAFT_AWAITING_ORGANISER), or a
    ToolError with a recovery_hint.
  """
  retailer = get_retailer(retailer_id)
  if retailer is None:
    raise GuidedToolError(
        "UNKNOWN_RETAILER", f"retailer_id '{retailer_id}' was not found.",
        "Use a retailer_id exactly as returned by find_gluten_free_retailers_by_country.")
  if not _REGION_RE.match(organiser_region or ""):
    raise GuidedToolError(
        "INVALID_REGION",
        "organiser_region must be a city or region name only (letters, 2-60 chars).",
        "Ask the user for their city or region only. Do not collect street "
        "addresses, emails or phone numbers.")
  if not 1 <= group_size <= 50:
    raise GuidedToolError(
        "INVALID_GROUP_SIZE", f"group_size must be 1-50 (got {group_size}).",
        "Use the group_size from shopping_requirements.")
  parsed = [ln if isinstance(ln, GroupBasketLine) else GroupBasketLine.model_validate(ln)
            for ln in lines]
  if not parsed:
    raise GuidedToolError("EMPTY_BASKET", "No lines provided.",
                          "Add at least one VERIFIED product with packs >= 1.")
  for line in parsed:
    product = get_product(line.product_id)
    if product is None or product.retailer_id != retailer_id:
      raise GuidedToolError(
          "PRODUCT_RETAILER_MISMATCH",
          f"product_id '{line.product_id}' is not sold by {retailer_id}.",
          "Split the basket so each request contains products from one retailer only.")

  draft = GroupPurchaseDraft(
      draft_id=f"gpr-{uuid.uuid4().hex[:10]}",
      retailer_id=retailer_id,
      lines=parsed,
      group_size=group_size,
      organiser_region=organiser_region,
      message=(
          f"Draft group request created for {retailer.name}. The organiser "
          f"should place the order at {retailer.website}. No payment was taken."
      ),
  )
  if tool_context is not None:
    drafts = list(tool_context.state.get("group_purchase_drafts", []))
    drafts.append(draft.model_dump())
    tool_context.state["group_purchase_drafts"] = drafts
  return draft.model_dump()


# HITL policy: purchase requests ALWAYS require explicit human approval.
submit_group_purchase_request_tool = FunctionTool(
    submit_group_purchase_request, require_confirmation=True
)
