"""Domain knowledge: national gluten-free rules and healthy-food standards.

This is the curated, version-controlled knowledge base used by the gluten
verification and health assessment tools. Every rule carries a citation so the
agents can cite the authority behind each decision.

NOTE: This is a simplified, transparent encoding for an educational project.
It is not legal or medical advice. Always check the physical label and the
latest official guidance.
"""

from __future__ import annotations

from gf_agent.schemas import Citation

# ---------------------------------------------------------------------------
# Gluten-free labelling law by country
# ---------------------------------------------------------------------------

_FSANZ = Citation(
    authority="Food Standards Australia New Zealand (FSANZ)",
    document=(
        "Australia New Zealand Food Standards Code - Standard 1.2.7 and "
        "Schedule 4 (gluten-free claim: no detectable gluten, no oats or oat "
        "products, no malted gluten-containing cereals)"
    ),
    url="https://www.foodstandards.gov.au/food-standards-code",
)
_EU = Citation(
    authority="European Union",
    document=(
        "Commission Implementing Regulation (EU) No 828/2014 - "
        "'gluten-free' means <= 20 mg/kg gluten as sold"
    ),
    url="https://eur-lex.europa.eu/eli/reg_impl/2014/828/oj",
)
_UK = Citation(
    authority="Food Standards Agency (UK)",
    document=(
        "Retained Regulation (EU) No 828/2014 as applied in Great Britain - "
        "'gluten-free' means <= 20 mg/kg gluten"
    ),
    url="https://www.legislation.gov.uk/eur/2014/828",
)
_CA = Citation(
    authority="Health Canada",
    document=(
        "Food and Drug Regulations (C.R.C., c. 870) B.24.018 and Health Canada "
        "gluten-free policy (< 20 ppm; specially produced gluten-free oats "
        "only under marketing authorization)"
    ),
    url="https://laws-lois.justice.gc.ca/eng/regulations/C.R.C.,_c._870/",
)
_SG = Citation(
    authority="Singapore Food Agency (SFA) / Codex Alimentarius",
    document=(
        "Singapore Food Regulations, with gluten-free claims assessed against "
        "Codex Standard 118-1979 (<= 20 mg/kg)"
    ),
    url="https://www.sfa.gov.sg/food-information/labelling-packaging-information",
)

GLUTEN_LAW: dict[str, dict] = {
    "AU": {"citation": _FSANZ, "threshold": "no detectable gluten",
           "oats_permitted": False, "wheat_starch_permitted": False,
           "malt_permitted": False},
    "NZ": {"citation": _FSANZ, "threshold": "no detectable gluten",
           "oats_permitted": False, "wheat_starch_permitted": False,
           "malt_permitted": False},
    "GB": {"citation": _UK, "threshold": "<= 20 mg/kg",
           "oats_permitted": True, "wheat_starch_permitted": True,
           "malt_permitted": None},
    "IE": {"citation": _EU, "threshold": "<= 20 mg/kg",
           "oats_permitted": True, "wheat_starch_permitted": True,
           "malt_permitted": None},
    "DE": {"citation": _EU, "threshold": "<= 20 mg/kg",
           "oats_permitted": True, "wheat_starch_permitted": True,
           "malt_permitted": None},
    "FR": {"citation": _EU, "threshold": "<= 20 mg/kg",
           "oats_permitted": True, "wheat_starch_permitted": True,
           "malt_permitted": None},
    "CA": {"citation": _CA, "threshold": "< 20 ppm",
           "oats_permitted": True, "wheat_starch_permitted": False,
           "malt_permitted": False},
    "SG": {"citation": _SG, "threshold": "<= 20 mg/kg (Codex)",
           "oats_permitted": True, "wheat_starch_permitted": None,
           "malt_permitted": None},
}

# Terms that always indicate gluten (matched as whole words, lower case).
GLUTEN_TERMS: tuple[str, ...] = (
    "wheat", "barley", "rye", "triticale", "spelt", "kamut", "khorasan",
    "einkorn", "emmer", "durum", "semolina", "farro", "freekeh", "bulgur",
    "couscous", "seitan", "wheat flour", "wheat gluten", "gluten",
    "brewer's yeast", "brewers yeast", "barley malt", "malt extract",
    "malt flavouring", "malt flavoring", "malted barley",
)

# Phrases that contain a gluten term but are safe (checked first).
SAFE_PHRASES: tuple[str, ...] = (
    "buckwheat", "rice malt", "gluten-free", "gluten free", "glutinous rice",
    "tamari (wheat free)", "wheat-free tamari", "corn starch", "maize starch",
    "potato starch", "tapioca starch", "rice flour", "sorghum", "millet",
    "quinoa", "amaranth", "teff",
)

# Highly refined wheat derivatives exempt from allergen labelling (EU Annex II)
# and generally accepted in GF products. Reported in reasoning, not flagged.
REFINED_EXEMPT: tuple[str, ...] = (
    "glucose syrup", "dextrose", "maltodextrin",
)

# Ambiguous ingredients: source grain unknown -> ask a question.
AMBIGUOUS_TERMS: dict[str, str] = {
    "flour": "Which grain is the 'flour' made from?",
    "starch": "What is the botanical source of the 'starch'?",
    "modified starch": "What is the source of the 'modified starch' (e.g. wheat, maize, potato)?",
    "soy sauce": "Is the soy sauce brewed with wheat, or is it a wheat-free tamari?",
    "hydrolysed vegetable protein": "What grain is the hydrolysed vegetable protein derived from?",
    "hydrolyzed vegetable protein": "What grain is the hydrolyzed vegetable protein derived from?",
    "stock": "Does the stock/bouillon contain wheat or barley?",
    "malt vinegar": "Is the malt vinegar distilled, and has the final product been tested below the gluten threshold?",
    "natural flavour": "Do the natural flavours contain barley malt or wheat derivatives?",
    "natural flavor": "Do the natural flavors contain barley malt or wheat derivatives?",
}

RECOGNISED_CERTIFICATIONS: dict[str, str] = {
    "crossed grain": "Crossed Grain symbol (Coeliac UK / AOECS licensing)",
    "coeliac australia": "Coeliac Australia Endorsement Program",
    "coeliac new zealand": "Coeliac New Zealand Endorsement",
    "gfco": "Gluten-Free Certification Organization (GFCO)",
    "gfcp": "Gluten-Free Certification Program (Canada, endorsed by Celiac Canada)",
    "aoecs": "AOECS Crossed Grain licensing",
}

# ---------------------------------------------------------------------------
# Healthy-food standards
# ---------------------------------------------------------------------------

UK_FOP = Citation(
    authority="Department of Health and Social Care / Food Standards Agency (UK)",
    document=(
        "Guide to creating a front of pack (FoP) nutrition label for "
        "pre-packed products sold through retail outlets (traffic-light "
        "thresholds per 100 g / 100 mL)"
    ),
    url="https://www.gov.uk/government/publications/front-of-pack-nutrition-labelling-guidance",
)
AU_HSR = Citation(
    authority="Australian, State and Territory and New Zealand Governments",
    document="Health Star Rating System (0.5 to 5 stars; more stars = healthier)",
    url="http://www.healthstarrating.gov.au/",
)
CA_FOP = Citation(
    authority="Health Canada",
    document=(
        "Front-of-package nutrition symbol ('High in' saturated fat, sugars, "
        "sodium: >= 10% DV for reference amounts <= 30 g, >= 15% DV otherwise; "
        "DV sat+trans fat 20 g, sugars 100 g, sodium 2300 mg)"
    ),
    url="https://www.canada.ca/en/health-canada/services/food-nutrition/nutrition-labelling/front-package.html",
)
SG_NUTRIGRADE = Citation(
    authority="Health Promotion Board / Ministry of Health (Singapore)",
    document=(
        "Nutri-Grade beverage grading (A-D by sugar and saturated fat per 100 mL) "
        "and Healthier Choice Symbol programme"
    ),
    url="https://www.hpb.gov.sg/healthy-living/food-beverage/nutri-grade",
)
EU_NUTRISCORE = Citation(
    authority="Sante publique France / EU Member States Nutri-Score steering committee",
    document="Nutri-Score front-of-pack label (A = healthiest to E)",
    url="https://www.santepubliquefrance.fr/en/nutri-score",
)
EU_CLAIMS = Citation(
    authority="European Union",
    document="Regulation (EC) No 1924/2006 - 'high fibre' >= 6 g fibre per 100 g",
    url="https://eur-lex.europa.eu/eli/reg/2006/1924/oj",
)

# UK FSA traffic-light thresholds: (low_max_inclusive, high_min_exclusive).
UK_TRAFFIC_LIGHTS_FOOD: dict[str, tuple[float, float]] = {
    "fat_g": (3.0, 17.5),
    "saturated_fat_g": (1.5, 5.0),
    "sugars_g": (5.0, 22.5),
    "salt_g": (0.3, 1.5),
}
UK_TRAFFIC_LIGHTS_DRINK: dict[str, tuple[float, float]] = {
    "fat_g": (1.5, 8.75),
    "saturated_fat_g": (0.75, 2.5),
    "sugars_g": (2.5, 11.25),
    "salt_g": (0.3, 0.75),
}

# Health Canada daily values for FOP "High in" symbol.
CA_DAILY_VALUES = {"saturated_fat_g": 20.0, "sugars_g": 100.0, "sodium_mg": 2300.0}

# Singapore Nutri-Grade per 100 mL: grade -> (max sugar g, max sat fat g).
SG_NUTRIGRADE_LIMITS = (("A", 1.0, 0.7), ("B", 5.0, 1.2), ("C", 10.0, 2.8))

HEALTH_STANDARDS_BY_COUNTRY: dict[str, list[Citation]] = {
    "AU": [UK_FOP, AU_HSR],
    "NZ": [UK_FOP, AU_HSR],
    "GB": [UK_FOP],
    "IE": [UK_FOP, EU_NUTRISCORE, EU_CLAIMS],
    "DE": [UK_FOP, EU_NUTRISCORE, EU_CLAIMS],
    "FR": [UK_FOP, EU_NUTRISCORE, EU_CLAIMS],
    "CA": [UK_FOP, CA_FOP],
    "SG": [UK_FOP, SG_NUTRIGRADE],
}
