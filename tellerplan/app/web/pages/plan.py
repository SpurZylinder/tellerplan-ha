"""Seite „Plan“: Tage als Spalten (waagerecht scrollbar) oder als Liste.

Gezeigt wird eine Woche zurück und zwei Wochen voraus; beim Öffnen steht
heute vorn. Rezepte erscheinen nur mit Titel und lassen sich verschieben.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.planner.models import PlanEntry
from modules.planner.service import add_entry, delete_entry, get_entry, move_entry, plan_days
from modules.recipes.service import get_recipe, recipe_summaries
from web.forms import redirect_to
from web.templating import render

router = APIRouter(prefix="/plan")
SessionDep = Annotated[Session, Depends(get_session)]

PAST_DAYS = 7
FUTURE_DAYS = 14
LAYOUTS = ("columns", "list")
LAYOUT_COOKIE = "plan_layout"
LAYOUT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _layout(value: str | None) -> str:
    return value if value in LAYOUTS else LAYOUTS[0]


def _entry_or_404(session: Session, entry_id: int) -> PlanEntry:
    entry = get_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Planeintrag nicht gefunden")
    return entry


def _back_to_plan(request: Request, day: date) -> Response:
    """Zurück zum Plan, direkt zum betroffenen Tag gescrollt."""
    return redirect_to(request, "plan_page", anchor=f"#day-{day.isoformat()}")


@router.get("", response_class=HTMLResponse)
def plan_page(
    request: Request,
    session: SessionDep,
    layout: str | None = None,
    plan_layout: Annotated[str | None, Cookie()] = None,
) -> HTMLResponse:
    current = _layout(layout or plan_layout)
    today = date.today()
    response = render(
        request,
        "plan/week.html",
        tab="plan",
        days=plan_days(session, today - timedelta(days=PAST_DAYS), PAST_DAYS + 1 + FUTURE_DAYS),
        today=today,
        layout=current,
        other_layout=LAYOUTS[1] if current == LAYOUTS[0] else LAYOUTS[0],
    )
    if layout is not None:
        response.set_cookie(
            LAYOUT_COOKIE, current, max_age=LAYOUT_COOKIE_MAX_AGE, samesite="lax", httponly=True
        )
    return response


def _render_add(
    request: Request,
    session: Session,
    day: date,
    recipe_id: int | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return render(
        request,
        "plan/add.html",
        tab="plan",
        day=day,
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
) -> HTMLResponse:
    return _render_add(request, session, day or date.today(), recipe_id)


@router.post("/add", response_model=None)
def plan_create(
    request: Request,
    session: SessionDep,
    day: Annotated[date, Form()],
    recipe_id: Annotated[int | None, Form()] = None,
) -> Response:
    recipe = get_recipe(session, recipe_id) if recipe_id is not None else None
    if recipe is None:
        return _render_add(request, session, day, error="Bitte ein Rezept auswählen.")
    add_entry(session, day, recipe)
    session.commit()
    return _back_to_plan(request, day)


@router.post("/entries/{entry_id}/move")
def plan_move(
    request: Request,
    session: SessionDep,
    entry_id: int,
    day: Annotated[date, Form()],
) -> Response:
    entry = move_entry(session, _entry_or_404(session, entry_id), day)
    session.commit()
    return _back_to_plan(request, entry.day)


@router.post("/entries/{entry_id}/delete")
def plan_delete(request: Request, session: SessionDep, entry_id: int) -> Response:
    entry = _entry_or_404(session, entry_id)
    day = entry.day
    delete_entry(session, entry)
    session.commit()
    return _back_to_plan(request, day)
