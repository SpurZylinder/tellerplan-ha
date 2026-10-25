"""Einkaufsliste: geplante Rezepte zu einer Zutatenliste zusammenfassen.

Jeder Planeintrag zählt mit allen Zutaten des Rezepts (Standardportionen).
Gleiche Artikel werden je Einheit addiert („2 Stück + 1 Stück“ → „3 Stück“),
Vorratsartikel (Salz, Mehl …) kommen in eine eigene Liste. Keine Nährwerte.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from modules.foods.models import Food
from modules.planner.service import entries_between
from modules.recipes.models import RecipeIngredient
from supervisor import SupervisorError, call_service

# Zustandswörter am Ende von BLS-Namen, die beim Einkaufen nicht helfen („Broccoli roh“)
STATE_WORDS = ("roh", "reif")
# Ab hier folgen in BLS-Namen Gehaltsangaben: „Parmesan mind. 30 % Fett“, „Vollmilch 3,5 %“;
# andere Zahlen bleiben („Weizenmehl Type 405“)
DETAILS_START = re.compile(r"\s(?:mind\.|max\.|ca\.|<|>|\d+(?:,\d+)?\s?%)")
WORD_PATTERN = re.compile(r"[^\W\d_]+")


@dataclass
class ShoppingItem:
    """Ein Artikel der Einkaufsliste mit Mengen je Einheit."""

    name: str
    amounts: dict[str, float] = field(default_factory=dict)
    optional: bool = False
    recipes: set[str] = field(default_factory=set)

    @property
    def description(self) -> str:
        """Mengenangabe für Bring, z. B. „550 g“, „1 Dose + 200 g“ oder „1 EL · optional“."""
        amounts = " + ".join(
            _format_amount(quantity, unit) for unit, quantity in self.amounts.items()
        )
        return " · ".join(part for part in (amounts, "optional" if self.optional else "") if part)


@dataclass(frozen=True)
class ShoppingList:
    first: date
    last: date
    items: list[ShoppingItem]
    pantry: list[ShoppingItem]


def _format_amount(quantity: float, unit: str) -> str:
    number = f"{round(quantity, 2):g}".replace(".", ",")
    return f"{number} {unit}".strip()


def default_shopping_name(food_name: str) -> str:
    """Kurzname aus dem Lebensmittelnamen: „Karotte/Möhre, roh“ → „Karotte“."""
    name = food_name.split(", ", 1)[0].split("/", 1)[0]
    words = DETAILS_START.split(name, maxsplit=1)[0].split()
    while len(words) > 1 and words[-1].casefold() in STATE_WORDS:
        words.pop()
    return " ".join(words)


def _sort_key(item: ShoppingItem) -> str:
    """Alphabetisch mit Umlauten an ihrem Grundbuchstaben („Hähnchen“ vor „Honig“)."""
    decomposed = unicodedata.normalize("NFD", item.name.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def shopping_name(food: Food) -> str:
    return food.shopping_name or default_shopping_name(food.name)


def is_pantry(names: Iterable[str], keywords: Sequence[str]) -> bool:
    """Vorratsartikel, wenn ein Wort mit einem Stichwort endet.

    Deutsche Zusammensetzungen tragen das Grundwort hinten: „Meersalz“ und
    „Weizenmehl“ passen zu „salz“ und „mehl“, „Zuckerschote“ aber nicht zu „zucker“.
    """
    words = {word for name in names for word in WORD_PATTERN.findall(name.casefold())}
    clean = [keyword.strip().casefold() for keyword in keywords if keyword.strip()]
    return any(word.endswith(keyword) for word in words for keyword in clean)


def _item_name(ingredient: RecipeIngredient) -> str:
    return shopping_name(ingredient.food) if ingredient.food else ingredient.raw_text


def _names_for_pantry(ingredient: RecipeIngredient) -> list[str]:
    if ingredient.food is None:
        return [ingredient.raw_text]
    return [ingredient.food.name, shopping_name(ingredient.food)]


def _add(item: ShoppingItem, ingredient: RecipeIngredient, recipe_title: str) -> None:
    if ingredient.food is not None and ingredient.quantity is not None:
        unit = ingredient.unit or "g"
        item.amounts[unit] = item.amounts.get(unit, 0) + ingredient.quantity
    # optional nur, wenn der Artikel in keinem Rezept Pflicht ist
    first = not item.recipes
    item.optional = ingredient.is_optional and (first or item.optional)
    item.recipes.add(recipe_title)


def build_shopping_list(
    session: Session, first: date, days: int, pantry_keywords: Sequence[str]
) -> ShoppingList:
    """Fasst alle Planeinträge von `first` an über `days` Tage zusammen."""
    last = first + timedelta(days=days - 1)
    items: dict[str, ShoppingItem] = {}
    pantry: dict[str, ShoppingItem] = {}
    for entry in entries_between(session, first, last):
        for ingredient in entry.recipe.ingredients:
            name = _item_name(ingredient)
            target = pantry if is_pantry(_names_for_pantry(ingredient), pantry_keywords) else items
            item = target.setdefault(name.casefold(), ShoppingItem(name=name))
            _add(item, ingredient, entry.recipe.title)
    return ShoppingList(
        first=first,
        last=last,
        items=sorted(items.values(), key=_sort_key),
        pantry=sorted(pantry.values(), key=_sort_key),
    )


@dataclass(frozen=True)
class SendResult:
    sent: int
    errors: list[str]


def send_to_todo_list(items: Sequence[ShoppingItem], entity_id: str, token: str) -> SendResult:
    """Trägt jeden Artikel per `todo.add_item` in eine To-do-Liste ein (z. B. Bring).

    Bring führt gleichnamige Artikel zusammen; erneutes Senden aktualisiert also
    nur die Mengenangabe.
    """
    errors = []
    for item in items:
        data = {"entity_id": entity_id, "item": item.name}
        if item.description:
            data["description"] = item.description
        try:
            call_service("todo", "add_item", data, token)
        except SupervisorError as error:
            errors.append(f"{item.name}: {error}")
    return SendResult(sent=len(items) - len(errors), errors=errors)
