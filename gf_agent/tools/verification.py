"""Independent gluten verification tools.

The Gluten Verification Agent uses these tools to independently re-check every
candidate product against the gluten-free law of the *destination* country.
It never trusts a retailer's "gluten-free" marketing claim on its own.
"""

from __future__ import annotations

import re

import httpx

from gf_agent import knowledge as kb
from gf_agent.schemas import (
    FlaggedIngredient,
    GlutenCheckRequest,
    GlutenVerdict,
)
from gf_agent.tools._errors import GuidedToolError, guided_errors

_SAFE_GRAIN_WORDS = {
    "rice", "maize", "corn", "potato", "tapioca", "buckwheat", "chickpea",
    "quinoa", "sorghum", "millet", "teff", "amaranth", "coconut", "almond",
    "soy", "soya", "pea", "lentil", "cassava", "arrowroot", "banana",
    "free", "gluten-free",
}
_GF_WHEAT_STARCH = re.compile(r"(gluten[- ]free|codex)\s+wheat\s+starch")
_OATS = re.compile(r"\boats?\b")
_GF_MARK = re.compile(r"gluten[- ]free")


def _word_re(term: str) -> re.Pattern[str]:
  return re.compile(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])")


def _strip_safe_phrases(text: str) -> str:
  for phrase in kb.SAFE_PHRASES:
    text = text.replace(phrase, " ")
  return text


def _ambiguous_hits(text: str) -> list[tuple[str, str]]:
  """Returns (term, question) for ingredient terms whose grain source is unknown."""
  hits: list[tuple[str, str]] = []
  for term, question in kb.AMBIGUOUS_TERMS.items():
    for m in _word_re(term).finditer(text):
      if term in ("flour", "starch", "modified starch"):
        before = text[: m.start()].strip().split()
        prev = before[-1].strip("(),") if before else ""
        paren = re.match(r"\s*\(([^)]*)\)", text[m.end():])
        if term == "starch" and prev == "modified":
          continue  # handled by the "modified starch" entry
        if prev in _SAFE_GRAIN_WORDS:
          continue  # e.g. "rice flour", "tapioca starch"
        if paren and any(w in paren.group(1).split() for w in _SAFE_GRAIN_WORDS):
          continue  # e.g. "modified starch (maize)"
      hits.append((term, question))
      break
  return hits


def _check_ingredient(
    ingredient: str, law: dict
) -> tuple[list[FlaggedIngredient], list[str], list[str]]:
  """Classifies one ingredient. Returns (flags, questions, notes)."""
  flags: list[FlaggedIngredient] = []
  questions: list[str] = []
  notes: list[str] = []
  s = ingredient.lower()
  work = s

  # 1. Gluten-free (Codex) wheat starch: legal in EU/UK, not in AU/NZ/CA.
  if _GF_WHEAT_STARCH.search(work):
    permitted = law["wheat_starch_permitted"]
    if permitted is True:
      notes.append(f"'{ingredient}': gluten-free wheat starch is permitted ({law['threshold']}).")
    elif permitted is None:
      flags.append(FlaggedIngredient(ingredient=ingredient, severity="uncertain",
          reason="Gluten-free wheat starch: national position is not explicit."))
      questions.append(
          f"'{ingredient}': has this product been tested to {law['threshold']} and is it "
          "accepted by your national coeliac society?")
    else:
      flags.append(FlaggedIngredient(ingredient=ingredient, severity="not_permitted_in_country",
          reason="Wheat starch is not permitted in gluten-free foods in this country."))
    work = _GF_WHEAT_STARCH.sub(" ", work)

  # 2. Oats: banned in AU/NZ GF claims; elsewhere only if specially produced GF.
  if _OATS.search(work):
    if not law["oats_permitted"]:
      flags.append(FlaggedIngredient(ingredient=ingredient, severity="not_permitted_in_country",
          reason="Oats/oat products are not permitted in gluten-free claims in this country."))
    elif not _GF_MARK.search(work):
      flags.append(FlaggedIngredient(ingredient=ingredient, severity="uncertain",
          reason="Oats are only acceptable if specially produced gluten-free."))
      questions.append(f"'{ingredient}': are these certified gluten-free oats (specially produced, {law['threshold']})?")
    else:
      notes.append(f"'{ingredient}': specially produced gluten-free oats (some coeliacs also react to avenin).")
    work = re.sub(r"\boats?\b|\boat\b", " ", work)

  # 3. Malt vinegar: banned where malted gluten cereals are banned, else ask.
  if "malt vinegar" in work:
    if law["malt_permitted"] is False:
      flags.append(FlaggedIngredient(ingredient=ingredient, severity="not_permitted_in_country",
          reason="Malted gluten-containing cereals are not permitted in GF claims here."))
    else:
      flags.append(FlaggedIngredient(ingredient=ingredient, severity="uncertain",
          reason="Malt vinegar is derived from barley; acceptability depends on testing."))
      questions.append(kb.AMBIGUOUS_TERMS["malt vinegar"])
    work = work.replace("malt vinegar", " ")

  # 4. Definite gluten sources (whole-word), after removing safe phrases.
  stripped = _strip_safe_phrases(work)
  terms = kb.GLUTEN_TERMS + ("malt",)
  found = sorted({t for t in terms if _word_re(t).search(stripped)})
  if found:
    flags.append(FlaggedIngredient(ingredient=ingredient, severity="contains_gluten",
        reason=f"Contains gluten source(s): {', '.join(found)}."))
    return flags, questions, notes

  # 5. Highly refined derivatives (informational).
  for term in kb.REFINED_EXEMPT:
    if term in work:
      notes.append(f"'{ingredient}': highly refined; exempt from allergen labelling and generally accepted as gluten-free.")

  # 6. Ambiguous ingredients -> clarification question.
  if not flags:
    for term, question in _ambiguous_hits(work):
      flags.append(FlaggedIngredient(ingredient=ingredient, severity="uncertain",
          reason=f"Source of '{term}' is not stated."))
      questions.append(question)
  return flags, questions, notes


@guided_errors
def check_ingredients_for_gluten_sources(request: GlutenCheckRequest) -> dict:
  """Independently classifies a product as gluten-free for a specific country.

  Applies the destination country's gluten-free labelling law (e.g. FSANZ
  'no detectable gluten' and no oats in Australia/NZ; <= 20 mg/kg under EU
  828/2014 in the EU/UK; Health Canada B.24.018) to the ingredient list,
  allergen 'contains' statement and 'may contain' statement. Retailer
  "gluten-free" claims and certifications are recorded but never override a
  detected gluten source.

  Args:
    request: The product to check:
      - product_name: Product name as shown to the user.
      - country_code: ISO country where it will be bought and eaten
        (AU, NZ, GB, IE, DE, FR, CA, SG).
      - ingredients: Each ingredient as a separate string, in label order.
      - allergen_statement: The label's 'Contains:' statement, if any.
      - may_contain: The label's precautionary 'May contain' statement, if any.
      - certifications: Certification marks on pack, e.g. 'Crossed Grain'.

  Returns:
    A GlutenVerdict dict with gluten_status:
      - VERIFIED: no gluten source found under the country's law.
      - EXCLUDED: contains gluten or an ingredient not permitted in that country.
      - NEEDS_CLARIFICATION: uncertain items; ask the user the returned
        clarification_questions before recommending it.
    On invalid input, returns a ToolError dict with a recovery_hint.
  """
  req = (
      request
      if isinstance(request, GlutenCheckRequest)
      else GlutenCheckRequest.model_validate(request)
  )
  law = kb.GLUTEN_LAW[req.country_code]
  flags: list[FlaggedIngredient] = []
  questions: list[str] = []
  notes: list[str] = []

  for ingredient in req.ingredients:
    f, q, n = _check_ingredient(ingredient, law)
    flags += f
    questions += q
    notes += n

  # Allergen 'Contains' statement (ignore the wheat mention caused solely by
  # gluten-free wheat starch, which is already judged at ingredient level).
  stmt = re.sub(r"wheat\s*\(\s*(gluten[- ]free|codex) wheat starch\s*\)", " ",
                req.allergen_statement.lower())
  stmt = _strip_safe_phrases(stmt)
  stmt_hits = sorted({t for t in kb.GLUTEN_TERMS if _word_re(t).search(stmt)})
  if stmt_hits:
    flags.append(FlaggedIngredient(ingredient="Allergen statement", severity="contains_gluten",
        reason=f"Label declares: {', '.join(stmt_hits)}."))

  # Precautionary 'May contain' statement -> cross-contact risk.
  may = _strip_safe_phrases(req.may_contain.lower())
  may_hits = sorted({t for t in kb.GLUTEN_TERMS if _word_re(t).search(may)})
  if may_hits:
    flags.append(FlaggedIngredient(ingredient="May contain statement", severity="uncertain",
        reason=f"Possible cross-contact with: {', '.join(may_hits)}."))
    questions.append(
        f"The label warns it may contain {', '.join(may_hits)}. Is the product tested to "
        f"{law['threshold']}? If unsure, it should be avoided by people with coeliac disease.")

  recognised = sorted({
      label for key, label in kb.RECOGNISED_CERTIFICATIONS.items()
      for c in req.certifications if key in c.lower()
  })

  severities = {f.severity for f in flags}
  if severities & {"contains_gluten", "not_permitted_in_country"}:
    status = "EXCLUDED"
  elif "uncertain" in severities:
    status = "NEEDS_CLARIFICATION"
  else:
    status = "VERIFIED"

  reasoning_parts = [f"Assessed against {law['citation'].authority} ({law['threshold']})."]
  if flags:
    reasoning_parts.append("; ".join(f"{f.ingredient}: {f.reason}" for f in flags))
  if notes:
    reasoning_parts.append(" ".join(notes))
  if recognised:
    reasoning_parts.append(
        "Recognised certification(s): " + ", ".join(recognised)
        + ". Certification is supporting evidence only and never overrides a detected gluten source.")

  return GlutenVerdict(
      product_name=req.product_name,
      country_code=req.country_code,
      gluten_status=status,
      flagged_ingredients=flags,
      clarification_questions=list(dict.fromkeys(questions)),
      recognised_certifications=recognised,
      reasoning=" ".join(reasoning_parts),
      standard_applied=law["citation"],
  ).model_dump()


_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_OFF_FIELDS = "product_name,ingredients_text,allergens_tags,traces_tags,labels_tags,nutriments"


@guided_errors
def lookup_product_label_by_barcode(barcode: str) -> dict:
  """Looks up a product's label data in the public Open Food Facts database.

  Use this to independently obtain ingredients, allergens and 'may contain'
  traces for a product the user mentions by barcode (EAN/UPC), instead of
  relying on retailer descriptions. No API key is required.

  Args:
    barcode: The 8-14 digit EAN/UPC barcode printed on the pack.

  Returns:
    {'status': 'success', 'product_name', 'ingredients_text', 'allergens',
    'traces', 'labels', 'source'} on success, or a ToolError dict with a
    recovery_hint (e.g. ask the user to read the ingredient list aloud).
  """
  code = barcode.strip().replace(" ", "")
  if not re.fullmatch(r"\d{8,14}", code):
    raise GuidedToolError(
        "INVALID_BARCODE",
        f"'{barcode}' is not an 8-14 digit EAN/UPC barcode.",
        "Ask the user to re-read the digits under the barcode, or ask them to "
        "type the ingredient list instead and call check_ingredients_for_gluten_sources.",
    )
  try:
    resp = httpx.get(
        _OFF_URL.format(barcode=code),
        params={"fields": _OFF_FIELDS},
        headers={"User-Agent": "gf-sourcing-agent/1.0 (educational project)"},
        timeout=8.0,
    )
  except httpx.HTTPError as e:
    raise GuidedToolError(
        "LOOKUP_UNAVAILABLE",
        f"Open Food Facts could not be reached ({type(e).__name__}).",
        "Do not guess the ingredients. Ask the user to type the ingredient "
        "list from the pack, then call check_ingredients_for_gluten_sources.",
    ) from e
  data = resp.json() if resp.status_code == 200 else {}
  product = data.get("product") if data.get("status") == 1 else None
  if not product:
    raise GuidedToolError(
        "PRODUCT_NOT_FOUND",
        f"No Open Food Facts record for barcode {code}.",
        "Ask the user to type the ingredient list, allergen statement and any "
        "'may contain' warning from the pack.",
    )
  return {
      "status": "success",
      "product_name": product.get("product_name", ""),
      "ingredients_text": product.get("ingredients_text", ""),
      "allergens": product.get("allergens_tags", []),
      "traces": product.get("traces_tags", []),
      "labels": product.get("labels_tags", []),
      "source": "Open Food Facts (crowd-sourced; verify against the physical label)",
  }
