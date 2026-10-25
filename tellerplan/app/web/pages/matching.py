"""Seite „Zuordnen“: offene Zutaten einmal je Name zuordnen, fehlende Einheiten ergänzen.

Eine Zuordnung macht das Lebensmittel zum Standardartikel für den Zutatennamen
(z. B. „milch“) und gilt sofort in allen Rezepten und bei künftigen Importen.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.foods.models import Food
from modules.foods.service import get_food, set_unit
from modules.recipes.service import (
    assign_key,
    learned_aliases,
    open_groups,
    refresh_grams,
    unit_gaps,
)
from web.forms import FormError, redirect_to, required_number
from web.templating import render

router = APIRouter(prefix="/matching")
SessionDep = Annotated[Session, Depends(get_session)]

VIEWS = ("open", "units", "learned")
# So viele offene Zutaten zeigt die Seite zunächst; die häufigsten stehen oben.
OPEN_PAGE_SIZE = 30


def _food_or_404(session: Session, food_id: int | None) -> Food:
    food = get_food(session, food_id) if food_id is not None else None
    if food is None:
        raise HTTPException(status_code=404, detail="Lebensmittel nicht gefunden")
    return food


@router.get("", response_class=HTMLResponse)
def matching_page(
    request: Request,
    session: SessionDep,
    view: str = VIEWS[0],
    show_all: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    view = view if view in VIEWS else VIEWS[0]
    groups = open_groups(session)
    gaps = unit_gaps(session)
    return render(
        request,
        "matching.html",
        tab="recipes",
        view=view,
        groups=groups if show_all else groups[:OPEN_PAGE_SIZE],
        open_total=len(groups),
        open_lines=sum(group.lines for group in groups),
        gaps=gaps,
        aliases=learned_aliases(session) if view == "learned" else [],
        error=error,
    )


@router.post("/assign", response_model=None)
def matching_assign(
    request: Request,
    session: SessionDep,
    key: Annotated[str, Form()],
    food_id: Annotated[int | None, Form()] = None,
    view: Annotated[str, Form()] = VIEWS[0],
) -> Response:
    if food_id is None:
        return redirect_to(
            request,
            "matching_page",
            query={"view": view, "error": "Bitte ein Lebensmittel wählen."},
        )
    assign_key(session, key, _food_or_404(session, food_id))
    session.commit()
    return redirect_to(request, "matching_page", query={"view": view})


@router.post("/unit", response_model=None)
def matching_unit(
    request: Request,
    session: SessionDep,
    food_id: Annotated[int, Form()],
    unit: Annotated[str, Form()],
    grams: Annotated[str, Form()] = "",
) -> Response:
    food = _food_or_404(session, food_id)
    try:
        amount = required_number(grams, "Gramm")
        if amount <= 0:
            raise FormError("Gramm müssen größer als 0 sein.")
    except FormError as error:
        return redirect_to(request, "matching_page", query={"view": "units", "error": str(error)})
    set_unit(session, food, unit, amount)
    refresh_grams(session, food)
    session.commit()
    return redirect_to(request, "matching_page", query={"view": "units"})
