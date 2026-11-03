"""Platzhalter aus „Meine Woche“ mit der Rezeptseite von Cookidoo füllen.

Verbindet `cookidoo` (Abruf), `importers` (Seite → Entwurf → Import) und `planner`
(Planeinträge auf die neuen Standardportionen). Das geht nur hier, weil `importers`
den Plan nicht kennen darf (Regel 7).

Ablauf: Seiten nacheinander abrufen (gedrosselt, höchstens `MAX_PAGES_PER_RUN`), den
Titel der Seite mit dem des Platzhalters vergleichen, dann alle Entwürfe auf einmal
importieren. Der Aufrufer schreibt fest; Seiten werden vor jedem Schreibzugriff geholt,
damit die Datenbank währenddessen nicht gesperrt ist.

Was nicht klappt, bleibt Platzhalter und kommt beim nächsten Mal wieder dran:
- Seite fehlt oder hat keine Rezeptdaten → dieses Rezept überspringen, weiter.
- Titel passt nicht → überspringen (womöglich eine andere Seite), der Grund wird gezeigt.
- Cookidoo nicht erreichbar → abbrechen, damit nicht jede Seite ihre Zeitüberschreitung
  abwartet.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from cookidoo import CookidooError, RecipePageMissingError
from modules.importers.cookidoo_page import RecipePageError, draft_from_page, same_title
from modules.importers.service import ImportResult, import_drafts
from modules.planner.service import adopt_standard_servings
from modules.recipes.models import COOKIDOO_SOURCE, Recipe
from modules.recipes.service import get_recipe

# Höflich zu Cookidoo und kurz genug, dass der Ingress-Proxy nicht abbricht
MAX_PAGES_PER_RUN = 10
PAGE_DELAY_SECONDS = 1.0

logger = logging.getLogger(__name__)


class RecipePages(Protocol):
    """Was das Füllen von Cookidoo braucht; erfüllt von `cookidoo.CookidooAccount`."""

    def recipe_page(self, recipe_id: str) -> str: ...


@dataclass(frozen=True)
class Skipped:
    """Ein Platzhalter, der Platzhalter bleibt, mit Grund."""

    title: str
    reason: str


@dataclass
class FillResult:
    filled: int = 0
    # Planeinträge, die dabei die neuen Standardportionen bekommen haben
    adopted: int = 0
    skipped: list[Skipped] = field(default_factory=list)


def adopt_servings(session: Session, result: ImportResult) -> int:
    """Gefüllte Platzhalter: Planeinträge auf die neuen Standardportionen setzen."""
    adopted = 0
    for item in result.filled:
        recipe = get_recipe(session, item.recipe_id)
        if recipe is not None and recipe.servings != item.old_servings:
            adopted += adopt_standard_servings(session, recipe, item.old_servings)
    return adopted


def fill_placeholders(
    session: Session, pages: RecipePages, recipes: Sequence[Recipe]
) -> FillResult:
    """Füllt die Platzhalter unter `recipes`; andere Rezepte bleiben unberührt."""
    placeholders = [recipe for recipe in recipes if recipe.is_placeholder and recipe.source_id]
    result = FillResult()
    drafts: list[dict[str, Any]] = []
    for number, recipe in enumerate(placeholders):
        if number >= MAX_PAGES_PER_RUN:
            result.skipped.append(Skipped(recipe.title, "Für diesmal genug Seiten geladen."))
            continue
        if number:
            time.sleep(PAGE_DELAY_SECONDS)
        try:
            draft = _draft(pages, recipe)
        except (RecipePageMissingError, RecipePageError) as error:
            result.skipped.append(Skipped(recipe.title, str(error)))
            continue
        except CookidooError as error:
            result.skipped += [Skipped(rest.title, str(error)) for rest in placeholders[number:]]
            break
        drafts.append(draft)
    if not drafts:
        return result
    imported = import_drafts(session, COOKIDOO_SOURCE, drafts)
    result.filled = len(imported.filled)
    result.adopted = adopt_servings(session, imported)
    logger.info("%d Platzhalter aus Cookidoo gefüllt", result.filled)
    return result


def _draft(pages: RecipePages, recipe: Recipe) -> dict[str, Any]:
    """Entwurf aus der Rezeptseite; Fehler als `CookidooError` oder `RecipePageError`."""
    assert recipe.source_id is not None
    page = pages.recipe_page(recipe.source_id)
    draft = draft_from_page(recipe.source_id, recipe.source_url or "", page)
    if not same_title(draft["title"], recipe.title):
        raise RecipePageError(f"Titel passt nicht, die Rezeptseite heißt „{draft['title']}“.")
    return draft
