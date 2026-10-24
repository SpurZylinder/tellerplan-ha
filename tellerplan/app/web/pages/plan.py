"""Seite „Plan“: 1 oder 2 Wochen, Tag × Mahlzeit, Portionen je Eintrag."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.planner.models import PlanEntry
from modules.planner.service import (
    DAYS_PER_WEEK,
    add_entry,
    delete_entry,
    get_entry,
    plan_days,
    set_servings,
    week_start,
)
from modules.recipes.service import get_recipe, recipe_summaries
from web.forms import FormError, parse_number, redirect_to
from web.templating import render

router = APIRouter(prefix="/plan")
SessionDep = Annotated[Session, Depends(get_session)]

WEEK_OPTIONS = (1, 2)
SERVINGS_STEP = 0.5


def _day_anchor(day: date) -> str:
    return f"#day-{day.isoformat()}"


def _entry_or_404(session: Session, entry_id: int) -> PlanEntry:
    entry = get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Planeintrag nicht gefunden")
    return entry


def _back_to_plan(request: Request, day: date) -> Response:
    """Zurück zur Woche des Tages, direkt zum Tag gescrollt."""
    return redirect_to(
        request,
        "plan_page",
        anchor=_day_anchor(day),
        query={"start": week_start(day).isoformat()},
    )


@router.get("", response_class=HTMLResponse)
def plan_page(
    request: Request,
    session: SessionDep,
    start: date | None = None,
    weeks: int = WEEK_OPTIONS[0],
) -> HTMLResponse:
    weeks = weeks if weeks in WEEK_OPTIONS else WEEK_OPTIONS[0]
    first = week_start(start or date.today())
    days = plan_days(session, first, weeks * DAYS_PER_WEEK, request.app.state.settings.meal_names)
    return render(
        request,
        "plan/week.html",
        tab="plan",
        days=days,
        first=first,
        weeks=weeks,
        week_options=WEEK_OPTIONS,
        previous=first - timedelta(days=weeks * DAYS_PER_WEEK),
        following=first + timedelta(days=weeks * DAYS_PER_WEEK),
        today=date.today(),
        step=SERVINGS_STEP,
    )


@router.get("/add", response_class=HTMLResponse)
def plan_add(
    request: Request,
    session: SessionDep,
    day: date | None = None,
    meal: str | None = None,
    recipe_id: int | None = None,
) -> HTMLResponse:
    return render(
        request,
        "plan/add.html",
        tab="plan",
        day=day or date.today(),
        meal=meal,
        recipe_id=recipe_id,
        meal_names=request.app.state.settings.meal_names,
        summaries=recipe_summaries(session),
    )


@router.post("/add", response_model=None)
def plan_create(
    request: Request,
    session: SessionDep,
    day: Annotated[date, Form()],
    meal: Annotated[str, Form()],
    recipe_id: Annotated[int | None, Form()] = None,
    servings: Annotated[str, Form()] = "",
) -> Response:
    meal_names = request.app.state.settings.meal_names
    recipe = get_recipe(session, recipe_id) if recipe_id is not None else None
    try:
        if recipe is None:
            raise FormError("Bitte ein Rezept auswählen.")
        if meal not in meal_names:
            raise FormError("Unbekannte Mahlzeit.")
        amount = parse_number(servings, "Portionen") or recipe.servings
    except FormError as error:
        return render(
            request,
            "plan/add.html",
            tab="plan",
            day=day,
            meal=meal,
            recipe_id=recipe_id,
            meal_names=meal_names,
            summaries=recipe_summaries(session),
            error=str(error),
        )
    add_entry(session, day, meal, recipe, amount)
    session.commit()
    return _back_to_plan(request, day)


@router.post("/entries/{entry_id}/servings")
def plan_servings(
    request: Request,
    session: SessionDep,
    entry_id: int,
    change: Annotated[float, Form()],
) -> Response:
    """Ändert die geplanten Portionen um `change` (± ein Schritt), nie unter einen Schritt."""
    entry = _entry_or_404(session, entry_id)
    set_servings(session, entry, max(SERVINGS_STEP, entry.servings + change))
    session.commit()
    return _back_to_plan(request, entry.day)


@router.post("/entries/{entry_id}/delete")
def plan_delete(request: Request, session: SessionDep, entry_id: int) -> Response:
    entry = _entry_or_404(session, entry_id)
    day = entry.day
    delete_entry(session, entry)
    session.commit()
    return _back_to_plan(request, day)
