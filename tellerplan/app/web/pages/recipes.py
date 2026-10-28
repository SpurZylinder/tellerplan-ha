"""Seiten „Rezepte“: Ranking-Liste, Detail, Anlegen/Bearbeiten, Zutaten."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from db import get_session
from modules.foods.service import get_food
from modules.recipes.matching import base_names, choose_product, create_base, set_line_base
from modules.recipes.models import Recipe, RecipeIngredient
from modules.recipes.service import (
    IngredientInput,
    RecipeInput,
    add_ingredient,
    create_recipe,
    delete_recipe,
    get_ingredient,
    get_recipe,
    ingredient_label,
    instruction_steps,
    line_breakdown,
    list_categories,
    recipe_summaries,
    remove_ingredient,
    resolved_food,
    summarize,
    toggle_favorite,
    update_line,
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


def _category_choices(request: Request, current: str | None = None) -> list[str]:
    """Kategorien aus den Einstellungen; eine ältere Kategorie des Rezepts bleibt wählbar."""
    configured = list(request.app.state.settings.recipe_categories)
    return configured if not current or current in configured else [*configured, current]


def _ordered_categories(request: Request, used: list[str]) -> list[str]:
    """Vorkommende Kategorien in der Reihenfolge der Einstellungen, unbekannte am Ende."""
    configured = request.app.state.settings.recipe_categories
    return [c for c in configured if c in used] + [c for c in used if c not in configured]


async def _recipe_input(
    request: Request, recipe: Recipe | None
) -> tuple[RecipeInput | None, dict[str, str], str | None]:
    form = await request.form()
    keys = ("title", "servings", "category", "source_url", "note", "instructions")
    values = {key: str(form.get(key, "")) for key in keys}
    try:
        title = clean_text(values["title"])
        if title is None:
            raise FormError("Titel fehlt.")
        category = clean_text(values["category"])
        if category and category not in _category_choices(request, recipe and recipe.category):
            raise FormError("Bitte eine Kategorie aus der Liste wählen.")
        source_url = clean_text(values["source_url"])
        if source_url and not source_url.startswith(("https://", "http://")):
            raise FormError("Der Link muss mit https:// beginnen.")
        servings = required_number(values["servings"], "Portionen")
        if servings <= 0:
            raise FormError("Portionen müssen größer als 0 sein.")
        data = RecipeInput(
            title=title,
            servings=servings,
            category=category,
            source_url=source_url,
            note=clean_text(values["note"]),
            instructions=clean_text(values["instructions"]),
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
        "instructions": recipe.instructions or "",
    }


def _render_form(
    request: Request,
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
        categories=_category_choices(request, recipe and recipe.category),
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
        breakdown=line_breakdown(recipe),
        units=COMMON_UNITS,
        ingredient_error=ingredient_error,
    )


@router.get("", response_class=HTMLResponse)
def recipes_page(request: Request, session: SessionDep) -> HTMLResponse:
    summaries = recipe_summaries(session)
    return render(
        request,
        "recipes/list.html",
        tab="recipes",
        summaries=summaries,
        open_lines=sum(
            1
            for summary in summaries
            for line in summary.recipe.ingredients
            if line.food is None and line.base_ingredient is None
        ),
        categories=_ordered_categories(request, list_categories(session)),
        protein_weight=request.app.state.settings.ranking_protein_weight,
    )


@router.get("/new", response_class=HTMLResponse)
def recipe_new(request: Request) -> HTMLResponse:
    return _render_form(request, None, {"servings": "2"})


@router.post("/new", response_model=None)
async def recipe_create(request: Request, session: SessionDep) -> Response:
    data, values, error = await _recipe_input(request, None)
    if data is None:
        return _render_form(request, None, values, error)
    recipe = create_recipe(session, data)
    session.commit()
    return redirect_to(request, "recipe_detail", recipe_id=recipe.id)


@router.get("/{recipe_id}", response_class=HTMLResponse)
def recipe_detail(request: Request, session: SessionDep, recipe_id: int) -> HTMLResponse:
    return _render_detail(request, _recipe_or_404(session, recipe_id))


@router.get("/{recipe_id}/cook", response_class=HTMLResponse)
def recipe_cook(request: Request, session: SessionDep, recipe_id: int) -> HTMLResponse:
    """Kochansicht: Schritte, daneben die Zutaten zum Mitlesen."""
    recipe = _recipe_or_404(session, recipe_id)
    return render(
        request,
        "recipes/cook.html",
        tab="recipes",
        recipe=recipe,
        lines=[(ingredient_label(i), i) for i in recipe.ingredients],
        steps=instruction_steps(recipe),
    )


@router.get("/{recipe_id}/edit", response_class=HTMLResponse)
def recipe_edit(request: Request, session: SessionDep, recipe_id: int) -> HTMLResponse:
    recipe = _recipe_or_404(session, recipe_id)
    return _render_form(request, recipe, _form_values(recipe))


@router.post("/{recipe_id}/edit", response_model=None)
async def recipe_update(request: Request, session: SessionDep, recipe_id: int) -> Response:
    recipe = _recipe_or_404(session, recipe_id)
    data, values, error = await _recipe_input(request, recipe)
    if data is None:
        return _render_form(request, recipe, values, error)
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


def _ingredient_or_404(recipe: Recipe, ingredient_id: int) -> RecipeIngredient:
    ingredient = get_ingredient(recipe, ingredient_id)
    if ingredient is None:
        raise HTTPException(status_code=404, detail="Zutat nicht gefunden")
    return ingredient


def _render_line(
    request: Request,
    session: Session,
    recipe: Recipe,
    ingredient: RecipeIngredient,
    error: str | None = None,
) -> HTMLResponse:
    return render(
        request,
        "recipes/line.html",
        tab="recipes",
        recipe=recipe,
        ingredient=ingredient,
        label=ingredient_label(ingredient),
        resolved=resolved_food(ingredient),
        base_names=base_names(session),
        units=COMMON_UNITS,
        error=error,
    )


@router.get("/{recipe_id}/ingredients/{ingredient_id}", response_class=HTMLResponse)
def ingredient_edit(
    request: Request, session: SessionDep, recipe_id: int, ingredient_id: int
) -> HTMLResponse:
    """Eine Zeile: Name, Menge, Einheit, Grundzutat und Produkt nur für dieses Rezept."""
    recipe = _recipe_or_404(session, recipe_id)
    return _render_line(request, session, recipe, _ingredient_or_404(recipe, ingredient_id))


@router.post("/{recipe_id}/ingredients/{ingredient_id}", response_model=None)
def ingredient_update(
    request: Request,
    session: SessionDep,
    recipe_id: int,
    ingredient_id: int,
    name: Annotated[str, Form()] = "",
    quantity: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
    is_optional: Annotated[bool, Form()] = False,
    base_name: Annotated[str, Form()] = "",
    food_id: Annotated[str, Form()] = "",
) -> Response:
    recipe = _recipe_or_404(session, recipe_id)
    ingredient = _ingredient_or_404(recipe, ingredient_id)
    try:
        line_name = clean_text(name)
        if line_name is None:
            raise FormError("Der Name der Zutat fehlt.")
        amount = parse_number(quantity, "Menge")
    except FormError as error:
        return _render_line(request, session, recipe, ingredient, error=str(error))

    base_text = clean_text(base_name)
    set_line_base(session, ingredient, create_base(session, base_text) if base_text else None)
    food = get_food(session, int(food_id)) if food_id.strip().isdigit() else None
    if ingredient.base_ingredient is None and food is None:
        food = ingredient.food  # Zeile von Hand ohne Grundzutat behält ihr Lebensmittel
    choose_product(session, ingredient, food)
    update_line(session, ingredient, line_name, amount, clean_text(unit), is_optional)
    session.commit()
    return redirect_to(request, "recipe_detail", anchor="#ingredients", recipe_id=recipe.id)
