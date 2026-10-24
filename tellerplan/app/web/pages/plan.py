"""Seite „Plan“: 1 oder 2 Wochen als Tagesliste; Rezepte mit ihren Standardportionen."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.planner.service import (
    DAYS_PER_WEEK,
    add_entry,
    delete_entry,
    get_entry,
    plan_days,
    week_start,
)
from modules.recipes.service import get_recipe, recipe_summaries
from web.forms import redirect_to
from web.templating import render

router = APIRouter(prefix="/plan")
SessionDep = Annotated[Session, Depends(get_session)]

WEEK_OPTIONS = (1, 2)


def _weeks(value: int) -> int:
    return value if value in WEEK_OPTIONS else WEEK_OPTIONS[0]


def _back_to_plan(request: Request, day: date, weeks: int) -> Response:
    """Zurück zur Woche des Tages, direkt zum Tag gescrollt."""
    return redirect_to(
        request,
        "plan_page",
        anchor=f"#day-{day.isoformat()}",
        query={"start": week_start(day).isoformat(), "weeks": str(_weeks(weeks))},
    )


@router.get("", response_class=HTMLResponse)
def plan_page(
    request: Request,
    session: SessionDep,
    start: date | None = None,
    weeks: int = WEEK_OPTIONS[0],
) -> HTMLResponse:
    weeks = _weeks(weeks)
    first = week_start(start or date.today())
    span = timedelta(days=weeks * DAYS_PER_WEEK)
    return render(
        request,
        "plan/week.html",
        tab="plan",
        days=plan_days(session, first, weeks * DAYS_PER_WEEK),
        first=first,
        weeks=weeks,
        week_options=WEEK_OPTIONS,
        previous=first - span,
        following=first + span,
        today=date.today(),
    )


def _render_add(
    request: Request,
    session: Session,
    day: date,
    weeks: int,
    recipe_id: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return render(
        request,
        "plan/add.html",
        tab="plan",
        day=day,
        weeks=_weeks(weeks),
        recipe_id=recipe_id,
        summaries=recipe_summaries(session),
        error=error,
    )


@router.get("/add", response_class=HTMLResponse)
def plan_add(
    request: Request,
    session: SessionDep,
    day: date | None = None,
    recipe_id: int | None = None,
    weeks: int = WEEK_OPTIONS[0],
) -> HTMLResponse:
    return _render_add(request, session, day or date.today(), weeks, recipe_id)


@router.post("/add", response_model=None)
def plan_create(
    request: Request,
    session: SessionDep,
    day: Annotated[date, Form()],
    recipe_id: Annotated[int | None, Form()] = None,
    weeks: Annotated[int, Form()] = WEEK_OPTIONS[0],
) -> Response:
    recipe = get_recipe(session, recipe_id) if recipe_id is not None else None
    if recipe is None:
        return _render_add(request, session, day, weeks, error="Bitte ein Rezept auswählen.")
    add_entry(session, day, recipe)
    session.commit()
    return _back_to_plan(request, day, weeks)


@router.post("/entries/{entry_id}/delete")
def plan_delete(
    request: Request,
    session: SessionDep,
    entry_id: int,
    weeks: Annotated[int, Form()] = WEEK_OPTIONS[0],
) -> Response:
    entry = get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Planeintrag nicht gefunden")
    day = entry.day
    delete_entry(session, entry)
    session.commit()
    return _back_to_plan(request, day, weeks)
