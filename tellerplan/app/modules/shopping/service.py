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
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

import clock
from modules.foods.models import FoodSource
from modules.foods.service import short_name
from modules.foods.units import to_base_unit, to_display_unit
from modules.planner.models import PlanEntry
from modules.planner.service import entries_between, mark_shopping_sent
from modules.recipes.models import RecipeIngredient
from modules.recipes.service import alias_key, resolved_food

logger = logging.getLogger(__name__)

# Quellen von Markenprodukten; deren Name kommt in die Details, nicht in den Artikelnamen
PRODUCT_SOURCES = {FoodSource.REWE, FoodSource.OFF}
# Packungsgröße am Ende eines Produktnamens, z. B. „250g“, „1 kg“, „0,5 l“
PACKAGE_SIZE = re.compile(r"\s+\d+(?:[.,]\d+)?\s*(?:g|kg|ml|l)\.?$", re.IGNORECASE)
# Eine Menge in einer Angabe von Tellerplan, z. B. „200 g“, „2,5 Prise“, „3“
AMOUNT = re.compile(r"^(\d+(?:,\d+)?)(?:\s+(\S.*))?$")
OPTIONAL = "optional"
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
    pantry_keywords: tuple[str, ...] = ()


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
    if food is not None and food.source in PRODUCT_SOURCES and not food.shopping_name:
        # Ohne Grundzutat: wenigstens ohne Packungsgröße („Cherry Romatomaten 250g“)
        return PACKAGE_SIZE.sub("", food.name).strip() or food.name
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
    items, pantry = _collect(entries, pantry_keywords)
    return ShoppingList(
        first=first,
        last=last,
        items=items,
        pantry=pantry,
        entries=entries,
        already_sent=[e for e in in_range if e.shopping_sent_at is not None and e not in entries],
        pantry_keywords=tuple(pantry_keywords),
    )


def _collect(
    entries: Sequence[PlanEntry], pantry_keywords: Sequence[str]
) -> tuple[list[ShoppingItem], list[ShoppingItem]]:
    """Artikel und Vorrat aus den Zutaten der Planeinträge, je Name zusammengefasst."""
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
    return sorted(items.values(), key=_sort_key), sorted(pantry.values(), key=_sort_key)


class SendError(RuntimeError):
    """Liste nicht erreichbar oder Artikel abgelehnt; die Meldung nennt den Grund."""


@dataclass(frozen=True)
class ListItem:
    """Ein offener Eintrag der Einkaufsliste (z. B. in Bring)."""

    uid: str
    name: str
    description: str


class TodoList(Protocol):
    """Was das Senden von der Einkaufsliste braucht; Fehler kommen als SendError.

    Das Fachmodul kennt so weder Home Assistant noch Bring; die Seite reicht die Liste herein.
    """

    def open_items(self) -> list[ListItem]: ...

    def add(self, name: str, description: str) -> None: ...

    # `item` ist die uid des Eintrags, ersatzweise sein Name
    def update(self, item: str, description: str) -> None: ...


# Meldet nach jedem Artikel, wie viele schon geschrieben sind (für die Fortschrittsanzeige)
Progress = Callable[[int], None]


@dataclass(frozen=True)
class SendResult:
    added: int
    updated: int
    failed: int
    errors: list[str]
    recipes_sent: int
    recipes_open: int

    @property
    def written(self) -> int:
        return self.added + self.updated


def planned_writes(shopping: ShoppingList) -> int:
    """So viele Artikel schreibt das Senden: je Rezept seine Artikel (für den Fortschritt)."""
    return sum(len(_collect([entry], shopping.pantry_keywords)[0]) for entry in shopping.entries)


def _parse_amounts(text: str) -> dict[str, float] | None:
    """Mengen aus einer Angabe wie „200 g + 1 Dose“; None, wenn sie nicht von Tellerplan stammt."""
    amounts: dict[str, float] = {}
    for part in text.split(" + "):
        match = AMOUNT.match(part.strip())
        if match is None:
            return None
        quantity = float(match.group(1).replace(",", "."))
        unit = match.group(2) or ""
        if unit:
            quantity, unit = to_base_unit(quantity, unit)
        key = next((k for k in amounts if k.casefold() == unit.casefold()), unit)
        amounts[key] = amounts.get(key, 0) + quantity
    return amounts


def merge_description(existing: str, item: ShoppingItem) -> str:
    """Angabe eines vorhandenen Eintrags, ergänzt um den Artikel (Befund K19).

    Stammt die Angabe von Tellerplan („200 g · ja! Tomatenmark“), werden Mengen addiert und
    Produkte zusammengeführt. Sonst (z. B. von Hand in Bring geändert) wird angehängt.
    """
    if not existing.strip():
        return item.description
    first, *rest = existing.split(" · ")
    amounts = _parse_amounts(first)
    if amounts is None:
        return f"{existing} + {item.description}" if item.description else existing
    merged = ShoppingItem(
        name=item.name,
        amounts=amounts,
        optional=OPTIONAL in rest and item.optional,
        products=set(item.products)
        | {product for part in rest if part != OPTIONAL for product in part.split(", ")},
    )
    for unit, quantity in item.amounts.items():
        key = _amount_key(merged, unit)
        merged.amounts[key] = merged.amounts.get(key, 0) + quantity
    return merged.description


def _with_uid(todo: TodoList, entry: ListItem) -> ListItem:
    """Eintrag mit uid; ein eben angelegter hat noch keine und wird in der Liste nachgeschlagen.

    Über den Namen allein träfe ein Update bei gleichnamigen Einträgen den ersten, z. B.
    das „Oliven“ ohne Angaben statt der eben angelegten „Oliven 4 EL“.
    """
    if entry.uid:
        return entry
    candidates = [
        found
        for found in todo.open_items()
        if found.name == entry.name and found.description == entry.description and found.uid
    ]
    return candidates[-1] if candidates else entry


def send_shopping_list(
    session: Session,
    shopping: ShoppingList,
    todo: TodoList,
    target: str,
    on_progress: Progress | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> SendResult:
    """Sendet Rezept für Rezept; vorhandene Einträge werden erweitert, neue angelegt.

    Ein Eintrag ohne Angaben (z. B. von Hand „Oliven“) bleibt unberührt; der Artikel kommt als
    eigener Eintrag dazu, weitere Rezepte ergänzen dann diesen.

    Ein Rezept gilt als gesendet, sobald alle seine Artikel angekommen sind; `checkpoint`
    hält das sofort fest. Bricht etwas ab, wiederholt der nächste Lauf nur offene Rezepte.
    Ist die Liste nicht lesbar, wird nichts gesendet: lieber nichts als doppelte Einträge.
    """
    try:
        known = {alias_key(entry.name): entry for entry in reversed(todo.open_items())}
    except SendError as error:
        logger.warning("Einkaufsliste: %s nicht lesbar: %s", target, error)
        return SendResult(0, 0, 0, [f"Liste nicht lesbar: {error}"], 0, len(shopping.entries))
    added = updated = 0
    errors: list[str] = []
    recipes_sent = 0
    for entry in shopping.entries:
        complete = True
        for item in _collect([entry], shopping.pantry_keywords)[0]:
            key = alias_key(item.name)
            try:
                current = known.get(key)
                # Ein Eintrag ohne Angaben ist offen gehalten („Oliven“ – vielleicht andere);
                # ergänzt wird nur ein spezifischer Eintrag, sonst kommt ein eigener dazu
                if current is None or not current.description.strip():
                    todo.add(item.name, item.description)
                    known[key] = ListItem("", item.name, item.description)
                    added += 1
                else:
                    description = merge_description(current.description, item)
                    if description != current.description:
                        current = _with_uid(todo, current)
                        todo.update(current.uid or current.name, description)
                    known[key] = replace(current, description=description)
                    updated += 1
            except SendError as error:
                complete = False
                errors.append(f"{item.name}: {error}")
            if on_progress is not None:
                on_progress(added + updated)
        if complete:
            mark_shopping_sent(session, [entry], clock.now())
            recipes_sent += 1
            if checkpoint is not None:
                checkpoint()
    result = SendResult(
        added, updated, len(errors), errors, recipes_sent, len(shopping.entries) - recipes_sent
    )
    logger.info(
        "Einkaufsliste: %d Rezepte an %s gesendet (%d Artikel neu, %d ergänzt), %d offen",
        recipes_sent,
        target,
        added,
        updated,
        result.recipes_open,
    )
    for error in errors:
        logger.warning("Einkaufsliste: %s", error)
    return result
