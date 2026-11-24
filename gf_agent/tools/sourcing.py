"""Sourcing tools: where to buy gluten-free products in a given country."""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Optional

from google.adk.tools.tool_context import ToolContext

from gf_agent.schemas import (
    SUPPORTED_COUNTRIES,
    CountryCode,
    Product,
    ProductCategory,
    ProductSearchResult,
    Retailer,
    RetailerSearchResult,
    ShoppingRequirements,
)
from gf_agent.tools._errors import GuidedToolError, guided_errors

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@functools.lru_cache(maxsize=1)
def _load_retailers() -> tuple[Retailer, ...]:
  raw = json.loads((_DATA_DIR / "retailers.json").read_text(encoding="utf-8"))
  return tuple(Retailer.model_validate(r) for r in raw["retailers"])


@functools.lru_cache(maxsize=1)
def _load_products() -> tuple[Product, ...]:
  raw = json.loads((_DATA_DIR / "products.json").read_text(encoding="utf-8"))
  return tuple(Product.model_validate(p) for p in raw["products"])


def _require_supported(country_code: str) -> str:
  code = (country_code or "").strip().upper()
  if code == "UK":
    code = "GB"
  if code not in SUPPORTED_COUNTRIES:
    raise GuidedToolError(
        "UNSUPPORTED_COUNTRY",
        f"Country '{country_code}' is not supported.",
        f"Ask the user to choose one of: {', '.join(SUPPORTED_COUNTRIES)} "
        "(use ISO 3166-1 alpha-2 codes; the UK is 'GB').",
    )
  return code


@guided_errors
def record_shopping_requirements(
    requirements: ShoppingRequirements, tool_context: Optional[ToolContext] = None
) -> dict:
  """Validates and saves the user's gluten-free shopping brief to session state.

  Call this once you know the country, group size and product categories.
  The saved brief is read by all specialist agents in the pipeline.

  Args:
    requirements: The shopping brief:
      - country_code: ISO code where products will be bought (AU, NZ, GB, IE,
        DE, FR, CA, SG). The UK is 'GB'.
      - group_size: Number of people/households sharing the purchase (1-50).
      - product_categories: One or more of bread_bakery, breakfast_cereal,
        pasta_grains, snacks, flour_baking, beverages, condiments.
      - budget_per_person: Optional budget per person in local currency.
      - dietary_notes: Optional non-identifying notes (no names/addresses).
    tool_context: Injected by ADK; used to write session state.

  Returns:
    {'status': 'success', 'requirements': {...}} or a ToolError with a
    recovery_hint describing which field to ask the user about.
  """
  req = (
      requirements
      if isinstance(requirements, ShoppingRequirements)
      else ShoppingRequirements.model_validate(requirements)
  )
  data = req.model_dump()
  if tool_context is not None:
    tool_context.state["shopping_requirements"] = data
    # New brief -> clear results from any previous pipeline run.
    for stale in ("final_report", "report_critique", "guardrail_last_block"):
      tool_context.state[stale] = ""
    # user: prefix -> persists across sessions for this user (preferences).
    tool_context.state["user:preferred_country"] = req.country_code
  return {"status": "success", "requirements": data}


@guided_errors
def find_gluten_free_retailers_by_country(
    country_code: CountryCode, bulk_or_group_only: bool = False
) -> dict:
  """Lists retailers that sell gluten-free products in a specific country.

  Args:
    country_code: ISO 3166-1 alpha-2 code (AU, NZ, GB, IE, DE, FR, CA, SG).
    bulk_or_group_only: If True, only return retailers that support bulk or
      group purchasing (useful when group_size > 1).

  Returns:
    A RetailerSearchResult dict with 'retailers' (id, name, channel, website,
    delivery fee, free-delivery threshold, currency) and a 'data_notice'.
    If no curated data exists for the country, returns a ToolError whose
    recovery_hint tells you to use the live web search agent instead.
  """
  code = _require_supported(country_code)
  retailers = [r for r in _load_retailers() if r.country_code == code]
  if bulk_or_group_only:
    retailers = [r for r in retailers if r.supports_bulk_or_group]
  if not retailers:
    raise GuidedToolError(
        "NO_CURATED_RETAILERS",
        f"No curated retailer data for {code}"
        + (" with bulk/group support." if bulk_or_group_only else "."),
        "If bulk_or_group_only was True, retry with False. Otherwise call the "
        "live_retailer_search_agent tool (if available) to find retailers via "
        "Google Search, and clearly label those results as unverified.",
    )
  return RetailerSearchResult(
      country_code=code,
      retailers=retailers,
      data_notice=(
          "Illustrative curated data; confirm stock, prices and delivery terms "
          "with the retailer."
      ),
  ).model_dump()


@guided_errors
def list_gluten_free_products_by_category(
    country_code: CountryCode,
    categories: list[ProductCategory],
    retailer_id: Optional[str] = None,
) -> dict:
  """Lists candidate gluten-free products (with full label data) in a country.

  Returned products are CANDIDATES only. Every product must still be checked
  independently with check_ingredients_for_gluten_sources.

  Args:
    country_code: ISO code (AU, NZ, GB, IE, DE, FR, CA, SG).
    categories: Product categories to include, e.g. ['breakfast_cereal'].
    retailer_id: Optional retailer_id from find_gluten_free_retailers_by_country
      to restrict results to one retailer.

  Returns:
    A ProductSearchResult dict. Each product includes ingredients,
    allergen_statement, may_contain, certifications, pack size, price,
    nutrition_per_100g, label_ratings and bulk_tiers.
  """
  code = _require_supported(country_code)
  if not categories:
    raise GuidedToolError(
        "MISSING_CATEGORIES",
        "No product categories were provided.",
        "Use the product_categories from the saved shopping_requirements, or "
        "ask the user which categories they want.",
    )
  products = [
      p for p in _load_products()
      if p.country_code == code and p.category in set(categories)
      and (retailer_id is None or p.retailer_id == retailer_id)
  ]
  if not products:
    raise GuidedToolError(
        "NO_PRODUCTS_FOUND",
        f"No curated products for {code} in {categories}"
        + (f" at {retailer_id}." if retailer_id else "."),
        "Retry without retailer_id, or with broader categories. If still "
        "empty, tell the user no curated products are available and offer a "
        "live web search.",
    )
  return ProductSearchResult(
      country_code=code,
      products=products,
      data_notice="Synthetic sample products for demonstration.",
  ).model_dump()


def get_retailer(retailer_id: str) -> Optional[Retailer]:
  """Internal helper: returns a Retailer by id or None."""
  return next((r for r in _load_retailers() if r.retailer_id == retailer_id), None)


def get_product(product_id: str) -> Optional[Product]:
  """Internal helper: returns a Product by id or None."""
  return next((p for p in _load_products() if p.product_id == product_id), None)
