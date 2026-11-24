"""Cost-effectiveness and group-purchase tools (deterministic arithmetic).

All money arithmetic is done in code, never by the LLM, so rankings are
reproducible and testable.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

from gf_agent.schemas import (
    BulkTier,
    CostCandidate,
    CostRanking,
    GroupBasketLine,
    GroupPurchaseOption,
    GroupPurchaseOptions,
    RankedOption,
)
from gf_agent.tools._errors import GuidedToolError, guided_errors
from gf_agent.tools.sourcing import get_product, get_retailer


def best_unit_price(list_price: float, tiers: list[BulkTier], packs: int) -> float:
  """Returns the lowest applicable per-pack price for a quantity of packs."""
  eligible = [t.unit_price for t in tiers if packs >= t.min_packs]
  return min([list_price, *eligible])


@guided_errors
def rank_products_by_cost_effectiveness(
    candidates: list[CostCandidate],
    group_size: int,
    currency: str,
    packs_per_person: int = 1,
    budget_per_person: Optional[float] = None,
) -> dict:
  """Ranks VERIFIED gluten-free products by health-adjusted cost effectiveness.

  Only pass products whose gluten_status is VERIFIED. For each product the
  tool applies the best bulk tier available for the whole group's quantity,
  then computes price per 100 g, per-person cost, savings versus buying
  individually, and a cost-effectiveness score = health_score / price per
  100 g (higher is better).

  Args:
    candidates: Products to rank. Each needs product_id, name, retailer_id,
      price (single pack), pack_size_g, health_score (0-100, from
      assess_nutrition_against_national_standard) and bulk_tiers.
    group_size: Number of people/households buying together (1-50).
    currency: ISO currency code shown to the user, e.g. 'AUD'.
    packs_per_person: Packs each person wants (1-20). Defaults to 1.
    budget_per_person: Optional per-person budget to flag affordability.

  Returns:
    A CostRanking dict with ranked_options (rank 1 = most cost effective).
  """
  if not candidates:
    raise GuidedToolError(
        "NO_CANDIDATES",
        "No products were provided to rank.",
        "Pass the VERIFIED products (with health_score) from the previous "
        "steps. If none were verified, tell the user and do not rank.",
    )
  if not 1 <= group_size <= 50:
    raise GuidedToolError(
        "INVALID_GROUP_SIZE",
        f"group_size must be between 1 and 50 (got {group_size}).",
        "Use the group_size saved in shopping_requirements or ask the user.",
    )
  if not 1 <= packs_per_person <= 20:
    raise GuidedToolError(
        "INVALID_PACKS_PER_PERSON",
        f"packs_per_person must be 1-20 (got {packs_per_person}).",
        "Default to 1 unless the user specified a quantity.",
    )
  items = [
      c if isinstance(c, CostCandidate) else CostCandidate.model_validate(c)
      for c in candidates
  ]
  total_packs = group_size * packs_per_person
  rows = []
  for c in items:
    unit = best_unit_price(c.price, c.bulk_tiers, total_packs)
    per_100g = unit / c.pack_size_g * 100
    per_person = unit * packs_per_person
    rows.append(dict(
        product_id=c.product_id, name=c.name, retailer_id=c.retailer_id,
        price_per_100g=round(per_100g, 3),
        group_unit_price=round(unit, 2),
        packs_for_group=total_packs,
        per_person_cost=round(per_person, 2),
        savings_vs_individual_pct=round((c.price - unit) / c.price * 100, 1),
        cost_effectiveness_score=round(c.health_score / per_100g, 2),
        within_budget=(None if budget_per_person is None
                       else per_person <= budget_per_person),
    ))
  rows.sort(key=lambda r: (-r["cost_effectiveness_score"], r["price_per_100g"]))
  ranked = [RankedOption(rank=i + 1, **r) for i, r in enumerate(rows)]
  return CostRanking(
      group_size=group_size,
      packs_per_person=packs_per_person,
      currency=currency,
      ranked_options=ranked,
      method_note=(
          "cost_effectiveness_score = health_score / price per 100 g after "
          "best bulk tier for the whole group. Higher is better."
      ),
  ).model_dump()


@guided_errors
def calculate_group_purchase_options(
    basket: list[GroupBasketLine], group_size: int
) -> dict:
  """Compares group-purchase totals per retailer, including delivery.

  Groups the basket lines by retailer, applies bulk tiers to each line,
  adds the retailer's delivery fee unless the free-delivery threshold is
  met, and splits the grand total across the group.

  Args:
    basket: Lines of {'product_id': str, 'packs': int} for the whole group.
    group_size: Number of people/households sharing the cost (1-50).

  Returns:
    A GroupPurchaseOptions dict with one option per retailer, sorted by
    per_person_total ascending (cheapest first).
  """
  if not 1 <= group_size <= 50:
    raise GuidedToolError(
        "INVALID_GROUP_SIZE",
        f"group_size must be between 1 and 50 (got {group_size}).",
        "Use the group_size saved in shopping_requirements or ask the user.",
    )
  lines = [
      b if isinstance(b, GroupBasketLine) else GroupBasketLine.model_validate(b)
      for b in basket
  ]
  if not lines:
    raise GuidedToolError(
        "EMPTY_BASKET", "The basket is empty.",
        "Add at least one VERIFIED product_id with a pack quantity.")
  by_retailer: dict[str, float] = defaultdict(float)
  currency = ""
  for line in lines:
    product = get_product(line.product_id)
    if product is None:
      raise GuidedToolError(
          "UNKNOWN_PRODUCT",
          f"product_id '{line.product_id}' was not found.",
          "Use product_id values exactly as returned by "
          "list_gluten_free_products_by_category.",
      )
    currency = product.currency
    unit = best_unit_price(product.price, product.bulk_tiers, line.packs)
    by_retailer[product.retailer_id] += unit * line.packs

  options = []
  for retailer_id, basket_total in by_retailer.items():
    retailer = get_retailer(retailer_id)
    threshold = retailer.free_delivery_threshold if retailer else None
    meets = threshold is not None and basket_total >= threshold
    fee = 0.0 if meets else (retailer.delivery_fee if retailer else 0.0)
    grand = basket_total + fee
    options.append(GroupPurchaseOption(
        retailer_id=retailer_id,
        retailer_name=retailer.name if retailer else retailer_id,
        basket_total=round(basket_total, 2),
        delivery_fee=round(fee, 2),
        grand_total=round(grand, 2),
        per_person_total=round(grand / group_size, 2),
        meets_free_delivery=meets,
    ))
  options.sort(key=lambda o: o.per_person_total)
  return GroupPurchaseOptions(
      group_size=group_size,
      currency=currency,
      options=options,
      method_note="Bulk tiers applied per line; delivery waived at threshold.",
  ).model_dump()
