"""Unit tests: health scoring against national standards."""

from __future__ import annotations

import pytest

from gf_agent.tools.health import (
    assess_nutrition_against_national_standard,
    canada_high_in_flags,
    singapore_nutri_grade,
    uk_traffic_lights,
)

HEALTHY = {"energy_kj": 1400, "fat_g": 2.0, "saturated_fat_g": 0.5,
           "sugars_g": 1.0, "salt_g": 0.1, "fibre_g": 8.0, "protein_g": 10}
SUGARY = {"energy_kj": 2000, "fat_g": 22.0, "saturated_fat_g": 13.0,
          "sugars_g": 32.0, "salt_g": 0.6, "fibre_g": 1.0, "protein_g": 4}


def _assess(country, nutrition, serving=40, beverage=False, ratings=None):
  return assess_nutrition_against_national_standard(request={
      "product_name": "x", "country_code": country, "nutrition_per_100g": nutrition,
      "serving_size_g": serving, "is_beverage": beverage, "label_ratings": ratings or {},
  })


@pytest.mark.parametrize("value,expected", [(3.0, "green"), (3.1, "amber"), (17.5, "amber"), (17.6, "red")])
def test_uk_fat_thresholds_boundaries(value, expected):
  n = dict(HEALTHY, fat_g=value)
  assert uk_traffic_lights(n, is_beverage=False)["fat"] == expected


def test_uk_beverage_thresholds_differ_from_food():
  n = dict(HEALTHY, sugars_g=4.0)
  assert uk_traffic_lights(n, is_beverage=False)["sugars"] == "green"
  assert uk_traffic_lights(n, is_beverage=True)["sugars"] == "amber"


def test_healthy_product_scores_high_and_cites_standards():
  r = _assess("GB", HEALTHY)
  assert r["status"] == "success"
  assert r["is_healthy_choice"] is True
  assert r["health_score"] >= 90
  assert all(c["url"].startswith("http") for c in r["standards_cited"])


def test_sugary_product_not_healthy():
  r = _assess("GB", SUGARY)
  assert r["is_healthy_choice"] is False
  assert r["traffic_lights"]["sugars"] == "red"


def test_australia_low_health_star_rating_not_healthy():
  r = _assess("AU", HEALTHY, ratings={"health_star_rating": "2.0"})
  assert r["is_healthy_choice"] is False
  assert any("Health Star Rating 2" in f for f in r["national_flags"])
  assert any("Health Star" in c["document"] for c in r["standards_cited"])


def test_canada_high_in_symbol():
  # 40 g serving (>30 g) -> 15% DV threshold.
  # Sat fat: 13 g/100 g x 0.4 = 5.2 g = 26% of 20 g DV -> 'High in'.
  # Sugars: 32 g/100 g x 0.4 = 12.8 g = 12.8% of 100 g DV -> below 15%.
  flags = canada_high_in_flags(SUGARY, serving_size_g=40)
  assert any("saturated fat" in f for f in flags)
  assert not any("sugars" in f for f in flags)
  # Small serving (<=30 g) uses the stricter 10% threshold.
  flags_small = canada_high_in_flags(dict(SUGARY, sugars_g=40.0), serving_size_g=30)
  assert any("sugars" in f for f in flags_small)  # 12 g = 12% >= 10%
  r = _assess("CA", SUGARY)
  assert r["is_healthy_choice"] is False


@pytest.mark.parametrize("sugar,sat,grade", [(0.5, 0.5, "A"), (4.0, 0.3, "B"), (8.0, 1.0, "C"), (12.0, 0.5, "D")])
def test_singapore_nutri_grade(sugar, sat, grade):
  assert singapore_nutri_grade({"sugars_g": sugar, "saturated_fat_g": sat}) == grade


def test_eu_nutriscore_d_not_healthy():
  r = _assess("DE", HEALTHY, ratings={"nutri_score": "D"})
  assert r["is_healthy_choice"] is False


def test_invalid_nutrition_returns_guided_error():
  r = _assess("GB", {"fat_g": -1})
  assert r["status"] == "error"
  assert r["error_code"] == "INVALID_ARGUMENTS"
  assert r["recovery_hint"]
