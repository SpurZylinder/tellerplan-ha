"""Seiten „Rezepte“: Ranking-Liste, Detail, Anlegen/Bearbeiten, Zutaten."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.recipes.models import Recipe
from modules.recipes.service import (
    IngredientInput,
    RecipeInput,
    add_ingredient,
    create_recipe,
    delete_recipe,
    get_recipe,
    list_categories,
    recipe_summaries,
    remove_ingredient,
    summarize,
    toggle_favorite,
    update_recipe,
)
from web.forms import (
    COMMON_UNITS,
    FormError,
    clean_text,
    parse_number,
    redirect_to,
    required_number,
)
from web.templating import render

router = APIRouter(prefix="/recipes")
SessionDep = Annotated[Session, Depends(get_session)]


def _recipe_or_404(session: Session, recipe_id: int) -> Recipe:
    recipe = get_recipe(session, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Rezept nicht gefunden")
    return recipe


async def _recipe_input(request: Request) -> tuple[RecipeInput | None, dict[str, str], str | None]:
    form = await request.form()
    keys = ("title", "servings", "category", "source_url", "note")
    values = {key: str(form.get(key, "")) for key in keys}
    try:
        title = clean_text(values["title"])
        if title is None:
            raise FormError("Titel fehlt.")
        servings = required_number(values["servings"], "Portionen")
        if servings <= 0:
            raise FormError("Portionen müssen größer als 0 sein.")
        data = RecipeInput(
            title=title,
            servings=servings,
            category=clean_text(values["category"]),
            source_url=clean_text(values["source_url"]),
            note=clean_text(values["note"]),
        )
    except FormError as error:
        return None, values, str(error)
    return data, values, None


def _form_values(recipe: Recipe) -> dict[str, str]:
    return {
        "title": recipe.title,
        "servings": f"{recipe.servings:g}".replace(".", ","),
        "category": recipe.category or "",
        "source_url": recipe.source_url or "",
        "note": recipe.note or "",
    }


def _render_form(
    request: Request,
    session: Session,
    recipe: Recipe | None,
    values: dict[str, str],
    error: str | None = None,
) -> HTMLResponse:
    return render(
        request,
        "recipes/form.html",
        tab="recipes",
        recipe=recipe,
        values=values,
        categories=list_categories(session),
        error=error,
    )


def _render_detail(
    request: Request, recipe: Recipe, ingredient_error: str | None = None
) -> HTMLResponse:
    return render(
        request,
        "recipes/detail.html",
        tab="recipes",
        summary=summarize(recipe),
        units=COMMON_UNITS,
        ingredient_error=ingredient_error,
    )


@router.get("", response_class=HTMLResponse)
def recipes_page(request: Request, session: SessionDep) -> HTMLResponse:
    return render(
        request,
        "recipes/list.html",
        tab="recipes",
        summaries=recipe_summaries(session),
        categories=list_categories(session),
        protein_weight=request.app.state.settings.ranking_protein_weight,
    )


@router.get("/new", response_class=HTMLResponse)
def recipe_new(request: Request, session: SessionDep) -> HTMLResponse:
    return _render_form(request, session, None, {"servings": "2"})


@router.post("/new", response_model=None)
async def recipe_create(request: Request, session: SessionDep) -> Response:
    data, values, error = await _recipe_input(request)
    if data is None:
        return _render_form(request, session, None, values, error)
    recipe = create_recipe(session, data)
    session.commit()
    return redirect_to(request, "recipe_detail", recipe_id=recipe.id)


@router.get("/{recipe_id}", response_class=HTMLResponse)
def recipe_detail(request: Request, session: SessionDep, recipe_id: int) -> HTMLResponse:
    return _render_detail(request, _recipe_or_404(session, recipe_id))


@router.get("/{recipe_id}/edit", response_class=HTMLResponse)
def recipe_edit(request: Request, session: SessionDep, recipe_id: int) -> HTMLResponse:
    recipe = _recipe_or_404(session, recipe_id)
    return _render_form(request, session, recipe, _form_values(recipe))


@router.post("/{recipe_id}/edit", response_model=None)
async def recipe_update(request: Request, session: SessionDep, recipe_id: int) -> Response:
    recipe = _recipe_or_404(session, recipe_id)
    data, values, error = await _recipe_input(request)
    if data is None:
        return _render_form(request, session, recipe, values, error)
    update_recipe(session, recipe, data)
    session.commit()
    return redirect_to(request, "recipe_detail", recipe_id=recipe.id)


@router.post("/{recipe_id}/delete")
def recipe_delete(request: Request, session: SessionDep, recipe_id: int) -> Response:
    delete_recipe(session, _recipe_or_404(session, recipe_id))
    session.commit()
    return redirect_to(request, "recipes_page")


@router.post("/{recipe_id}/favorite", response_class=HTMLResponse)
def recipe_favorite(request: Request, session: SessionDep, recipe_id: int) -> HTMLResponse:
    """HTMX: schaltet den Favoriten-Stern um und liefert den neuen Stern."""
    recipe = toggle_favorite(session, _recipe_or_404(session, recipe_id))
    session.commit()
    return render(request, "recipes/_star.html", recipe=recipe)


@router.post("/{recipe_id}/ingredients", response_model=None)
def ingredient_add(
    request: Request,
    session: SessionDep,
    recipe_id: int,
    quantity: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
    food_id: Annotated[int | None, Form()] = None,
    is_optional: Annotated[bool, Form()] = False,
) -> Response:
    recipe = _recipe_or_404(session, recipe_id)
    try:
        if food_id is None:
            raise FormError("Bitte ein Lebensmittel auswählen.")
        amount = parse_number(quantity, "Menge")
        data = IngredientInput(
            food_id=food_id, quantity=amount, unit=clean_text(unit), is_optional=is_optional
        )
    except FormError as error:
        return _render_detail(request, recipe, ingredient_error=str(error))
    add_ingredient(session, recipe, data)
    session.commit()
    return redirect_to(request, "recipe_detail", anchor="#ingredients", recipe_id=recipe.id)


@router.post("/{recipe_id}/ingredients/{ingredient_id}/delete")
def ingredient_delete(
    request: Request, session: SessionDep, recipe_id: int, ingredient_id: int
) -> Response:
    recipe = _recipe_or_404(session, recipe_id)
    remove_ingredient(session, recipe, ingredient_id)
    session.commit()
    return redirect_to(request, "recipe_detail", anchor="#ingredients", recipe_id=recipe.id)
