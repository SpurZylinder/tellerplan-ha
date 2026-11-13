"""Einkaufsliste: geplante Rezepte zu einer Zutatenliste zusammenfassen.

Jeder Planeintrag zählt mit allen Zutaten des Rezepts, umgerechnet auf seine
geplanten Portionen (4 statt 2 Portionen → doppelte Mengen).
Gleiche Artikel werden je Einheit addiert („2 Stück + 1 Stück“ → „3 Stück“),
Vorratsartikel (Salz, Mehl …) kommen in eine eigene Liste. Keine Nährwerte.

Gesendete Planeinträge werden markiert; ohne `include_sent` zählen nur neue,
damit erneutes Senden Gekauftes nicht wieder auf die Liste setzt.
"""

import logging
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

import clock
from modules.foods.models import FoodSource
from modules.foods.service import short_name
from modules.foods.units import to_base_unit, to_display_unit
from modules.planner.models import PlanEntry
from modules.planner.service import entries_between, mark_shopping_sent
from modules.recipes.models import RecipeIngredient
from modules.recipes.service import resolved_food

logger = logging.getLogger(__name__)

# Quellen von Markenprodukten; deren Name kommt in die Details, nicht in den Artikelnamen
PRODUCT_SOURCES = {FoodSource.REWE, FoodSource.OFF}
WORD_PATTERN = re.compile(r"[^\W\d_]+")


@dataclass
class ShoppingItem:
    """Ein Artikel der Einkaufsliste mit Mengen je Einheit."""

    name: str
    amounts: dict[str, float] = field(default_factory=dict)
    optional: bool = False
    recipes: set[str] = field(default_factory=set)
    # Zugeordnete Markenprodukte, z. B. „ja! Tomatenmark“ beim Artikel „Tomatenmark“
    products: set[str] = field(default_factory=set)

    @property
    def description(self) -> str:
        """Angabe für Bring, z. B. „550 g“, „200 g · ja! Tomatenmark“ oder „1 EL · optional“."""
        amounts = " + ".join(
            _format_amount(quantity, unit) for unit, quantity in self.amounts.items()
        )
        products = ", ".join(sorted(self.products))
        optional = "optional" if self.optional else ""
        return " · ".join(part for part in (amounts, products, optional) if part)


@dataclass(frozen=True)
class ShoppingList:
    first: date
    last: date
    items: list[ShoppingItem]
    pantry: list[ShoppingItem]
    # Planeinträge, deren Zutaten in `items` stecken, und bereits gesendete
    entries: list[PlanEntry]
    already_sent: list[PlanEntry]


def _format_amount(quantity: float, unit: str) -> str:
    quantity, unit = to_display_unit(quantity, unit)
    number = f"{round(quantity, 2):g}".replace(".", ",")
    return f"{number} {unit}".strip()


def _sort_key(item: ShoppingItem) -> str:
    """Alphabetisch mit Umlauten an ihrem Grundbuchstaben („Hähnchen“ vor „Honig“)."""
    decomposed = unicodedata.normalize("NFD", item.name.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _main_word(name: str) -> str:
    """Erstes Wort eines Namens; bei BLS steht dort das Lebensmittel selbst."""
    words = WORD_PATTERN.findall(name.casefold())
    return words[0] if words else ""


def is_pantry(names: Iterable[str], keywords: Sequence[str]) -> bool:
    """Vorratsartikel, wenn das erste Wort eines Namens mit einem Stichwort endet.

    Deutsche Zusammensetzungen tragen das Grundwort hinten: „Meersalz“ und
    „Weizenmehl“ passen zu „salz“ und „mehl“, „Zuckerschote“ aber nicht zu „zucker“.
    Nur das erste Wort zählt, damit „Thunfisch in Öl“ nicht als Öl gilt.
    """
    words = {_main_word(name) for name in names} - {""}
    clean = [keyword.strip().casefold() for keyword in keywords if keyword.strip()]
    return any(word.endswith(keyword) for word in words for keyword in clean)


def _item_name(ingredient: RecipeIngredient) -> str:
    """Grundzutat, sonst Einkaufsname des Lebensmittels, sonst Zutatenname, sonst Originaltext.

    Die Grundzutat zuerst: Bring erkennt „Tomatenmark“ und sortiert es ein,
    „ja! Tomatenmark“ dagegen nicht (Befund K20). Das Produkt steht in den Details.
    """
    if ingredient.base_ingredient is not None:
        return ingredient.base_ingredient.name
    food = resolved_food(ingredient)
    if food is not None:
        return short_name(food)
    return ingredient.name or ingredient.raw_text


def _product(ingredient: RecipeIngredient, item_name: str) -> str | None:
    """Name des Markenprodukts (REWE, Open Food Facts), wenn er mehr sagt als der Artikel."""
    food = resolved_food(ingredient)
    if food is None or food.source not in PRODUCT_SOURCES:
        return None
    return None if food.name.casefold() == item_name.casefold() else food.name


def _names_for_pantry(ingredient: RecipeIngredient) -> list[str]:
    """Namen, deren erstes Wort geprüft wird; Originaltext („1 TL Salz“) Wort für Wort."""
    base = [ingredient.base_ingredient.name] if ingredient.base_ingredient is not None else []
    food = resolved_food(ingredient)
    if food is None:
        own = [ingredient.name] if ingredient.name else ingredient.raw_text.split()
        return base + own
    return [*base, food.name, short_name(food)]


def _amount_key(item: ShoppingItem, unit: str) -> str:
    """Vorhandener Schlüssel derselben Einheit; eigene Einheiten („Zehe“/„zehe“) ohne Groß/klein."""
    return next((key for key in item.amounts if key.casefold() == unit.casefold()), unit)


def _add(
    item: ShoppingItem, ingredient: RecipeIngredient, recipe_title: str, factor: float
) -> None:
    if product := _product(ingredient, item.name):
        item.products.add(product)
    # Menge auch ohne Zuordnung, wenn der Zeilenparser sie erkannt hat („350 g Brokkoliröschen“)
    if ingredient.quantity is not None and (
        resolved_food(ingredient) is not None or ingredient.name
    ):
        quantity, unit = to_base_unit(ingredient.quantity * factor, ingredient.unit or "g")
        key = _amount_key(item, unit)
        item.amounts[key] = item.amounts.get(key, 0) + quantity
    # optional nur, wenn der Artikel in keinem Rezept Pflicht ist
    first = not item.recipes
    item.optional = ingredient.is_optional and (first or item.optional)
    item.recipes.add(recipe_title)


def build_shopping_list(
    session: Session,
    first: date,
    last: date,
    pantry_keywords: Sequence[str],
    include_sent: bool = False,
) -> ShoppingList:
    """Fasst die Planeinträge von `first` bis einschließlich `last` zusammen.

    Ohne `include_sent` nur Einträge, die noch nicht gesendet wurden.
    """
    in_range = entries_between(session, first, last)
    entries = [e for e in in_range if include_sent or e.shopping_sent_at is None]
    items: dict[str, ShoppingItem] = {}
    pantry: dict[str, ShoppingItem] = {}
    for entry in entries:
        recipe = entry.recipe
        factor = entry.servings / recipe.servings if recipe.servings else 1
        for ingredient in recipe.ingredients:
            name = _item_name(ingredient)
            target = pantry if is_pantry(_names_for_pantry(ingredient), pantry_keywords) else items
            item = target.setdefault(name.casefold(), ShoppingItem(name=name))
            _add(item, ingredient, recipe.title, factor)
    return ShoppingList(
        first=first,
        last=last,
        items=sorted(items.values(), key=_sort_key),
        pantry=sorted(pantry.values(), key=_sort_key),
        entries=entries,
        already_sent=[e for e in in_range if e.shopping_sent_at is not None and e not in entries],
    )


class SendError(RuntimeError):
    """Ein Artikel kam nicht in der Liste an; die Meldung nennt den Grund."""


# Trägt einen Artikel ein: Name und Mengenangabe („“ = keine). Fehler kommen als SendError.
# Das Fachmodul kennt so weder Home Assistant noch Bring; die Seite reicht das Senden herein.
AddItem = Callable[[str, str], None]


@dataclass(frozen=True)
class SendResult:
    sent: int
    not_sent: int
    errors: list[str]


# Meldet nach jedem Artikel, wie viele schon gesendet sind (für die Fortschrittsanzeige)
Progress = Callable[[int], None]


def send_items(
    items: Sequence[ShoppingItem], add_item: AddItem, on_progress: Progress | None = None
) -> SendResult:
    """Trägt die Artikel nacheinander ein; ein Fehler bei einem Artikel hält die anderen nicht auf.

    Jeder Artikel wird neu eingetragen. Vorhandene Einträge in Bring werden (noch) nicht
    erweitert, siehe Befund K19 in docs/Version-0.6.0.md.
    """
    sent = 0
    errors: list[str] = []
    for item in items:
        try:
            add_item(item.name, item.description)
        except SendError as error:
            errors.append(f"{item.name}: {error}")
        else:
            sent += 1
        if on_progress is not None:
            on_progress(sent)
    return SendResult(sent=sent, not_sent=len(items) - sent, errors=errors)


def send_shopping_list(
    session: Session,
    shopping: ShoppingList,
    add_item: AddItem,
    target: str,
    on_progress: Progress | None = None,
) -> SendResult:
    """Sendet die Artikel; nur wenn alle ankommen, gelten die Planeinträge als gesendet."""
    result = send_items(shopping.items, add_item, on_progress)
    logger.info(
        "Einkaufsliste: %d Artikel aus %d Rezepten an %s gesendet, %d nicht gesendet",
        result.sent,
        len(shopping.entries),
        target,
        result.not_sent,
    )
    for error in result.errors:
        logger.warning("Einkaufsliste: %s", error)
    if not result.errors:
        mark_shopping_sent(session, shopping.entries, clock.now())
    return result
