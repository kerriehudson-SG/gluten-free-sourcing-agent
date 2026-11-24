"""Unit tests: sourcing and cost-effectiveness tools."""

from __future__ import annotations

from gf_agent.schemas import BulkTier
from gf_agent.tools.cost import (
  best_unit_price,
  calculate_group_purchase_options,
  rank_products_by_cost_effectiveness,
)
from gf_agent.tools.sourcing import (
  find_gluten_free_retailers_by_country,
  list_gluten_free_products_by_category,
  record_shopping_requirements,
)


class FakeToolContext:
  def __init__(self):
    self.state = {}


# ---- Sourcing --------------------------------------------------------------

def test_find_retailers_for_australia():
  r = find_gluten_free_retailers_by_country("AU")
  assert r["status"] == "success"
  assert {x["retailer_id"] for x in r["retailers"]} >= {"au-woolworths", "au-costco"}


def test_uk_alias_maps_to_gb():
  assert find_gluten_free_retailers_by_country("UK")["country_code"] == "GB"


def test_bulk_filter_only_returns_bulk_retailers():
  r = find_gluten_free_retailers_by_country("AU", bulk_or_group_only=True)
  assert r["retailers"] and all(x["supports_bulk_or_group"] for x in r["retailers"])


def test_unsupported_country_guided_error():
  r = find_gluten_free_retailers_by_country("US")
  assert r["status"] == "error" and r["error_code"] == "UNSUPPORTED_COUNTRY"
  assert "GB" in r["recovery_hint"]


def test_supported_country_without_data_suggests_live_search():
  r = find_gluten_free_retailers_by_country("NZ")
  assert r["error_code"] == "NO_CURATED_RETAILERS"
  assert "live_retailer_search_agent" in r["recovery_hint"]


def test_list_products_by_category():
  r = list_gluten_free_products_by_category("GB", ["breakfast_cereal"])
  assert r["status"] == "success"
  assert all(p["category"] == "breakfast_cereal" for p in r["products"])


def test_list_products_empty_categories_guided_error():
  r = list_gluten_free_products_by_category("GB", [])
  assert r["error_code"] == "MISSING_CATEGORIES"


def test_record_requirements_writes_state():
  ctx = FakeToolContext()
  r = record_shopping_requirements(
      requirements={"country_code": "AU", "group_size": 6,
                    "product_categories": ["pasta_grains"]},
      tool_context=ctx)
  assert r["status"] == "success"
  assert ctx.state["shopping_requirements"]["group_size"] == 6
  assert ctx.state["user:preferred_country"] == "AU"


def test_record_requirements_rejects_bad_group_size():
  r = record_shopping_requirements(
      requirements={"country_code": "AU", "group_size": 0, "product_categories": ["snacks"]})
  assert r["error_code"] == "INVALID_ARGUMENTS"


def test_record_requirements_rejects_extra_fields():
  r = record_shopping_requirements(requirements={
      "country_code": "AU", "group_size": 2, "product_categories": ["snacks"],
      "home_address": "1 Smith Street"})
  assert r["error_code"] == "INVALID_ARGUMENTS"


# ---- Cost ------------------------------------------------------------------

def test_best_unit_price_applies_highest_eligible_tier():
  tiers = [BulkTier(min_packs=2, unit_price=9.0), BulkTier(min_packs=5, unit_price=8.0)]
  assert best_unit_price(10.0, tiers, 1) == 10.0
  assert best_unit_price(10.0, tiers, 3) == 9.0
  assert best_unit_price(10.0, tiers, 6) == 8.0


def test_ranking_prefers_health_per_cost():
  candidates = [
      {"product_id": "a", "name": "cheap unhealthy", "retailer_id": "r", "price": 2.0,
       "pack_size_g": 500, "health_score": 20, "bulk_tiers": []},
      {"product_id": "b", "name": "healthy value", "retailer_id": "r", "price": 3.0,
       "pack_size_g": 500, "health_score": 90, "bulk_tiers": []},
  ]
  r = rank_products_by_cost_effectiveness(candidates=candidates, group_size=1, currency="AUD")
  assert r["ranked_options"][0]["product_id"] == "b"
  assert [o["rank"] for o in r["ranked_options"]] == [1, 2]


def test_group_size_unlocks_bulk_savings_and_budget_flag():
  candidates = [{"product_id": "au-p3", "name": "Penne", "retailer_id": "au-costco",
                 "price": 18.99, "pack_size_g": 3000, "health_score": 95,
                 "bulk_tiers": [{"min_packs": 5, "unit_price": 15.99}]}]
  r = rank_products_by_cost_effectiveness(
      candidates=candidates, group_size=6, currency="AUD", budget_per_person=16.0)
  opt = r["ranked_options"][0]
  assert opt["group_unit_price"] == 15.99
  assert opt["savings_vs_individual_pct"] > 15
  assert opt["within_budget"] is True


def test_rank_without_candidates_guided_error():
  r = rank_products_by_cost_effectiveness(candidates=[], group_size=2, currency="GBP")
  assert r["error_code"] == "NO_CANDIDATES"


def test_group_purchase_options_delivery_threshold():
  r = calculate_group_purchase_options(
      basket=[{"product_id": "gb-p1", "packs": 20}, {"product_id": "gb-p5", "packs": 8}],
      group_size=4)
  assert r["status"] == "success"
  tesco = next(o for o in r["options"] if o["retailer_id"] == "gb-tesco")
  # 20 x 2.20 + 8 x 1.60 = 56.80 >= 50 free-delivery threshold
  assert tesco["basket_total"] == 56.8
  assert tesco["meets_free_delivery"] is True and tesco["delivery_fee"] == 0
  assert tesco["per_person_total"] == 14.2


def test_group_purchase_unknown_product_guided_error():
  r = calculate_group_purchase_options(basket=[{"product_id": "nope", "packs": 1}], group_size=2)
  assert r["error_code"] == "UNKNOWN_PRODUCT"
