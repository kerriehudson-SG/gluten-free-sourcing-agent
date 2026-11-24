"""Explicit Pydantic schemas for every tool input/output and agent output.

Rubric: Tool & Interface Design -> Explicit JSON Schemas.

These models are used to:
  1. Generate strict JSON schemas for tool function declarations (ADK converts
     Pydantic-typed parameters into the function declaration sent to Gemini).
  2. Validate every tool argument at runtime (invalid input -> guided error).
  3. Constrain LLM output via `output_schema` on the report writer agent.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Shared enums / primitives
# ---------------------------------------------------------------------------

CountryCode = Literal["AU", "NZ", "GB", "IE", "DE", "FR", "CA", "SG"]
SUPPORTED_COUNTRIES: tuple[str, ...] = (
    "AU", "NZ", "GB", "IE", "DE", "FR", "CA", "SG",
)

ProductCategory = Literal[
    "bread_bakery", "breakfast_cereal", "pasta_grains", "snacks",
    "flour_baking", "beverages", "condiments",
]

GlutenStatus = Literal["VERIFIED", "EXCLUDED", "NEEDS_CLARIFICATION"]

RetailerChannel = Literal[
    "supermarket", "bulk_warehouse", "online_specialist", "pharmacy_health",
]


class StrictModel(BaseModel):
  """Base model: reject unknown fields so the LLM cannot smuggle extra args."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Citation(StrictModel):
  """A citation to an authoritative standard or regulation."""

  authority: str = Field(description="Issuing body, e.g. 'Food Standards Agency (UK)'.")
  document: str = Field(description="Name of the standard/regulation/guidance.")
  url: str = Field(description="Official URL for the citation.")


class ToolError(StrictModel):
  """Standard guided error payload returned by tools instead of raising."""

  status: Literal["error"] = "error"
  error_code: str
  message: str
  recovery_hint: str = Field(
      description="Concrete next step the LLM should take to recover."
  )


# ---------------------------------------------------------------------------
# Requirements captured by the coordinator
# ---------------------------------------------------------------------------


class ShoppingRequirements(StrictModel):
  """The user's validated shopping brief (stored in session state)."""

  country_code: CountryCode
  group_size: int = Field(ge=1, le=50, description="Number of households/people sharing the purchase.")
  product_categories: list[ProductCategory] = Field(min_length=1, max_length=7)
  budget_per_person: Optional[float] = Field(default=None, gt=0, description="Optional budget per person in local currency.")
  dietary_notes: str = Field(default="", max_length=500, description="Non-identifying dietary notes, e.g. 'coeliac, also dairy-free'.")


# ---------------------------------------------------------------------------
# Sourcing
# ---------------------------------------------------------------------------


class Nutrition(StrictModel):
  """Nutrition values per 100 g (or per 100 mL for beverages)."""

  energy_kj: float = Field(ge=0)
  fat_g: float = Field(ge=0)
  saturated_fat_g: float = Field(ge=0)
  sugars_g: float = Field(ge=0)
  salt_g: float = Field(ge=0)
  fibre_g: float = Field(default=0, ge=0)
  protein_g: float = Field(default=0, ge=0)


class BulkTier(StrictModel):
  """Price per pack when buying at least `min_packs` packs."""

  min_packs: int = Field(ge=1)
  unit_price: float = Field(gt=0)


class Retailer(StrictModel):
  retailer_id: str
  name: str
  country_code: CountryCode
  channel: RetailerChannel
  website: str
  gf_range_notes: str
  supports_bulk_or_group: bool
  delivery_fee: float = Field(ge=0)
  free_delivery_threshold: Optional[float] = Field(default=None, ge=0)
  currency: str


class Product(StrictModel):
  product_id: str
  retailer_id: str
  country_code: CountryCode
  name: str
  brand: str
  category: ProductCategory
  ingredients: list[str] = Field(min_length=1)
  allergen_statement: str = ""
  may_contain: str = ""
  certifications: list[str] = Field(default_factory=list)
  pack_size_g: float = Field(gt=0)
  price: float = Field(gt=0)
  currency: str
  serving_size_g: float = Field(gt=0)
  is_beverage: bool = False
  nutrition_per_100g: Nutrition
  label_ratings: dict[str, str] = Field(
      default_factory=dict,
      description="Front-of-pack ratings printed on label, e.g. {'health_star_rating': '4.0'}.",
  )
  bulk_tiers: list[BulkTier] = Field(default_factory=list)


class RetailerSearchResult(StrictModel):
  status: Literal["success"] = "success"
  country_code: CountryCode
  retailers: list[Retailer]
  data_notice: str


class ProductSearchResult(StrictModel):
  status: Literal["success"] = "success"
  country_code: CountryCode
  products: list[Product]
  data_notice: str


# ---------------------------------------------------------------------------
# Gluten verification
# ---------------------------------------------------------------------------


class GlutenCheckRequest(StrictModel):
  """Input for an independent gluten check of one product."""

  product_name: str = Field(min_length=1, max_length=200, description="Product name as shown to the user.")
  country_code: CountryCode = Field(description="Destination country whose gluten-free law applies (UK = GB).")
  ingredients: list[str] = Field(min_length=1, max_length=100, description="One ingredient per item, in label order.")
  allergen_statement: str = Field(default="", max_length=500, description="The label's 'Contains:' statement, if any.")
  may_contain: str = Field(default="", max_length=500, description="The label's precautionary 'May contain' statement, if any.")
  certifications: list[str] = Field(default_factory=list, max_length=10, description="Certification marks on pack, e.g. 'Crossed Grain', 'GFCO'.")

  @field_validator("ingredients")
  @classmethod
  def _non_empty_items(cls, v: list[str]) -> list[str]:
    cleaned = [i.strip() for i in v if i and i.strip()]
    if not cleaned:
      raise ValueError("ingredients must contain at least one non-empty item")
    return cleaned


class FlaggedIngredient(StrictModel):
  ingredient: str
  reason: str
  severity: Literal["contains_gluten", "uncertain", "not_permitted_in_country"]


class GlutenVerdict(StrictModel):
  status: Literal["success"] = "success"
  product_name: str
  country_code: CountryCode
  gluten_status: GlutenStatus
  flagged_ingredients: list[FlaggedIngredient]
  clarification_questions: list[str]
  recognised_certifications: list[str]
  reasoning: str
  standard_applied: Citation


# ---------------------------------------------------------------------------
# Health assessment
# ---------------------------------------------------------------------------


class HealthAssessmentRequest(StrictModel):
  product_name: str = Field(min_length=1, max_length=200, description="Product name.")
  country_code: CountryCode = Field(description="Destination country whose health scheme is overlaid.")
  nutrition_per_100g: Nutrition = Field(description="Nutrition per 100 g (per 100 mL for beverages).")
  serving_size_g: float = Field(gt=0, le=2000, description="Serving size in g or mL (used for Health Canada's symbol).")
  is_beverage: bool = Field(default=False, description="True for drinks (uses beverage thresholds).")
  label_ratings: dict[str, str] = Field(default_factory=dict, description="Ratings printed on pack, e.g. {'health_star_rating': '4.0'}, {'nutri_score': 'B'}.")


TrafficLight = Literal["green", "amber", "red"]


class HealthAssessment(StrictModel):
  status: Literal["success"] = "success"
  product_name: str
  country_code: CountryCode
  health_score: int = Field(ge=0, le=100)
  is_healthy_choice: bool
  traffic_lights: dict[str, TrafficLight]
  national_flags: list[str]
  standards_cited: list[Citation]
  method_note: str


# ---------------------------------------------------------------------------
# Cost analysis
# ---------------------------------------------------------------------------


class CostCandidate(StrictModel):
  """A verified product to be ranked for cost effectiveness."""

  product_id: str = Field(description="product_id from the catalogue.")
  name: str = Field(description="Product name.")
  retailer_id: str = Field(description="retailer_id selling this product.")
  price: float = Field(gt=0, description="Single-pack price in local currency.")
  pack_size_g: float = Field(gt=0, description="Pack size in grams (or mL).")
  health_score: int = Field(ge=0, le=100, description="From assess_nutrition_against_national_standard.")
  bulk_tiers: list[BulkTier] = Field(default_factory=list, description="Bulk price tiers, if any.")


class RankedOption(StrictModel):
  rank: int
  product_id: str
  name: str
  retailer_id: str
  price_per_100g: float
  group_unit_price: float
  packs_for_group: int
  per_person_cost: float
  savings_vs_individual_pct: float
  cost_effectiveness_score: float
  within_budget: Optional[bool]


class CostRanking(StrictModel):
  status: Literal["success"] = "success"
  group_size: int
  packs_per_person: int
  currency: str
  ranked_options: list[RankedOption]
  method_note: str


class GroupBasketLine(StrictModel):
  product_id: str = Field(min_length=1, description="product_id of a VERIFIED product.")
  packs: int = Field(ge=1, le=500, description="Number of packs for the whole group.")


class GroupPurchaseOption(StrictModel):
  retailer_id: str
  retailer_name: str
  basket_total: float
  delivery_fee: float
  grand_total: float
  per_person_total: float
  meets_free_delivery: bool


class GroupPurchaseOptions(StrictModel):
  status: Literal["success"] = "success"
  group_size: int
  currency: str
  options: list[GroupPurchaseOption]
  method_note: str


class GroupPurchaseDraft(StrictModel):
  status: Literal["success"] = "success"
  draft_id: str
  retailer_id: str
  lines: list[GroupBasketLine]
  group_size: int
  organiser_region: str
  state: Literal["DRAFT_AWAITING_ORGANISER"] = "DRAFT_AWAITING_ORGANISER"
  message: str


# ---------------------------------------------------------------------------
# Final report (LLM output_schema)
# ---------------------------------------------------------------------------


class ReportProduct(StrictModel):
  product_id: str
  name: str
  retailer: str
  gluten_status: GlutenStatus
  health_score: Optional[int] = None
  reason: str = ""


class FinalReport(StrictModel):
  """Structured final report produced by the report writer (output_schema)."""

  country_code: CountryCode
  summary: str = Field(description="3-5 sentence plain-English summary.")
  recommended_sources: list[str] = Field(description="Retailers recommended, best first.")
  recommended_products: list[ReportProduct]
  excluded_products: list[ReportProduct]
  needs_clarification: list[ReportProduct]
  clarification_questions: list[str]
  cost_ranking_summary: list[str] = Field(description="Ranked one-line cost-effectiveness options.")
  group_purchase_recommendation: str
  standards_cited: list[str] = Field(description="'Authority - Document - URL' strings.")
  disclaimer: str
