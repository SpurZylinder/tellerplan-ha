"""Seiten „Lebensmittel“: suchen, anlegen, bearbeiten, Einheiten pflegen."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.foods.models import Food, FoodSource
from modules.foods.service import (
    FoodInput,
    create_food,
    default_short_name,
    delete_unit,
    get_food,
    search_foods,
    set_shopping_name,
    set_unit,
    update_food,
)
from modules.nutrition.service import standard_units, uses_standard_unit
from web.forms import FormError, clean_text, parse_number, redirect_to, required_number
from web.templating import render

router = APIRouter(prefix="/foods")
SessionDep = Annotated[Session, Depends(get_session)]

NUTRIENT_FIELDS = (
    ("kcal", "kcal"),
    ("protein_g", "Eiweiß (g)"),
    ("fat_g", "Fett (g)"),
    ("carbs_g", "Kohlenhydrate (g)"),
    ("fiber_g", "Ballaststoffe (g)"),
    ("sugar_g", "Zucker (g)"),
    ("salt_g", "Salz (g)"),
)
REQUIRED_NUTRIENTS = {"kcal", "protein_g", "fat_g", "carbs_g"}


def _food_or_404(session: Session, food_id: int) -> Food:
    food = get_food(session, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Lebensmittel nicht gefunden")
    return food


def _editable_food_or_error(session: Session, food_id: int) -> Food:
    """Nur eigene Lebensmittel sind änderbar; BLS-Werte bleiben, wie sie sind."""
    food = _food_or_404(session, food_id)
    if food.source != FoodSource.CUSTOM:
        raise HTTPException(status_code=403, detail="BLS-Lebensmittel sind schreibgeschützt")
    return food


def _nutrient_unit(field: str) -> str:
    """Einheit, die hinter dem Wert stehen darf („60 kcal“, „11 g“)."""
    return "kcal" if field == "kcal" else "g"


async def _food_input(request: Request) -> tuple[FoodInput | None, dict[str, str], str | None]:
    """Liest das Lebensmittel-Formular; liefert Eingabe, Rohwerte und ggf. Fehler."""
    form = await request.form()
    keys = ("name", "brand", *(f for f, _ in NUTRIENT_FIELDS))
    values = {key: str(form.get(key, "")) for key in keys}
    try:
        name = clean_text(values["name"])
        if name is None:
            raise FormError("Name fehlt.")
        numbers = {
            field: (
                required_number(values[field], label, unit=_nutrient_unit(field))
                if field in REQUIRED_NUTRIENTS
                else parse_number(values[field], label, unit=_nutrient_unit(field))
            )
            for field, label in NUTRIENT_FIELDS
        }
    except FormError as error:
        return None, values, str(error)
    return FoodInput(name=name, brand=clean_text(values["brand"]), **numbers), values, None


def _form_values(food: Food) -> dict[str, str]:
    values = {"name": food.name, "brand": food.brand or ""}
    for field, _ in NUTRIENT_FIELDS:
        value = getattr(food, field)
        values[field] = "" if value is None else f"{value:g}".replace(".", ",")
    return values


@router.get("", response_class=HTMLResponse)
def foods_page(request: Request, session: SessionDep, q: str = "") -> HTMLResponse:
    return render(request, "foods/list.html", foods=search_foods(session, q), q=q)


@router.get("/search", response_class=HTMLResponse)
def foods_search(request: Request, session: SessionDep, q: str = "") -> HTMLResponse:
    return render(request, "foods/_results.html", foods=search_foods(session, q))


@router.get("/picker", response_class=HTMLResponse)
def foods_picker(
    request: Request,
    session: SessionDep,
    q: str = "",
    preselect: bool = True,
    optional: bool = False,
) -> HTMLResponse:
    """Auswahlliste für Formulare, z. B. Zutat zum Rezept hinzufügen.

    `preselect=false` wählt nichts vor, z. B. beim Zuordnen für viele Rezepte auf einmal;
    `optional=true` macht die Auswahl nicht zur Pflicht.
    """
    foods = search_foods(session, q) if q.strip() else []
    return render(
        request, "foods/_picker.html", foods=foods, q=q, preselect=preselect, optional=optional
    )


@router.get("/new", response_class=HTMLResponse)
def food_new(request: Request) -> HTMLResponse:
    return render(request, "foods/form.html", food=None, values={}, fields=NUTRIENT_FIELDS)


@router.post("/new", response_model=None)
async def food_create(request: Request, session: SessionDep) -> Response:
    data, values, error = await _food_input(request)
    if data is None:
        return render(
            request,
            "foods/form.html",
            food=None,
            values=values,
            fields=NUTRIENT_FIELDS,
            error=error,
        )
    food = create_food(session, data)
    session.commit()
    return redirect_to(request, "food_detail", food_id=food.id)


@router.get("/{food_id}", response_class=HTMLResponse)
def food_detail(request: Request, session: SessionDep, food_id: int) -> HTMLResponse:
    food = _food_or_404(session, food_id)
    return _render_detail(request, food)


def _render_detail(request: Request, food: Food, unit_error: str | None = None) -> HTMLResponse:
    return render(
        request,
        "foods/detail.html",
        food=food,
        fields=NUTRIENT_FIELDS,
        default_shopping_name=default_short_name(food.name),
        # Standard-Einheiten, für die das Lebensmittel keine eigene Angabe hat
        standard_units=[unit for unit in standard_units() if uses_standard_unit(food, unit.name)],
        unit_error=unit_error,
    )


@router.get("/{food_id}/edit", response_class=HTMLResponse)
def food_edit(request: Request, session: SessionDep, food_id: int) -> HTMLResponse:
    food = _editable_food_or_error(session, food_id)
    return render(
        request,
        "foods/form.html",
        food=food,
        values=_form_values(food),
        fields=NUTRIENT_FIELDS,
    )


@router.post("/{food_id}/edit", response_model=None)
async def food_update(request: Request, session: SessionDep, food_id: int) -> Response:
    food = _editable_food_or_error(session, food_id)
    data, values, error = await _food_input(request)
    if data is None:
        return render(
            request,
            "foods/form.html",
            food=food,
            values=values,
            fields=NUTRIENT_FIELDS,
            error=error,
        )
    update_food(session, food, data)
    session.commit()
    return redirect_to(request, "food_detail", food_id=food.id)


@router.post("/{food_id}/units", response_model=None)
def unit_add(
    request: Request,
    session: SessionDep,
    food_id: int,
    name: Annotated[str, Form()],
    grams: Annotated[str, Form()],
) -> Response:
    food = _food_or_404(session, food_id)
    try:
        unit_name = clean_text(name)
        if unit_name is None:
            raise FormError("Name der Einheit fehlt.")
        set_unit(session, food, unit_name, required_number(grams, "Gramm", unit="g"))
    except FormError as error:
        return _render_detail(request, food, unit_error=str(error))
    session.commit()
    return redirect_to(request, "food_detail", anchor="#units", food_id=food.id)


@router.post("/{food_id}/shopping-name")
def shopping_name_set(
    request: Request,
    session: SessionDep,
    food_id: int,
    shopping_name: Annotated[str, Form()] = "",
) -> Response:
    food = _food_or_404(session, food_id)
    set_shopping_name(session, food, shopping_name)
    session.commit()
    return redirect_to(request, "food_detail", anchor="#shopping", food_id=food.id)


@router.post("/{food_id}/units/{unit_id}/delete")
def unit_delete(request: Request, session: SessionDep, food_id: int, unit_id: int) -> Response:
    food = _food_or_404(session, food_id)
    delete_unit(session, food, unit_id)
    session.commit()
    return redirect_to(request, "food_detail", anchor="#units", food_id=food.id)
