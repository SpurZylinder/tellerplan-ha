"""Seite „Heute“: Tages-Dashboard. Nur hier wird eingetragen, was gegessen wurde."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

import clock
from db import get_session
from modules.diary.models import DiaryEntry
from modules.diary.service import (
    UnknownUnitError,
    change_amount,
    change_servings,
    day_log,
    delete_entry,
    get_entry,
    log_food,
    log_recipe,
    planned_for_day,
    recipes_eaten,
)
from modules.foods.service import get_food
from modules.nutrition.service import Nutrients, StandardUnit, unit_choices
from modules.planner.service import get_entry as get_plan_entry
from modules.recipes.service import RecipeSummary, get_recipe, recipe_summaries
from settings import Settings
from web.forms import FormError, clean_text, redirect_to, required_number
from web.templating import render

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]

ADD_MODES = ("recipe", "food")
SERVINGS_STEP = 0.25
FULL_PERCENT = 100.0


@dataclass(frozen=True)
class KcalGauge:
    """Werte für den Halbkreis: Anteil des Limits, Rest oder Überschreitung."""

    eaten: float
    limit: float

    @property
    def percent(self) -> float:
        return min(FULL_PERCENT, self.eaten / self.limit * FULL_PERCENT) if self.limit else 0

    @property
    def remaining(self) -> float:
        return self.limit - self.eaten

    @property
    def over_limit(self) -> bool:
        return self.eaten > self.limit


@dataclass(frozen=True)
class MacroBar:
    label: str
    css_class: str
    value: float
    goal: float

    @property
    def percent(self) -> float:
        return min(FULL_PERCENT, self.value / self.goal * FULL_PERCENT) if self.goal else 0


def _macro_bars(total: Nutrients, settings: Settings) -> list[MacroBar]:
    return [
        MacroBar("Eiweiß", "p", total.protein_g, settings.protein_goal_g),
        MacroBar("Fett", "d", total.fat_g, settings.fat_goal_g),
        MacroBar("Kohlenhydrate", "d", total.carbs_g, settings.carbs_goal_g),
    ]


def _back_to_day(request: Request, day: date, meal: str | None = None) -> Response:
    query = {} if day == clock.today() else {"day": day.isoformat()}
    anchor = f"#meal-{meal}" if meal else ""
    return redirect_to(request, "today_page", anchor=anchor, query=query)


def _meal_or_error(meal: str, settings: Settings) -> str:
    if meal not in settings.meal_names:
        raise FormError("Bitte eine Mahlzeit wählen.")
    return meal


def _entry_units(session: Session, entries: list[DiaryEntry]) -> dict[int, list[StandardUnit]]:
    """Einheiten zur Auswahl je Lebensmitteleintrag, fürs Ändern der Menge."""
    units = {}
    for entry in entries:
        if entry.servings is None:
            food = get_food(session, entry.food_id) if entry.food_id is not None else None
            choices = unit_choices(food) if food is not None else []
            if entry.unit not in {choice.name for choice in choices}:
                # Ohne Lebensmittel bleibt nur die eingetragene Einheit
                grams = (entry.grams or 0) / entry.quantity if entry.quantity else 0
                choices.insert(0, StandardUnit(entry.unit or "g", grams))
            units[entry.id] = choices
    return units


def _render_today(
    request: Request,
    session: Session,
    day: date,
    edit_id: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    settings = request.app.state.settings
    log = day_log(session, day, settings.meal_names)
    return render(
        request,
        "today.html",
        tab="today",
        log=log,
        gauge=KcalGauge(eaten=log.total.kcal, limit=settings.daily_kcal_limit),
        macros=_macro_bars(log.total, settings),
        planned=planned_for_day(session, day),
        planned_meal=settings.plan_default_meal,
        entry_units=_entry_units(session, [e for meal in log.meals for e in meal.entries]),
        edit_id=edit_id,
        error=error,
        step=SERVINGS_STEP,
        is_today=day == clock.today(),
        previous=day - timedelta(days=1),
        following=day + timedelta(days=1),
    )


@router.get("/", response_class=HTMLResponse)
def today_page(request: Request, session: SessionDep, day: date | None = None) -> HTMLResponse:
    return _render_today(request, session, day or clock.today())


@dataclass(frozen=True)
class RecipeChoices:
    """Rezeptauswahl beim Eintragen: Vorschläge von gestern oben, darunter der Rest."""

    suggestions: list[tuple[RecipeSummary, float]]
    others: list[RecipeSummary]
    # Kategorien, auf die vorgefiltert ist; leer = alle Rezepte
    categories: list[str]
    # Ohne Filter gäbe es mehr Rezepte („Alle Rezepte“ anbieten)
    filterable: bool


def _recipe_choices(
    session: Session,
    settings: Settings,
    day: date,
    meal: str | None,
    recipe_id: int | None,
    show_all: bool,
) -> RecipeChoices:
    summaries = recipe_summaries(session)
    by_id = {summary.recipe.id: summary for summary in summaries}
    suggestions = []
    if meal in settings.suggest_yesterday_meals:
        eaten = recipes_eaten(session, day - timedelta(days=1), meal)
        suggestions = [(by_id[e.recipe_id], e.servings or 1) for e in eaten if e.recipe_id in by_id]
    suggested = {summary.recipe.id for summary, _ in suggestions}
    others = [summary for summary in summaries if summary.recipe.id not in suggested]

    categories = settings.categories_for_meal(meal)
    matching = {summary.recipe.id for summary in summaries if summary.recipe.category in categories}
    # Ein vorgegebenes Rezept (z. B. aus dem Plan) muss in der Auswahl stehen
    chosen_hidden = recipe_id is not None and recipe_id not in matching | suggested
    if show_all or not matching or chosen_hidden:
        return RecipeChoices(suggestions, others, [], filterable=bool(matching))
    filtered = [summary for summary in others if summary.recipe.id in matching]
    return RecipeChoices(suggestions, filtered, categories, filterable=True)


def _render_add(
    request: Request,
    session: Session,
    *,
    day: date,
    mode: str,
    meal: str | None = None,
    recipe_id: int | None = None,
    plan_entry_id: int | None = None,
    show_all: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    settings = request.app.state.settings
    mode = mode if mode in ADD_MODES else ADD_MODES[0]
    choices = (
        _recipe_choices(session, settings, day, meal, recipe_id, show_all)
        if mode == "recipe"
        else None
    )
    servings: float = 1
    if choices and choices.suggestions and recipe_id is None:
        first, servings = choices.suggestions[0]
        recipe_id = first.recipe.id
    return render(
        request,
        "diary/add.html",
        tab="today",
        day=day,
        mode=mode,
        meal=meal,
        recipe_id=recipe_id,
        plan_entry_id=plan_entry_id,
        meal_names=settings.meal_names,
        choices=choices,
        servings=servings,
        units=unit_choices(None),
        step=SERVINGS_STEP,
        error=error,
    )


@router.get("/diary/add", response_class=HTMLResponse)
def diary_add(
    request: Request,
    session: SessionDep,
    day: date | None = None,
    meal: str | None = None,
    mode: str = ADD_MODES[0],
    recipe_id: int | None = None,
    plan_entry_id: int | None = None,
    show_all: Annotated[bool, Query(alias="all")] = False,
) -> HTMLResponse:
    return _render_add(
        request,
        session,
        day=day or clock.today(),
        mode=mode,
        meal=meal,
        recipe_id=recipe_id,
        plan_entry_id=plan_entry_id,
        show_all=show_all,
    )


@router.post("/diary/recipe", response_model=None)
def diary_log_recipe(
    request: Request,
    session: SessionDep,
    day: Annotated[date, Form()],
    meal: Annotated[str, Form()] = "",
    recipe_id: Annotated[int | None, Form()] = None,
    servings: Annotated[str, Form()] = "",
    plan_entry_id: Annotated[int | None, Form()] = None,
) -> Response:
    recipe = get_recipe(session, recipe_id) if recipe_id is not None else None
    try:
        meal = _meal_or_error(meal, request.app.state.settings)
        if recipe is None:
            raise FormError("Bitte ein Rezept auswählen.")
        amount = required_number(servings, "Portionen")
        if amount <= 0:
            raise FormError("Portionen müssen größer als 0 sein.")
    except FormError as error:
        return _render_add(
            request,
            session,
            day=day,
            mode="recipe",
            meal=meal,
            recipe_id=recipe_id,
            plan_entry_id=plan_entry_id,
            error=str(error),
        )
    plan_entry = get_plan_entry(session, plan_entry_id) if plan_entry_id else None
    log_recipe(session, day, meal, recipe, amount, plan_entry)
    session.commit()
    return _back_to_day(request, day, meal)


@router.post("/diary/food", response_model=None)
def diary_log_food(
    request: Request,
    session: SessionDep,
    day: Annotated[date, Form()],
    meal: Annotated[str, Form()] = "",
    food_id: Annotated[int | None, Form()] = None,
    quantity: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
) -> Response:
    food = get_food(session, food_id) if food_id is not None else None
    try:
        meal = _meal_or_error(meal, request.app.state.settings)
        if food is None:
            raise FormError("Bitte ein Lebensmittel auswählen.")
        amount = required_number(quantity, "Menge")
        log_food(session, day, meal, food, amount, clean_text(unit))
    except (FormError, UnknownUnitError) as error:
        return _render_add(request, session, day=day, mode="food", meal=meal, error=str(error))
    session.commit()
    return _back_to_day(request, day, meal)


@router.get("/diary/units", response_class=HTMLResponse)
def diary_units(request: Request, session: SessionDep, food_id: int | None = None) -> HTMLResponse:
    """Einheiten-Auswahl passend zum gewählten Lebensmittel (lädt per HTMX nach)."""
    food = get_food(session, food_id) if food_id is not None else None
    return render(request, "diary/_unit_select.html", units=unit_choices(food), selected="g")


def _entry_or_404(session: Session, entry_id: int) -> DiaryEntry:
    entry = get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return entry


@router.post("/diary/entries/{entry_id}", response_model=None)
def diary_change(
    request: Request,
    session: SessionDep,
    entry_id: int,
    servings: Annotated[str, Form()] = "",
    quantity: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
) -> Response:
    """Portionen bzw. Menge eines Eintrags ändern."""
    entry = _entry_or_404(session, entry_id)
    try:
        if entry.servings is not None:
            amount = required_number(servings, "Portionen")
            if amount <= 0:
                raise FormError("Portionen müssen größer als 0 sein.")
            change_servings(session, entry, amount)
        else:
            amount = required_number(quantity, "Menge")
            if amount <= 0:
                raise FormError("Die Menge muss größer als 0 sein.")
            food = get_food(session, entry.food_id) if entry.food_id is not None else None
            change_amount(session, entry, food, amount, clean_text(unit))
    except (FormError, UnknownUnitError) as error:
        session.rollback()
        return _render_today(request, session, entry.day, edit_id=entry.id, error=str(error))
    session.commit()
    return _back_to_day(request, entry.day, entry.meal)


@router.post("/diary/entries/{entry_id}/delete")
def diary_delete(request: Request, session: SessionDep, entry_id: int) -> Response:
    entry = _entry_or_404(session, entry_id)
    day, meal = entry.day, entry.meal
    delete_entry(session, entry)
    session.commit()
    return _back_to_day(request, day, meal)
