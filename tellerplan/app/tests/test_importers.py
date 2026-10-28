"""Import von Rezeptentwürfen: Anlegen, erneuter Import, Standardartikel, Upload-Seite."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from factories import make_food
from modules.importers.service import ImportFormatError, import_document
from modules.recipes.matching import create_base, link_name, set_default_product
from modules.recipes.models import Recipe
from modules.recipes.service import (
    effective_grams,
    find_recipe_by_source,
    resolved_food,
    summarize,
)


def _document(**changes: Any) -> dict[str, Any]:
    draft = {
        "source_id": "r753850",
        "title": "Brokkoli-Auflauf",
        "servings": 2,
        "category": "Hauptgericht",
        "source_url": "https://cookidoo.de/recipes/recipe/de-DE/r753850",
        "total_time": "40 Min",
        "note": None,
        "ingredients": ["350 g Brokkoliröschen", "2 Eier", "½ TL Salz", "Pfeffer"],
        "reference": {"kcal_per_serving": 410.0, "protein_g_per_serving": 54.0},
        **changes,
    }
    return {"format": "tellerplan-recipes", "version": 1, "source": "cookidoo", "recipes": [draft]}


def _imported(session: Session) -> Recipe:
    recipe = find_recipe_by_source(session, "cookidoo", "r753850")
    assert recipe is not None
    return recipe


def test_import_creates_recipe_with_parsed_lines(session: Session) -> None:
    result = import_document(session, _document())

    recipe = _imported(session)
    assert (result.created, result.updated, result.lines) == (1, 0, 4)
    assert (recipe.title, recipe.servings, recipe.category) == (
        "Brokkoli-Auflauf",
        2,
        "Hauptgericht",
    )
    assert recipe.note == "Gesamtzeit 40 Min"
    assert [(i.name, i.quantity, i.unit) for i in recipe.ingredients] == [
        ("Brokkoliröschen", 350, "g"),
        ("Eier", 2, "Stück"),
        ("Salz", 0.5, "TL"),
        ("Pfeffer", None, None),
    ]
    assert recipe.ingredients[0].raw_text == "350 g Brokkoliröschen"


def test_reference_values_are_kept_but_never_counted(session: Session) -> None:
    import_document(session, _document())

    recipe = _imported(session)
    assert recipe.reference is not None
    assert (recipe.reference.kcal, recipe.reference.protein_g) == (410, 54)
    assert summarize(recipe).per_serving.kcal == 0  # Regel 2: nur eigene Lebensmittel zählen


def test_reimport_updates_but_keeps_ingredients(session: Session) -> None:
    import_document(session, _document())
    broccoli = make_food(session, "Broccoli roh")
    _imported(session).ingredients[0].food = broccoli
    _imported(session).instructions = "Ofen vorheizen"

    result = import_document(session, _document(title="Brokkoli-Auflauf neu", ingredients=["1 Ei"]))

    recipe = _imported(session)
    assert (result.created, result.updated) == (0, 1)
    assert recipe.title == "Brokkoli-Auflauf neu"
    assert len(recipe.ingredients) == 4
    assert recipe.ingredients[0].food == broccoli
    assert recipe.instructions == "Ofen vorheizen"
    assert len(session.scalars(select(Recipe)).all()) == 1


def test_source_categories_map_to_the_list(session: Session) -> None:
    import_document(session, _document(category="Snack/Beilage"))

    assert _imported(session).category == "Snack"


def test_reimport_keeps_category_set_by_hand(session: Session) -> None:
    import_document(session, _document(category="Snack/Beilage"))
    _imported(session).category = "Beilage"

    import_document(session, _document(category="Snack/Beilage"))

    assert _imported(session).category == "Beilage"


def test_known_names_bring_their_base_ingredient(session: Session) -> None:
    egg = make_food(session, "Hühnerei roh", units={"Stück": 58})
    eggs = create_base(session, "Ei")
    set_default_product(session, eggs, egg)
    link_name(session, "Eier", eggs)
    link_name(session, "Salz", create_base(session, "Salz", no_nutrients=True))

    result = import_document(session, _document())

    lines = {i.name: i for i in _imported(session).ingredients}
    assert result.matched_lines == 2  # Eier über den Standard, Salz ohne Nährwerte
    assert lines["Eier"].base_ingredient == eggs
    assert lines["Eier"].food is None  # folgt dem Standard, kein eigenes Produkt
    assert resolved_food(lines["Eier"]) == egg
    assert effective_grams(lines["Eier"]) == 116
    assert lines["Brokkoliröschen"].base_ingredient is None


def test_lines_without_quantity_do_not_block_completeness(session: Session) -> None:
    import_document(session, _document(ingredients=["Salz", "Pfeffer"]))

    match = summarize(_imported(session)).match
    assert (match.matched, match.total, match.complete) == (0, 0, True)


def test_missing_servings_fall_back_to_one(session: Session) -> None:
    import_document(session, _document(servings=None))

    assert _imported(session).servings == 1


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ([], "kein JSON-Objekt"),
        ({"format": "anders", "version": 1}, "Unbekanntes Format"),
        ({"format": "tellerplan-recipes", "version": 2}, "Version"),
        ({"format": "tellerplan-recipes", "version": 1, "source": "x"}, "Rezeptliste"),
        (
            {
                "format": "tellerplan-recipes",
                "version": 1,
                "source": "x",
                "recipes": [{"title": "A"}],
            },
            "Quell-ID",
        ),
    ],
)
def test_invalid_documents_are_rejected(session: Session, document: object, message: str) -> None:
    with pytest.raises(ImportFormatError, match=message):
        import_document(session, document)


def test_upload_page_imports_file(ingress_client: TestClient) -> None:
    content = json.dumps(_document()).encode()

    response = ingress_client.post(
        "/settings/import", files={"file": ("entwuerfe.json", content, "application/json")}
    )

    assert "1 neu, 0 schon vorhanden" in response.text
    assert "Brokkoli-Auflauf" in ingress_client.get("/recipes").text


def test_upload_page_reports_invalid_file(ingress_client: TestClient) -> None:
    response = ingress_client.post(
        "/settings/import", files={"file": ("kaputt.json", b"{nicht json", "application/json")}
    )

    assert "kein gültiges JSON" in response.text


def test_settings_link_to_import(ingress_client: TestClient) -> None:
    assert 'href="/settings/import"' in ingress_client.get("/settings").text
