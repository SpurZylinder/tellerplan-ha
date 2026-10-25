"""Zuordnen: offene Zutaten je Name, Standardartikel, fehlende Einheiten."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from factories import make_food
from modules.importers.service import import_document
from modules.recipes.models import Recipe
from modules.recipes.service import (
    alias_food,
    assign_key,
    find_recipe_by_source,
    open_groups,
    summarize,
    unit_gaps,
)


def _document(*drafts: tuple[str, list[str]]) -> dict[str, Any]:
    recipes = [
        {
            "source_id": source_id,
            "title": f"Rezept {source_id}",
            "servings": 2,
            "ingredients": lines,
        }
        for source_id, lines in drafts
    ]
    return {"format": "tellerplan-recipes", "version": 1, "source": "cookidoo", "recipes": recipes}


def _recipe(session: Session, source_id: str) -> Recipe:
    recipe = find_recipe_by_source(session, "cookidoo", source_id)
    assert recipe is not None
    return recipe


def _import_two(session: Session) -> None:
    import_document(
        session,
        _document(
            ("a", ["200 ml Milch", "2 Zwiebeln", "Salz"]),
            ("b", ["100 ml Milch", "1 Zwiebel"]),
            ("c", ["300 ml Milch"]),
        ),
    )


def test_open_groups_collect_lines_across_recipes(session: Session) -> None:
    _import_two(session)

    groups = open_groups(session)

    assert [(g.key, g.lines, len(g.recipes)) for g in groups][:2] == [
        ("milch", 3, 3),
        ("salz", 1, 1),
    ]
    assert groups[0].examples == ["100 ml Milch", "200 ml Milch", "300 ml Milch"]


def test_assign_key_sets_standard_food_everywhere(session: Session) -> None:
    _import_two(session)
    milk = make_food(session, "Laktosefreie Milch 1,5 % (Berchtesgadener Land)", units={"ml": 1.03})

    changed = assign_key(session, "milch", milk)

    assert changed == 3
    assert alias_food(session, "milch") == milk
    assert all(
        line.food == milk for line in _recipe(session, "a").ingredients if line.name == "Milch"
    )
    assert _recipe(session, "c").ingredients[0].grams == 309


def test_new_imports_use_the_standard_food(session: Session) -> None:
    milk = make_food(session, "Milch")
    assign_key(session, "milch", milk)

    import_document(session, _document(("d", ["250 ml Milch"])))

    assert _recipe(session, "d").ingredients[0].food == milk


def test_changing_the_standard_keeps_deliberate_exceptions(session: Session) -> None:
    _import_two(session)
    old_milk = make_food(session, "Vollmilch")
    new_milk = make_food(session, "Laktosefreie Milch")
    oat_drink = make_food(session, "Haferdrink")
    assign_key(session, "milch", old_milk)
    _recipe(session, "b").ingredients[0].food = oat_drink  # bewusst anders im Rezept b

    changed = assign_key(session, "milch", new_milk)

    assert changed == 2
    assert _recipe(session, "a").ingredients[0].food == new_milk
    assert _recipe(session, "b").ingredients[0].food == oat_drink


def test_unit_gaps_list_missing_grams(session: Session) -> None:
    _import_two(session)
    onion = make_food(session, "Speisezwiebel roh")
    assign_key(session, "zwiebeln", onion)
    assign_key(session, "zwiebel", onion)

    gaps = unit_gaps(session)

    assert [(gap.food.name, gap.unit, gap.lines) for gap in gaps] == [
        ("Speisezwiebel roh", "Stück", 2)
    ]


def test_matching_page_assigns_and_completes_recipe(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("e", ["2 Zwiebeln"])))
    onion = make_food(session, "Speisezwiebel roh", kcal=40)
    session.commit()

    page = ingress_client.get("/matching")
    assert "Zwiebeln" in page.text
    assert 'hx-trigger="intersect once"' in page.text

    ingress_client.post("/matching/assign", data={"key": "zwiebeln", "food_id": str(onion.id)})
    units = ingress_client.get("/matching?view=units")
    assert "1 Stück = … g" in units.text

    ingress_client.post(
        "/matching/unit", data={"food_id": str(onion.id), "unit": "Stück", "grams": "80"}
    )

    session.expire_all()
    summary = summarize(_recipe(session, "e"))
    assert summary.match.complete
    assert summary.per_serving.kcal == 32  # 2 × 80 g × 40 kcal / 100 g / 2 Portionen
    assert "zwiebeln" in ingress_client.get("/matching?view=learned").text


def test_assign_without_food_shows_error(ingress_client: TestClient) -> None:
    response = ingress_client.post("/matching/assign", data={"key": "milch"})

    assert "Bitte ein Lebensmittel wählen." in response.text


def test_recipes_list_links_to_open_lines(ingress_client: TestClient, session: Session) -> None:
    import_document(session, _document(("f", ["2 Zwiebeln", "Salz"])))
    session.commit()

    assert "Zuordnen · 2 offen" in ingress_client.get("/recipes").text


def test_recipe_shows_reference_for_comparison(
    ingress_client: TestClient, session: Session
) -> None:
    document = _document(("g", ["2 Zwiebeln"]))
    document["recipes"][0]["reference"] = {"kcal_per_serving": 410, "protein_g_per_serving": 54}
    import_document(session, document)
    session.commit()

    page = ingress_client.get(f"/recipes/{_recipe(session, 'g').id}").text

    assert "Zum Vergleich laut Cookidoo: 410 kcal · 54 g Eiweiß pro Portion" in page


def test_matching_suggestions_are_not_preselected(
    ingress_client: TestClient, session: Session
) -> None:
    make_food(session, "Meersalz")
    session.commit()

    suggestions = ingress_client.get("/foods/picker?preselect=false&q=salz").text
    form_picker = ingress_client.get("/foods/picker?q=salz").text

    assert "Meersalz" in suggestions
    assert "checked" not in suggestions
    assert "checked" in form_picker
