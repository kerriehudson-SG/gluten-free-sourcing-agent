"""Health assessment tools based on cited national healthy-food standards."""

from __future__ import annotations

from gf_agent import knowledge as kb
from gf_agent.schemas import HealthAssessment, HealthAssessmentRequest
from gf_agent.tools._errors import GuidedToolError, guided_errors

_LIGHT_POINTS = {"green": 25.0, "amber": 12.5, "red": 0.0}
_NUTRIENT_LABELS = {
    "fat_g": "fat", "saturated_fat_g": "saturated fat",
    "sugars_g": "sugars", "salt_g": "salt",
}


def uk_traffic_lights(nutrition: dict, is_beverage: bool) -> dict[str, str]:
  """Applies UK FSA/DHSC front-of-pack traffic-light thresholds per 100 g/mL."""
  table = kb.UK_TRAFFIC_LIGHTS_DRINK if is_beverage else kb.UK_TRAFFIC_LIGHTS_FOOD
  lights: dict[str, str] = {}
  for key, (low_max, high_min) in table.items():
    value = float(nutrition[key])
    if value <= low_max:
      lights[_NUTRIENT_LABELS[key]] = "green"
    elif value > high_min:
      lights[_NUTRIENT_LABELS[key]] = "red"
    else:
      lights[_NUTRIENT_LABELS[key]] = "amber"
  return lights


def canada_high_in_flags(nutrition: dict, serving_size_g: float) -> list[str]:
  """Health Canada FOP 'High in' symbol using the serving as reference amount."""
  threshold_pct = 10.0 if serving_size_g <= 30 else 15.0
  factor = serving_size_g / 100.0
  per_serving = {
      "saturated fat": nutrition["saturated_fat_g"] * factor / kb.CA_DAILY_VALUES["saturated_fat_g"] * 100,
      "sugars": nutrition["sugars_g"] * factor / kb.CA_DAILY_VALUES["sugars_g"] * 100,
      "sodium": (nutrition["salt_g"] / 2.5 * 1000) * factor / kb.CA_DAILY_VALUES["sodium_mg"] * 100,
  }
  return [
      f"Health Canada FOP: 'High in {name}' ({pct:.0f}% DV per serving >= {threshold_pct:.0f}%)"
      for name, pct in per_serving.items() if pct >= threshold_pct
  ]


def singapore_nutri_grade(nutrition: dict) -> str:
  """Singapore Nutri-Grade for beverages (per 100 mL)."""
  sugar, sat = nutrition["sugars_g"], nutrition["saturated_fat_g"]
  for grade, max_sugar, max_sat in kb.SG_NUTRIGRADE_LIMITS:
    if sugar <= max_sugar and sat <= max_sat:
      return grade
  return "D"


@guided_errors
def assess_nutrition_against_national_standard(
    request: HealthAssessmentRequest,
) -> dict:
  """Scores a product's healthiness against cited national nutrition standards.

  Always applies the UK FSA/DHSC front-of-pack traffic-light thresholds as a
  transparent common baseline, then overlays the destination country's own
  scheme: Australia/NZ Health Star Rating (from label), Health Canada
  front-of-package 'High in' symbol (computed), Singapore Nutri-Grade for
  beverages (computed) / Healthier Choice Symbol (from label), and EU
  Nutri-Score (from label).

  Args:
    request: The product nutrition to assess:
      - product_name: Product name.
      - country_code: Destination country (AU, NZ, GB, IE, DE, FR, CA, SG).
      - nutrition_per_100g: energy_kj, fat_g, saturated_fat_g, sugars_g,
        salt_g, fibre_g, protein_g per 100 g (per 100 mL for beverages).
      - serving_size_g: Serving size in g or mL (used for Canada's symbol).
      - is_beverage: True for drinks (uses beverage thresholds).
      - label_ratings: Ratings printed on pack, e.g. {'health_star_rating':
        '4.0'}, {'nutri_score': 'B'}, {'healthier_choice_symbol': 'yes'}.

  Returns:
    A HealthAssessment dict: health_score (0-100), is_healthy_choice,
    traffic_lights, national_flags and standards_cited (authority, document,
    URL) that MUST be cited in the final report.
  """
  req = (
      request
      if isinstance(request, HealthAssessmentRequest)
      else HealthAssessmentRequest.model_validate(request)
  )
  nutrition = req.nutrition_per_100g.model_dump()
  lights = uk_traffic_lights(nutrition, req.is_beverage)
  score = sum(_LIGHT_POINTS[v] for v in lights.values())
  flags: list[str] = []
  healthy = "red" not in lights.values()

  if not req.is_beverage and nutrition["fibre_g"] >= 6.0:
    score += 10
    flags.append("High fibre (>= 6 g/100 g, EU Reg. 1924/2006 definition)")

  ratings = {k.lower(): str(v).strip() for k, v in req.label_ratings.items()}
  code = req.country_code

  if code in ("AU", "NZ"):
    hsr = ratings.get("health_star_rating")
    if hsr:
      try:
        stars = float(hsr.split()[0])
      except ValueError as e:
        raise GuidedToolError(
            "INVALID_LABEL_RATING",
            f"health_star_rating '{hsr}' is not a number.",
            "Pass the Health Star Rating as a number string such as '4.0', "
            "or omit it if not printed on the label.") from e
      flags.append(f"Health Star Rating {stars:g}/5 (label)")
      if stars < 3.5:
        healthy = False
    else:
      flags.append("No Health Star Rating on label; traffic-light baseline used")
  elif code == "CA":
    high_in = canada_high_in_flags(nutrition, req.serving_size_g)
    flags += high_in
    if high_in:
      healthy = False
      score -= 10 * len(high_in)
  elif code == "SG":
    if req.is_beverage:
      grade = ratings.get("nutri_grade") or singapore_nutri_grade(nutrition)
      flags.append(f"Nutri-Grade {grade}")
      if grade in ("C", "D"):
        healthy = False
    if ratings.get("healthier_choice_symbol", "").lower() in ("yes", "true"):
      flags.append("Healthier Choice Symbol (label)")
      score += 5
  elif code in ("IE", "DE", "FR"):
    ns = ratings.get("nutri_score", "").upper()
    if ns:
      flags.append(f"Nutri-Score {ns} (label)")
      if ns in ("D", "E"):
        healthy = False

  score = int(max(0, min(100, round(score))))
  return HealthAssessment(
      product_name=req.product_name,
      country_code=code,
      health_score=score,
      is_healthy_choice=healthy,
      traffic_lights=lights,
      national_flags=flags,
      standards_cited=kb.HEALTH_STANDARDS_BY_COUNTRY[code],
      method_note=(
          "Transparent heuristic: 25 points per green / 12.5 per amber UK "
          "traffic light (fat, saturated fat, sugars, salt), +10 high fibre, "
          "national overlays applied. Not an official government rating."
      ),
  ).model_dump()
