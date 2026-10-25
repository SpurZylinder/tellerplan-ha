"""Zuordnen über Grundzutaten: Name → Grundzutat → Standardprodukt, Ausnahmen je Rezept."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from factories import make_food
from modules.foods.models import Food
from modules.importers.service import import_document
from modules.recipes.matching import (
    base_for_name,
    base_usages,
    choose_product,
    create_base,
    link_name,
    open_groups,
    set_default_product,
    unit_gaps,
)
from modules.recipes.models import BaseIngredient, Recipe
from modules.recipes.service import (
    find_recipe_by_source,
    ingredient_label,
    line_breakdown,
    resolved_food,
    summarize,
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


def _import_three(session: Session) -> None:
    import_document(
        session,
        _document(
            ("a", ["200 ml Milch", "2 Zwiebeln", "1 TL Kreuzkümmel"]),
            ("b", ["100 ml Milch", "1 Zwiebel", "250 ml Vollmilch"]),
            ("c", ["300 ml Milch"]),
        ),
    )


def _milk_base(
    session: Session, food_name: str = "Laktosefreie Milch 1,5 %"
) -> tuple[BaseIngredient, Food]:
    milk = make_food(session, food_name, kcal=47, units={"ml": 1})
    base = create_base(session, "Milch")
    set_default_product(session, base, milk)
    link_name(session, "Milch", base)
    return base, milk


def test_open_groups_collect_names_across_recipes(session: Session) -> None:
    _import_three(session)

    groups = open_groups(session)

    assert (groups[0].key, groups[0].lines, len(groups[0].recipes)) == ("milch", 3, 3)
    assert groups[0].examples == ["100 ml Milch", "200 ml Milch", "300 ml Milch"]


def test_standard_product_applies_to_all_lines_of_the_base(session: Session) -> None:
    _import_three(session)
    _, milk = _milk_base(session)

    line = _recipe(session, "c").ingredients[0]
    assert line.food is None  # folgt dem Standard, kein eigenes Produkt
    assert resolved_food(line) == milk
    assert summarize(_recipe(session, "c")).match.complete
    assert all(group.key != "milch" for group in open_groups(session))


def test_changing_the_standard_follows_without_rewriting_lines(session: Session) -> None:
    _import_three(session)
    base, _ = _milk_base(session, "Vollmilch 3,5 %")
    new_milk = make_food(session, "Laktosefreie Milch 1,5 %", units={"ml": 1})
    oat_drink = make_food(session, "Haferdrink", units={"ml": 1})
    choose_product(session, _recipe(session, "b").ingredients[0], oat_drink)  # bewusst anders

    set_default_product(session, base, new_milk)

    assert resolved_food(_recipe(session, "a").ingredients[0]) == new_milk
    assert resolved_food(_recipe(session, "b").ingredients[0]) == oat_drink
    assert oat_drink in base.products


def test_specialisations_are_their_own_base_ingredients(session: Session) -> None:
    _import_three(session)
    _, milk = _milk_base(session)
    whole = create_base(session, "Vollmilch")
    set_default_product(session, whole, milk)  # gleiches Produkt, eigene Grundzutat
    link_name(session, "Vollmilch", whole)

    lines = {line.name: line for line in _recipe(session, "b").ingredients}

    assert lines["Vollmilch"].base_ingredient == whole
    assert resolved_food(lines["Vollmilch"]) == milk
    assert [usage.base.name for usage in base_usages(session)] == ["Milch", "Vollmilch"]


def test_spices_without_nutrients_count_as_complete(session: Session) -> None:
    import_document(session, _document(("d", ["1 TL Kreuzkümmel"])))
    link_name(session, "Kreuzkümmel", create_base(session, "Kreuzkümmel", no_nutrients=True))

    summary = summarize(_recipe(session, "d"))

    assert summary.match.complete
    assert summary.per_serving.kcal == 0
    assert unit_gaps(session) == []


def test_new_imports_use_learned_names(session: Session) -> None:
    base = create_base(session, "Milch")
    link_name(session, "Milch", base)

    import_document(session, _document(("e", ["250 ml Milch"])))

    assert _recipe(session, "e").ingredients[0].base_ingredient == base
    assert base_for_name(session, "  milch ") == base


def test_unit_gaps_follow_the_resolved_product(session: Session) -> None:
    _import_three(session)
    onion = make_food(session, "Speisezwiebel roh")
    base = create_base(session, "Zwiebel")
    set_default_product(session, base, onion)
    link_name(session, "Zwiebeln", base)
    link_name(session, "Zwiebel", base)

    gaps = unit_gaps(session)

    assert [(gap.food.name, gap.unit, gap.lines) for gap in gaps] == [
        ("Speisezwiebel roh", "Stück", 2)
    ]


def test_recipe_line_shows_name_and_breakdown_shows_product(session: Session) -> None:
    import_document(session, _document(("f", ["200 ml Milch"])))
    _, milk = _milk_base(session)

    line = line_breakdown(_recipe(session, "f"))[0]

    assert ingredient_label(line.ingredient) == "200 ml Milch"
    assert line.food == milk
    assert line.nutrients is not None
    assert round(line.nutrients.kcal) == 94


# --- Seiten ---------------------------------------------------------------


def test_matching_flow_through_pages(ingress_client: TestClient, session: Session) -> None:
    import_document(session, _document(("g", ["200 ml Milch", "1 TL Kreuzkümmel"])))
    milk = make_food(session, "Laktosefreie Milch 1,5 %", kcal=47, units={"ml": 1})
    session.commit()

    page = ingress_client.get("/matching")
    assert "Milch" in page.text
    assert "Kreuzkümmel" in page.text

    ingress_client.post(
        "/matching/assign", data={"name": "Milch", "base_name": "Milch", "food_id": str(milk.id)}
    )
    ingress_client.post(
        "/matching/assign",
        data={"name": "Kreuzkümmel", "base_name": "Kreuzkümmel", "no_nutrients": "true"},
    )

    session.expire_all()
    summary = summarize(_recipe(session, "g"))
    assert summary.match.complete
    assert round(summary.per_serving.kcal) == 47  # 200 ml × 47 kcal / 100 / 2 Portionen
    assert "Milch" in ingress_client.get("/bases").text


def test_base_without_product_gets_one_from_matching_page(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("h", ["200 ml Milch"])))
    base = create_base(session, "Milch")
    link_name(session, "Milch", base)
    milk = make_food(session, "Milch 1,5 %")
    session.commit()

    assert "Als Standard" in ingress_client.get("/matching?view=products").text
    ingress_client.post(
        f"/bases/{base.id}/default", data={"food_id": str(milk.id), "back": "matching"}
    )

    session.expire_all()
    assert base_for_name(session, "Milch").default_food == milk


def test_line_page_chooses_product_only_for_this_recipe(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("i", ["200 ml Milch"]), ("j", ["100 ml Milch"])))
    _, milk = _milk_base(session)
    oat = make_food(session, "Haferdrink", units={"ml": 1})
    session.commit()
    recipe = _recipe(session, "i")
    line = recipe.ingredients[0]

    page = ingress_client.get(f"/recipes/{recipe.id}/ingredients/{line.id}")
    assert "Standard der Grundzutat" in page.text
    ingress_client.post(
        f"/recipes/{recipe.id}/ingredients/{line.id}",
        data={
            "name": "Milch",
            "quantity": "200",
            "unit": "ml",
            "base_name": "Milch",
            "food_id": str(oat.id),
        },
    )

    session.expire_all()
    assert resolved_food(_recipe(session, "i").ingredients[0]) == oat
    assert resolved_food(_recipe(session, "j").ingredients[0]) == milk


def test_recipe_page_shows_short_lines_and_breakdown(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("k", ["200 ml Milch"])))
    _, milk = _milk_base(session)
    milk.brand = "Berchtesgadener Land"
    session.commit()
    recipe = _recipe(session, "k")

    page = ingress_client.get(f"/recipes/{recipe.id}").text
    cook = ingress_client.get(f"/recipes/{recipe.id}/cook").text

    assert ">200 ml Milch</a>" in page
    assert "→ Laktosefreie Milch 1,5 % (Berchtesgadener Land)" in page
    assert "200 ml Milch" in cook
    assert "Berchtesgadener" not in cook


def test_label_hides_count_unit_and_uses_plural_units(session: Session) -> None:
    import_document(
        session, _document(("m", ["20 Lasagneplatten", "2 Prisen Salz", "1 Prise Zucker"]))
    )

    labels = [ingredient_label(line) for line in _recipe(session, "m").ingredients]

    assert labels == ["20 Lasagneplatten", "2 Prisen Salz", "1 Prise Zucker"]
