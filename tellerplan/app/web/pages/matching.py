"""Seiten „Zuordnen“ und „Grundzutaten“.

Zuordnen: Zutatennamen einmal einer Grundzutat zuordnen (gilt für alle Rezepte und
künftige Importe), Grundzutaten ohne Standardprodukt versorgen, fehlende Einheiten
ergänzen. Grundzutaten: Standardprodukt, weitere Produkte, Namen, „ohne Nährwerte“.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.foods.models import Food
from modules.foods.service import get_food, set_unit
from modules.recipes.matching import (
    add_product,
    base_names,
    base_usages,
    create_base,
    get_base,
    link_name,
    open_groups,
    remove_product,
    rename_base,
    set_default_product,
    set_no_nutrients,
    unit_gaps,
)
from modules.recipes.models import BaseIngredient
from web.forms import FormError, clean_text, redirect_to, required_number
from web.templating import render

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]

VIEWS = ("open", "products", "units")
# So viele offene Namen zeigt die Seite zunächst; die häufigsten stehen oben.
OPEN_PAGE_SIZE = 30


def _food_or_404(session: Session, food_id: int | None) -> Food:
    food = get_food(session, food_id) if food_id is not None else None
    if food is None:
        raise HTTPException(status_code=404, detail="Lebensmittel nicht gefunden")
    return food


def _base_or_404(session: Session, base_id: int) -> BaseIngredient:
    base = get_base(session, base_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Grundzutat nicht gefunden")
    return base


def _back(request: Request, view: str, error: str | None = None) -> Response:
    query = {"view": view if view in VIEWS else VIEWS[0]}
    if error:
        query["error"] = error
    return redirect_to(request, "matching_page", query=query)


@router.get("/matching", response_class=HTMLResponse)
def matching_page(
    request: Request,
    session: SessionDep,
    view: str = VIEWS[0],
    show_all: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    view = view if view in VIEWS else VIEWS[0]
    groups = open_groups(session)
    without_product = [
        usage
        for usage in base_usages(session)
        if usage.lines and usage.base.default_food is None and not usage.base.no_nutrients
    ]
    gaps = unit_gaps(session)
    return render(
        request,
        "matching.html",
        tab="recipes",
        view=view,
        groups=groups if show_all else groups[:OPEN_PAGE_SIZE],
        open_total=len(groups),
        open_lines=sum(group.lines for group in groups),
        without_product=without_product,
        gaps=gaps,
        base_names=base_names(session),
        error=error,
    )


@router.post("/matching/assign", response_model=None)
def matching_assign(
    request: Request,
    session: SessionDep,
    name: Annotated[str, Form()],
    base_name: Annotated[str, Form()] = "",
    food_id: Annotated[int | None, Form()] = None,
    no_nutrients: Annotated[bool, Form()] = False,
) -> Response:
    """Name → Grundzutat (wird bei Bedarf angelegt), optional mit Produkt oder „ohne Nährwerte“."""
    base = create_base(session, clean_text(base_name) or name, no_nutrients=no_nutrients)
    if no_nutrients:
        set_no_nutrients(session, base, True)
    if food_id is not None:
        food = _food_or_404(session, food_id)
        if base.default_food is None:
            set_default_product(session, base, food)
        else:
            add_product(session, base, food)
    link_name(session, name, base)
    session.commit()
    return _back(request, "open")


@router.post("/matching/unit", response_model=None)
def matching_unit(
    request: Request,
    session: SessionDep,
    food_id: Annotated[int, Form()],
    unit: Annotated[str, Form()],
    grams: Annotated[str, Form()] = "",
) -> Response:
    food = _food_or_404(session, food_id)
    try:
        amount = required_number(grams, "Gramm", unit="g")
        if amount <= 0:
            raise FormError("Gramm müssen größer als 0 sein.")
    except FormError as error:
        return _back(request, "units", str(error))
    set_unit(session, food, unit, amount)
    session.commit()
    return _back(request, "units")


# --- Grundzutaten ---------------------------------------------------------


@router.get("/bases", response_class=HTMLResponse)
def bases_page(request: Request, session: SessionDep) -> HTMLResponse:
    return render(request, "bases/list.html", tab="recipes", usages=base_usages(session))


@router.get("/bases/{base_id}", response_class=HTMLResponse)
def base_detail(
    request: Request, session: SessionDep, base_id: int, error: str | None = None
) -> HTMLResponse:
    base = _base_or_404(session, base_id)
    usage = next(u for u in base_usages(session) if u.base.id == base.id)
    return render(request, "bases/detail.html", tab="recipes", base=base, usage=usage, error=error)


@router.post("/bases/{base_id}/default", response_model=None)
def base_set_default(
    request: Request,
    session: SessionDep,
    base_id: int,
    food_id: Annotated[int | None, Form()] = None,
    back: Annotated[str, Form()] = "",
) -> Response:
    """Standardprodukt setzen; gilt sofort für alle Zeilen ohne eigene Produktwahl."""
    base = _base_or_404(session, base_id)
    if food_id is None:
        if back == "matching":
            return _back(request, "products", "Bitte ein Produkt wählen.")
        return redirect_to(
            request, "base_detail", query={"error": "Bitte ein Produkt wählen."}, base_id=base.id
        )
    set_default_product(session, base, _food_or_404(session, food_id))
    session.commit()
    if back == "matching":
        return _back(request, "products")
    return redirect_to(request, "base_detail", base_id=base.id)


@router.post("/bases/{base_id}/products/{food_id}/remove", response_model=None)
def base_remove_product(
    request: Request, session: SessionDep, base_id: int, food_id: int
) -> Response:
    base = _base_or_404(session, base_id)
    remove_product(session, base, _food_or_404(session, food_id))
    session.commit()
    return redirect_to(request, "base_detail", base_id=base.id)


@router.post("/bases/{base_id}/settings", response_model=None)
def base_settings(
    request: Request,
    session: SessionDep,
    base_id: int,
    name: Annotated[str, Form()] = "",
    no_nutrients: Annotated[bool, Form()] = False,
    back: Annotated[str, Form()] = "",
) -> Response:
    base = _base_or_404(session, base_id)
    new_name = clean_text(name)
    if new_name and new_name != base.name:
        rename_base(session, base, new_name)
    set_no_nutrients(session, base, no_nutrients)
    session.commit()
    if back == "matching":
        return _back(request, "products")
    return redirect_to(request, "base_detail", base_id=base.id)
