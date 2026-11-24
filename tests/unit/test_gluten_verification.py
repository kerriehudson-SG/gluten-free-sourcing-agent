"""Golden-dataset regression tests for independent gluten verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gf_agent.tools.sourcing import _load_products
from gf_agent.tools.verification import check_ingredients_for_gluten_sources

GOLDEN = json.loads(
    (Path(__file__).resolve().parent.parent / "golden" / "gluten_golden.json").read_text()
)
PRODUCTS = {p.product_id: p for p in _load_products()}


def _check(**kwargs):
  return check_ingredients_for_gluten_sources(request={"product_name": "test", **kwargs})


def test_golden_covers_entire_catalogue():
  assert set(GOLDEN["catalogue_expectations"]) == set(PRODUCTS)


@pytest.mark.parametrize("product_id,expected", sorted(GOLDEN["catalogue_expectations"].items()))
def test_catalogue_product_classification(product_id, expected):
  p = PRODUCTS[product_id]
  result = check_ingredients_for_gluten_sources(request={
      "product_name": p.name, "country_code": p.country_code,
      "ingredients": p.ingredients, "allergen_statement": p.allergen_statement,
      "may_contain": p.may_contain, "certifications": p.certifications,
  })
  assert result["status"] == "success"
  assert result["gluten_status"] == expected, result["reasoning"]


@pytest.mark.parametrize("case", GOLDEN["edge_cases"], ids=lambda c: c["id"])
def test_edge_cases(case):
  kwargs = {k: v for k, v in case.items() if k not in ("id", "expected")}
  result = _check(**kwargs)
  assert result["gluten_status"] == case["expected"], result["reasoning"]


def test_needs_clarification_always_has_questions():
  for case in GOLDEN["edge_cases"]:
    kwargs = {k: v for k, v in case.items() if k not in ("id", "expected")}
    result = _check(**kwargs)
    if result["gluten_status"] == "NEEDS_CLARIFICATION":
      assert result["clarification_questions"], case["id"]


def test_verdict_cites_country_standard():
  au = _check(country_code="AU", ingredients=["rice"])
  gb = _check(country_code="GB", ingredients=["rice"])
  assert "FSANZ" in au["standard_applied"]["authority"]
  assert au["standard_applied"]["url"].startswith("https://")
  assert "Food Standards Agency" in gb["standard_applied"]["authority"]


def test_recognised_certification_reported():
  result = _check(country_code="GB", ingredients=["rice"], certifications=["Crossed Grain"])
  assert result["recognised_certifications"]
  assert result["gluten_status"] == "VERIFIED"
