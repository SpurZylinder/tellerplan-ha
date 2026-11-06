"""Seiten „Zuordnen“ und „Grundzutaten“.

Zuordnen: Zutatennamen einmal einer Grundzutat zuordnen (gilt für alle Rezepte und
künftige Importe), Grundzutaten ohne Standardprodukt versorgen, fehlende Einheiten
ergänzen. Grundzutaten: Standardprodukt, weitere Produkte, Namen, „ohne Nährwerte“,
Zusammenführen doppelter Grundzutaten.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.foods.models import Food
from modules.foods.service import get_food, set_unit
from modules.recipes.matching import (
    BaseNameTakenError,
    add_product,
    all_bases,
    base_names,
    base_usages,
    create_base,
    find_base,
    get_base,
    link_name,
    merge_bases,
    open_groups,
    remove_product,
    rename_base,
    set_default_product,
    set_no_nutrients,
    similar_bases,
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


def _back(
    request: Request,
    view: str,
    error: str | None = None,
    position: int | None = None,
    show_all: bool = False,
) -> Response:
    """Zurück zur Zuordnen-Seite, an die Stelle der bearbeiteten Karte.

    Ist die Karte erledigt, rückt die nächste an ihre Position; bei einem Fehler
    steht dort dieselbe Karte mit der Meldung.
    """
    query = {"view": view if view in VIEWS else VIEWS[0]}
    if show_all:
        query["show_all"] = "true"
    if error:
        query["error"] = error
        if position is not None:
            query["error_at"] = str(position)
    anchor = f"#card-{position}" if position is not None else ""
    return redirect_to(request, "matching_page", anchor=anchor, query=query)


@router.get("/matching", response_class=HTMLResponse)
def matching_page(
    request: Request,
    session: SessionDep,
    view: str = VIEWS[0],
    show_all: bool = False,
    error: str | None = None,
    error_at: int | None = None,
) -> HTMLResponse:
    view = view if view in VIEWS else VIEWS[0]
    groups = open_groups(session)
    without_product = [
        usage
        for usage in base_usages(session)
        if usage.lines and usage.base.default_food is None and not usage.base.no_nutrients
    ]
    gaps = unit_gaps(session)
    shown = groups if show_all else groups[:OPEN_PAGE_SIZE]
    bases = all_bases(session)
    return render(
        request,
        "matching.html",
        tab="recipes",
        view=view,
        groups=shown,
        suggestions={group.key: similar_bases(bases, group.name) for group in shown},
        open_total=len(groups),
        open_lines=sum(group.lines for group in groups),
        without_product=without_product,
        gaps=gaps,
        base_names=base_names(session),
        show_all=show_all,
        error=error,
        error_at=error_at,
    )


@router.post("/matching/assign", response_model=None)
def matching_assign(
    request: Request,
    session: SessionDep,
    name: Annotated[str, Form()],
    base_name: Annotated[str, Form()] = "",
    suggestion: Annotated[str, Form()] = "",
    food_id: Annotated[int | None, Form()] = None,
    no_nutrients: Annotated[bool, Form()] = False,
    position: Annotated[int | None, Form()] = None,
    show_all: Annotated[bool, Form()] = False,
) -> Response:
    """Name → Grundzutat (wird bei Bedarf angelegt), optional mit Produkt oder „ohne Nährwerte“.

    Ein Tipp auf einen Vorschlag (`suggestion`) geht vor dem Textfeld. Bleibt das Textfeld
    leer, aber ist ein Produkt oder „ohne Nährwerte“ gewählt, heißt die Grundzutat wie der Name.
    """
    chosen = clean_text(suggestion) or clean_text(base_name)
    if chosen is None and (food_id is not None or no_nutrients):
        chosen = clean_text(name)
    if chosen is None:
        message = "Bitte eine Grundzutat wählen oder einen Namen eingeben."
        return _back(request, "open", message, position, show_all)
    base = create_base(session, chosen, no_nutrients=no_nutrients)
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
    return _back(request, "open", position=position, show_all=show_all)


@router.post("/matching/unit", response_model=None)
def matching_unit(
    request: Request,
    session: SessionDep,
    food_id: Annotated[int, Form()],
    unit: Annotated[str, Form()],
    grams: Annotated[str, Form()] = "",
    position: Annotated[int | None, Form()] = None,
) -> Response:
    food = _food_or_404(session, food_id)
    try:
        amount = required_number(grams, "Gramm", unit="g")
        if amount <= 0:
            raise FormError("Gramm müssen größer als 0 sein.")
    except FormError as error:
        return _back(request, "units", str(error), position)
    set_unit(session, food, unit, amount)
    session.commit()
    return _back(request, "units", position=position)


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
    return render(
        request,
        "bases/detail.html",
        tab="recipes",
        base=base,
        usage=usage,
        similar=similar_bases(all_bases(session), base.name, exclude=base),
        base_names=base_names(session),
        error=error,
    )


@router.post("/bases/{base_id}/merge", response_model=None)
def base_merge(
    request: Request,
    session: SessionDep,
    base_id: int,
    target_name: Annotated[str, Form()] = "",
) -> Response:
    """Diese Grundzutat in eine andere aufgehen lassen; weiter geht es bei der anderen."""
    base = _base_or_404(session, base_id)
    target = find_base(session, target_name) if clean_text(target_name) else None
    if target is None or target.id == base.id:
        message = "Bitte eine andere, bestehende Grundzutat wählen."
        return redirect_to(request, "base_detail", query={"error": message}, base_id=base.id)
    merge_bases(session, base, target)
    session.commit()
    return redirect_to(request, "base_detail", base_id=target.id)


@router.post("/bases/{base_id}/default", response_model=None)
def base_set_default(
    request: Request,
    session: SessionDep,
    base_id: int,
    food_id: Annotated[int | None, Form()] = None,
    back: Annotated[str, Form()] = "",
    position: Annotated[int | None, Form()] = None,
) -> Response:
    """Standardprodukt setzen; gilt sofort für alle Zeilen ohne eigene Produktwahl."""
    base = _base_or_404(session, base_id)
    if food_id is None:
        if back == "matching":
            return _back(request, "products", "Bitte ein Produkt wählen.", position)
        return redirect_to(
            request, "base_detail", query={"error": "Bitte ein Produkt wählen."}, base_id=base.id
        )
    set_default_product(session, base, _food_or_404(session, food_id))
    session.commit()
    if back == "matching":
        return _back(request, "products", position=position)
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
    position: Annotated[int | None, Form()] = None,
) -> Response:
    base = _base_or_404(session, base_id)
    new_name = clean_text(name)
    if new_name and new_name != base.name:
        try:
            rename_base(session, base, new_name)
        except BaseNameTakenError as error:
            if back == "matching":
                return _back(request, "products", str(error), position)
            return redirect_to(request, "base_detail", query={"error": str(error)}, base_id=base.id)
    set_no_nutrients(session, base, no_nutrients)
    session.commit()
    if back == "matching":
        return _back(request, "products", position=position)
    return redirect_to(request, "base_detail", base_id=base.id)
