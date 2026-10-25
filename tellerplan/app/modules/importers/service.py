"""Import von Rezeptentwürfen im Format „tellerplan-recipes“ (z. B. aus tools/cookidoo_fetch.py).

Regel 2: Ein Entwurf liefert Titel, Portionen, Link, Quell-ID und rohe Zutatenzeilen,
nie Nährwerte. Werte der Quelle kommen nur als Vergleich (`reference`) mit.

Ein Rezept mit derselben Quelle und Quell-ID wird nicht doppelt angelegt. Bei einem
erneuten Import werden Titel, Portionen, Kategorie, Link, Notiz und Vergleichswerte
aktualisiert; die Zutaten bleiben, damit Zuordnungen nicht verloren gehen.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from modules.importers.line_parser import parse_line
from modules.recipes.matching import add_parsed_ingredient
from modules.recipes.models import Recipe
from modules.recipes.service import (
    RecipeInput,
    create_recipe,
    find_recipe_by_source,
    has_no_nutrients,
    resolved_food,
    set_reference,
    update_recipe,
)

FORMAT = "tellerplan-recipes"
FORMAT_VERSION = 1
# Fehlt die Portionenzahl in der Quelle, gilt das Rezept als eine Portion.
FALLBACK_SERVINGS = 1.0
REFERENCE_FIELDS = {
    "kcal": "kcal_per_serving",
    "protein_g": "protein_g_per_serving",
    "fat_g": "fat_g_per_serving",
    "carbs_g": "carbs_g_per_serving",
}


class ImportFormatError(ValueError):
    """Die Datei ist kein gültiger Rezeptexport für Tellerplan."""


@dataclass(frozen=True)
class ImportResult:
    created: int
    updated: int
    lines: int
    matched_lines: int


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ImportFormatError(message)


def _recipes(document: object) -> tuple[str, list[dict[str, Any]]]:
    _require(isinstance(document, dict), "Die Datei enthält kein JSON-Objekt.")
    assert isinstance(document, dict)
    _require(document.get("format") == FORMAT, f"Unbekanntes Format, erwartet „{FORMAT}“.")
    _require(document.get("version") == FORMAT_VERSION, "Diese Version wird nicht unterstützt.")
    source = document.get("source")
    _require(isinstance(source, str) and bool(source), "Die Quelle fehlt.")
    recipes = document.get("recipes")
    _require(isinstance(recipes, list), "Die Rezeptliste fehlt.")
    for draft in recipes:
        _require(isinstance(draft, dict), "Ein Rezept ist kein JSON-Objekt.")
        _require(isinstance(draft.get("source_id"), str), "Ein Rezept hat keine Quell-ID.")
        _require(
            isinstance(draft.get("title"), str), f"Rezept {draft.get('source_id')}: Titel fehlt."
        )
    return str(source), recipes


def _servings(value: object) -> float:
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return FALLBACK_SERVINGS


def _note(draft: dict[str, Any]) -> str | None:
    parts = []
    if draft.get("total_time"):
        parts.append(f"Gesamtzeit {draft['total_time']}")
    if draft.get("note"):
        parts.append(str(draft["note"]))
    return " · ".join(parts) or None


def _recipe_input(draft: dict[str, Any]) -> RecipeInput:
    return RecipeInput(
        title=draft["title"].strip(),
        servings=_servings(draft.get("servings")),
        category=draft.get("category") or None,
        source_url=draft.get("source_url") or None,
        note=_note(draft),
    )


def _reference(draft: dict[str, Any]) -> dict[str, float | None]:
    reference = draft.get("reference") or {}
    values: dict[str, float | None] = {}
    for field, key in REFERENCE_FIELDS.items():
        value = reference.get(key) if isinstance(reference, dict) else None
        values[field] = float(value) if isinstance(value, int | float) else None
    return values


def _add_lines(session: Session, recipe: Recipe, lines: object) -> None:
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, str) or not line.strip():
            continue
        parsed = parse_line(line)
        add_parsed_ingredient(
            session, recipe, line.strip(), parsed.name, parsed.quantity, parsed.unit
        )


def import_document(session: Session, document: object) -> ImportResult:
    """Legt neue Rezepte an oder aktualisiert vorhandene; der Aufrufer schreibt fest."""
    source, drafts = _recipes(document)
    created = updated = 0
    touched: list[Recipe] = []
    for draft in drafts:
        recipe = find_recipe_by_source(session, source, draft["source_id"])
        if recipe is None:
            recipe = create_recipe(session, _recipe_input(draft))
            recipe.source = source
            recipe.source_id = draft["source_id"]
            _add_lines(session, recipe, draft.get("ingredients"))
            created += 1
        else:
            update_recipe(session, recipe, _with_instructions(recipe, _recipe_input(draft)))
            updated += 1
        set_reference(session, recipe, _reference(draft))
        touched.append(recipe)
    lines = [ingredient for recipe in touched for ingredient in recipe.ingredients]
    return ImportResult(
        created=created,
        updated=updated,
        lines=len(lines),
        matched_lines=sum(
            1 for line in lines if resolved_food(line) is not None or has_no_nutrients(line)
        ),
    )


def _with_instructions(recipe: Recipe, data: RecipeInput) -> RecipeInput:
    """Von Hand eingetragene Kochschritte überstehen einen erneuten Import."""
    return RecipeInput(
        title=data.title,
        servings=data.servings,
        category=data.category,
        source_url=data.source_url,
        note=data.note,
        instructions=recipe.instructions,
    )
