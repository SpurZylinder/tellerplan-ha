"""Seite „Plan“: Tage als Spalten (waagerecht scrollbar) oder als Liste.

Gezeigt werden drei Tage zurück und zwei Wochen voraus; beim Öffnen steht
heute vorn. Rezepte erscheinen nur mit Titel und lassen sich verschieben.

Mit Cookidoo verbunden, gleicht „Cookidoo abgleichen“ den Plan von heute bis zum
Planende mit „Meine Woche“ ab: erst eine Vorschau, dann „Übernehmen“.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

import clock
from cookidoo import CookidooError
from db import get_session
from modules.planner.cookidoo_apply import SyncPreview, apply, preview
from modules.planner.cookidoo_sync import (
    INTERNAL,
    AddToCookidoo,
    AddToTellerplan,
    Change,
    DeleteFromTellerplan,
    MoveInCookidoo,
    MoveInTellerplan,
    RemoveFromCookidoo,
)
from modules.planner.models import PlanEntry
from modules.planner.service import add_entry, delete_entry, get_entry, move_entry, plan_days
from modules.recipes.service import get_recipe, recipe_summaries, summarize
from web.forms import FormError, parse_number, redirect_to
from web.pages.options import cookidoo_account
from web.templating import format_day, render

router = APIRouter(prefix="/plan")
SessionDep = Annotated[Session, Depends(get_session)]

PAST_DAYS = 3
FUTURE_DAYS = 14
LAYOUTS = ("columns", "list")
LAYOUT_COOKIE = "plan_layout"
LAYOUT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
SERVINGS_STEP = 0.25


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
    synced: int | None = None,
    failed: int = 0,
    sync_error: str | None = None,
) -> HTMLResponse:
    current = _layout(layout or plan_layout)
    today = clock.today()
    response = render(
        request,
        "plan/week.html",
        tab="plan",
        days=plan_days(session, today - timedelta(days=PAST_DAYS), PAST_DAYS + 1 + FUTURE_DAYS),
        today=today,
        cookidoo_connected=cookidoo_account(request.app.state.settings).username() is not None,
        synced=synced,
        failed=failed,
        sync_error=sync_error,
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
    fixed: bool = False,
    servings: str = "",
    error: str | None = None,
) -> HTMLResponse:
    """Einplanen: mit festem Rezept (vom Rezept aus) nur Tag und Portionen, sonst mit Auswahl."""
    recipe = get_recipe(session, recipe_id) if fixed and recipe_id is not None else None
    return render(
        request,
        "plan/add.html",
        tab="recipes" if recipe else "plan",
        day=day,
        recipe_id=recipe_id,
        chosen=summarize(recipe) if recipe else None,
        summaries=[] if recipe else recipe_summaries(session),
        servings=servings or (f"{recipe.servings:g}" if recipe else ""),
        step=SERVINGS_STEP,
        error=error,
    )


def _servings(text: str) -> float | None:
    """Geplante Portionen; leer bedeutet: Standardportionen des Rezepts."""
    servings = parse_number(text, "Portionen")
    if servings is not None and servings <= 0:
        raise FormError("Portionen müssen größer als 0 sein.")
    return servings


@router.get("/add", response_class=HTMLResponse)
def plan_add(
    request: Request,
    session: SessionDep,
    day: date | None = None,
    recipe_id: int | None = None,
) -> HTMLResponse:
    fixed = recipe_id is not None
    return _render_add(request, session, day or clock.today(), recipe_id, fixed=fixed)


@router.post("/add", response_model=None)
def plan_create(
    request: Request,
    session: SessionDep,
    day: Annotated[date, Form()],
    recipe_id: Annotated[int | None, Form()] = None,
    servings: Annotated[str, Form()] = "",
    fixed: Annotated[bool, Form()] = False,
) -> Response:
    recipe = get_recipe(session, recipe_id) if recipe_id is not None else None
    try:
        if recipe is None:
            raise FormError("Bitte ein Rezept auswählen.")
        planned = _servings(servings)
    except FormError as error:
        return _render_add(
            request, session, day, recipe_id, fixed=fixed, servings=servings, error=str(error)
        )
    add_entry(session, day, recipe, planned)
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


# --- Abgleich mit „Meine Woche“ ---------------------------------------------------------


@dataclass(frozen=True)
class ChangeLine:
    """Eine Zeile der Vorschau, z. B. „Linsen-Dal: Mo 02.11. → Mi 04.11.“."""

    group: str
    text: str


GROUPS = ("In Tellerplan", "Neue Platzhalter", "In Cookidoo")


def _sync_range() -> tuple[date, date]:
    """Von heute bis zum Ende des Plans; vergangene Tage bleiben unberührt."""
    today = clock.today()
    return today, today + timedelta(days=FUTURE_DAYS)


def _describe(change: Change, shown: SyncPreview) -> ChangeLine | None:
    def title(entry_id: int) -> str:
        return shown.titles.get(entry_id, "Rezept")

    def name(cookidoo_id: str) -> str:
        return shown.names.get(cookidoo_id, cookidoo_id)

    match change:
        case AddToTellerplan(day=day, name=recipe_name, placeholder=True):
            return ChangeLine(GROUPS[1], f"{recipe_name}: neu am {format_day(day)}")
        case AddToTellerplan(day=day, name=recipe_name):
            return ChangeLine(GROUPS[0], f"{recipe_name}: neu am {format_day(day)}")
        case MoveInTellerplan(entry_id=entry_id, from_day=from_day, to_day=to_day):
            text = f"{title(entry_id)}: {format_day(from_day)} → {format_day(to_day)}"
            return ChangeLine(GROUPS[0], text)
        case DeleteFromTellerplan(entry_id=entry_id, day=day):
            text = f"{title(entry_id)}: am {format_day(day)} entfernen (in Cookidoo nicht mehr da)"
            return ChangeLine(GROUPS[0], text)
        case AddToCookidoo(entry_id=entry_id, day=day):
            return ChangeLine(GROUPS[2], f"{title(entry_id)}: am {format_day(day)} einplanen")
        case MoveInCookidoo(entry_id=entry_id, from_day=from_day, to_day=to_day):
            text = f"{title(entry_id)}: {format_day(from_day)} → {format_day(to_day)}"
            return ChangeLine(GROUPS[2], text)
        case RemoveFromCookidoo(day=day, cookidoo_id=cookidoo_id):
            return ChangeLine(GROUPS[2], f"{name(cookidoo_id)}: am {format_day(day)} entfernen")
    return None


def _render_sync(
    request: Request,
    shown: SyncPreview | None,
    error: str | None = None,
    changed_meanwhile: bool = False,
) -> HTMLResponse:
    lines = [line for c in shown.plan.visible if (line := _describe(c, shown))] if shown else []
    first, last = _sync_range()
    return render(
        request,
        "plan/cookidoo.html",
        tab="plan",
        groups=[(group, [line.text for line in lines if line.group == group]) for group in GROUPS],
        fingerprint=shown.fingerprint if shown else "",
        in_sync=shown is not None and shown.plan.in_sync,
        first=first,
        last=last,
        error=error,
        changed_meanwhile=changed_meanwhile,
    )


@router.get("/cookidoo", response_class=HTMLResponse)
def cookidoo_preview(request: Request, session: SessionDep) -> HTMLResponse:
    """Vorschau: liest „Meine Woche“ und zeigt, was sich ändern würde; schreibt nichts."""
    try:
        shown = preview(session, cookidoo_account(request.app.state.settings), *_sync_range())
    except CookidooError as error:
        return _render_sync(request, None, error=str(error))
    return _render_sync(request, shown)


@router.post("/cookidoo", response_model=None)
def cookidoo_apply(
    request: Request, session: SessionDep, fingerprint: Annotated[str, Form()] = ""
) -> Response:
    """Übernehmen – nur, wenn Cookidoo seit der Vorschau unverändert ist."""
    try:
        result = apply(
            session, cookidoo_account(request.app.state.settings), *_sync_range(), fingerprint
        )
    except CookidooError as error:
        session.rollback()
        return _render_sync(request, None, error=str(error))
    if isinstance(result, SyncPreview):
        return _render_sync(request, result, changed_meanwhile=True)
    session.commit()
    query = {"synced": str(sum(1 for c in result.applied if not isinstance(c, INTERNAL)))}
    if result.failed:
        query["failed"] = str(len(result.failed))
    if result.error:
        query["sync_error"] = result.error
    return redirect_to(request, "plan_page", query=query)
