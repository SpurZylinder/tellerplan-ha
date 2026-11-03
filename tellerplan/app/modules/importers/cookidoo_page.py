"""Rezeptseite von Cookidoo → Rezeptentwurf im Format „tellerplan-recipes“.

Reine Logik ohne Netzwerk: Den Abruf übernimmt `cookidoo.CookidooAccount.recipe_page`.
Gelesen werden die strukturierten Daten der Seite (JSON-LD, schema.org/Recipe), wie in
`tools/cookidoo_fetch.py`; die Zutatenzeilen haben damit dasselbe Format wie beim
Import der Sammlung, und gelernte Zuordnungen greifen genauso.

Regel 2: Der Entwurf liefert Titel, Portionen, Link, Quell-ID und rohe Zutatenzeilen.
Die Nährwerte der Seite (pro Portion) kommen nur als Vergleich (`reference`) mit.

Die Seite gilt als nicht vertrauenswürdig: Texte werden gekürzt, die Zahl der Zeilen
begrenzt, Link und ID kommen vom Aufrufer, nicht aus der Seite.
"""

import html
import json
import re
from typing import Any

# Wie die Spalten `recipe.title` und `recipe_ingredient.raw_text`
MAX_TEXT_LENGTH = 300
# Weit über jedem echten Rezept; schützt vor ausufernden Seiten
MAX_INGREDIENT_LINES = 100
JSON_LD_PATTERN = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
LEADING_NUMBER = re.compile(r"^\s*(\d+(?:[.,]\d+)?)")
# ISO-8601-Dauer, wie Cookidoo sie schreibt: „PT30M“, „PT1H10M“, „P1DT2H“
DURATION_PATTERN = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")
HOURS_PER_DAY = 24
REFERENCE_KEYS = {
    "kcal_per_serving": "calories",
    "protein_g_per_serving": "proteinContent",
    "fat_g_per_serving": "fatContent",
    "carbs_g_per_serving": "carbohydrateContent",
}


class RecipePageError(ValueError):
    """Die Seite enthält kein passendes Rezept."""


def recipe_data(page: str) -> dict[str, Any]:
    """Das schema.org/Recipe-Objekt aus den JSON-LD-Blöcken der Seite."""
    for block in JSON_LD_PATTERN.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Recipe":
                return item
    raise RecipePageError("Die Seite enthält keine Rezeptdaten.")


def clean_text(value: object) -> str:
    """HTML-Entitäten auflösen („&frac12;“ → „½“), Leerraum vereinheitlichen, kürzen."""
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(value).split())[:MAX_TEXT_LENGTH]


def same_title(first: str, second: str) -> bool:
    """Gleicher Titel, ohne Rücksicht auf Groß-/Kleinschreibung, Satzzeichen und Leerraum."""

    def key(text: str) -> str:
        return "".join(char for char in text.casefold() if char.isalnum())

    return key(first) == key(second)


def _leading_number(value: object) -> float | None:
    match = LEADING_NUMBER.match(value) if isinstance(value, str) else None
    return float(match.group(1).replace(",", ".")) if match else None


def _servings(recipe_yield: object) -> float | None:
    """„4 Portionen“ → 4; „recipeYield“ kann auch eine Liste sein."""
    values = recipe_yield if isinstance(recipe_yield, list) else [recipe_yield]
    for value in values:
        number = _leading_number(value)
        if number is not None and number > 0:
            return number
    return None


def _duration(value: object) -> str | None:
    """„PT1H10M“ → „1 h 10 min“; unbekannte Formen fallen weg."""
    match = DURATION_PATTERN.match(value) if isinstance(value, str) else None
    if match is None:
        return None
    days, hours, minutes = (int(part or 0) for part in match.groups())
    hours += days * HOURS_PER_DAY
    parts = [f"{hours} h"] if hours else []
    if minutes or not hours:
        parts.append(f"{minutes} min")
    return " ".join(parts)


def _ingredients(lines: object) -> list[str]:
    if not isinstance(lines, list):
        return []
    cleaned = (clean_text(line) for line in lines[:MAX_INGREDIENT_LINES])
    return [line for line in cleaned if line]


def _reference(nutrition: object) -> dict[str, float | None]:
    """Nährwerte der Seite pro Portion („430 kcal“, „21 g“), nur zum Vergleich."""
    values = nutrition if isinstance(nutrition, dict) else {}
    return {key: _leading_number(values.get(name)) for key, name in REFERENCE_KEYS.items()}


def draft_from_page(cookidoo_id: str, url: str, page: str) -> dict[str, Any]:
    """Rezeptentwurf aus der Seite; Fehler als `RecipePageError`."""
    data = recipe_data(page)
    title = clean_text(data.get("name"))
    if not title:
        raise RecipePageError("Die Rezeptdaten haben keinen Titel.")
    return {
        "source_id": cookidoo_id,
        "title": title,
        "servings": _servings(data.get("recipeYield")),
        "source_url": url,
        "total_time": _duration(data.get("totalTime")),
        "ingredients": _ingredients(data.get("recipeIngredient")),
        "reference": _reference(data.get("nutrition")),
    }
