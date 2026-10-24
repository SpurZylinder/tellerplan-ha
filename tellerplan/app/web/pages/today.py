"""Seite „Heute“: Tages-Dashboard. Nur hier wird eingetragen, was gegessen wurde."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.diary.service import (
    UnknownUnitError,
    day_log,
    delete_entry,
    get_entry,
    log_food,
    log_recipe,
    planned_for_day,
)
from modules.foods.service import get_food
from modules.nutrition.service import Nutrients
from modules.planner.service import get_entry as get_plan_entry
from modules.recipes.service import get_recipe, recipe_summaries
from settings import Settings
from web.forms import COMMON_UNITS, FormError, clean_text, redirect_to, required_number
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
    query = {} if day == date.today() else {"day": day.isoformat()}
    anchor = f"#meal-{meal}" if meal else ""
    return redirect_to(request, "today_page", anchor=anchor, query=query)


def _meal_or_error(meal: str, settings: Settings) -> str:
    if meal not in settings.meal_names:
        raise FormError("Bitte eine Mahlzeit wählen.")
    return meal


@router.get("/", response_class=HTMLResponse)
def today_page(request: Request, session: SessionDep, day: date | None = None) -> HTMLResponse:
    settings = request.app.state.settings
    day = day or date.today()
    log = day_log(session, day, settings.meal_names)
    return render(
        request,
        "today.html",
        tab="today",
        log=log,
        gauge=KcalGauge(eaten=log.total.kcal, limit=settings.daily_kcal_limit),
        macros=_macro_bars(log.total, settings),
        planned=planned_for_day(session, day),
        is_today=day == date.today(),
        previous=day - timedelta(days=1),
        following=day + timedelta(days=1),
    )


def _render_add(
    request: Request,
    session: Session,
    *,
    day: date,
    mode: str,
    meal: str | None = None,
    recipe_id: int | None = None,
    plan_entry_id: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return render(
        request,
        "diary/add.html",
        tab="today",
        day=day,
        mode=mode if mode in ADD_MODES else ADD_MODES[0],
        meal=meal,
        recipe_id=recipe_id,
        plan_entry_id=plan_entry_id,
        meal_names=request.app.state.settings.meal_names,
        summaries=recipe_summaries(session) if mode == "recipe" else [],
        units=COMMON_UNITS,
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
) -> HTMLResponse:
    return _render_add(
        request,
        session,
        day=day or date.today(),
        mode=mode,
        meal=meal,
        recipe_id=recipe_id,
        plan_entry_id=plan_entry_id,
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


@router.post("/diary/entries/{entry_id}/delete")
def diary_delete(request: Request, session: SessionDep, entry_id: int) -> Response:
    entry = get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    day, meal = entry.day, entry.meal
    delete_entry(session, entry)
    session.commit()
    return _back_to_day(request, day, meal)
