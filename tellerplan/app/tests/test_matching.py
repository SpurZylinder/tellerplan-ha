"""Zuordnen über Grundzutaten: Name → Grundzutat → Standardprodukt, Ausnahmen je Rezept."""

from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from factories import make_food
from modules.diary.models import DiaryEntry
from modules.foods.models import Food, FoodSource
from modules.importers.service import import_document
from modules.recipes.matching import (
    add_product,
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


def test_assign_with_product_but_empty_name_uses_the_ingredient_name(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("k", ["200 g Dinkelmehl Type 630"])))
    create_base(session, "Dinkelmehl")  # erzeugt einen Vorschlag, das Textfeld bleibt leer
    flour = make_food(session, "Dinkelmehl Type 630", kcal=340)
    session.commit()

    response = ingress_client.post(
        "/matching/assign",
        data={
            "name": "Dinkelmehl Type 630",
            "base_name": "",
            "food_id": str(flour.id),
            "position": "3",
        },
        follow_redirects=False,
    )

    assert "error" not in response.headers["location"]
    assert response.headers["location"].endswith("#card-3")
    session.expire_all()
    assert base_for_name(session, "Dinkelmehl Type 630").default_food == flour


def test_assign_without_anything_keeps_the_place_and_shows_the_error_there(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("l", ["1 Prise Zimt"])))
    session.commit()

    response = ingress_client.post(
        "/matching/assign",
        data={"name": "Zimt", "base_name": "", "position": "0", "show_all": "true"},
    )

    assert response.url.fragment == "card-0"
    assert "show_all=true" in str(response.url)
    assert 'id="card-0"' in response.text
    card = response.text.split('id="card-0"', 1)[1]
    assert card.index("Bitte eine Grundzutat") < card.index("</form>")


def test_line_page_marks_an_open_line_as_spice_for_all_recipes(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("m", ["1 TL Kümmel"]), ("n", ["2 TL Kümmel"])))
    session.commit()
    recipe = _recipe(session, "m")
    line = recipe.ingredients[0]

    page = ingress_client.get(f"/recipes/{recipe.id}/ingredients/{line.id}")
    assert "ohne Nährwerte" in page.text
    ingress_client.post(
        f"/recipes/{recipe.id}/ingredients/{line.id}",
        data={"name": "Kümmel", "quantity": "1", "unit": "TL", "no_nutrients": "true"},
    )

    session.expire_all()
    base = base_for_name(session, "Kümmel")
    assert base is not None and base.no_nutrients
    assert summarize(_recipe(session, "m")).match.complete
    assert summarize(_recipe(session, "n")).match.complete
    page = ingress_client.get(f"/recipes/{recipe.id}/ingredients/{line.id}")
    assert f"/bases/{base.id}" in page.text


def test_line_page_switching_base_keeps_the_other_bases_flag(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("o", ["1 Prise Gewürzsalz"])))
    salt = create_base(session, "Salz", no_nutrients=True)
    session.commit()
    recipe = _recipe(session, "o")
    line = recipe.ingredients[0]
    link_name(session, "Gewürzsalz", create_base(session, "Gewürzsalz"))
    session.commit()

    ingress_client.post(
        f"/recipes/{recipe.id}/ingredients/{line.id}",
        data={"name": "Gewürzsalz", "base_name": "Salz"},
    )

    session.expire_all()
    assert salt.no_nutrients
    assert _recipe(session, "o").ingredients[0].base_ingredient == salt


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


def test_unit_page_accepts_grams_with_unit(ingress_client: TestClient, session: Session) -> None:
    import_document(session, _document(("n", ["2 Eier"])))
    egg = make_food(session, "Hühnerei roh", kcal=137)
    base = create_base(session, "Ei")
    set_default_product(session, base, egg)
    link_name(session, "Eier", base)
    session.commit()

    response = ingress_client.post(
        "/matching/unit", data={"food_id": str(egg.id), "unit": "Stück", "grams": "50g"}
    )

    assert "bitte eine Zahl" not in response.text
    session.expire_all()
    assert summarize(_recipe(session, "n")).match.complete


# --- Lebensmittel löschen -------------------------------------------------


def test_deleting_a_food_releases_bases_lines_and_keeps_the_diary(
    ingress_client: TestClient, session: Session
) -> None:
    import_document(session, _document(("p", ["200 ml Milch"]), ("q", ["100 ml Milch"])))
    base, milk = _milk_base(session)
    oat = make_food(session, "Haferdrink", units={"ml": 1})
    add_product(session, base, oat)
    choose_product(session, _recipe(session, "q").ingredients[0], oat)
    entry = DiaryEntry(
        day=date(2026, 11, 6),
        meal="Frühstück",
        food_id=oat.id,
        quantity=200,
        unit="ml",
        grams=200,
        label="200 ml Haferdrink",
        kcal=90,
        protein_g=1,
        fat_g=3,
        carbs_g=13,
    )
    session.add(entry)
    session.commit()
    oat_id, milk_id = oat.id, milk.id

    page = ingress_client.get(f"/foods/{oat_id}/delete")
    assert "Weiteres Produkt von Milch" in page.text
    assert "Rezept q" in page.text
    assert "Standardprodukt von Milch" in ingress_client.get(f"/foods/{milk_id}/delete").text

    response = ingress_client.post(f"/foods/{oat_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    ingress_client.post(f"/foods/{milk_id}/delete")

    session.expire_all()
    assert session.get(Food, oat_id) is None
    assert entry.food_id is None and entry.kcal == 90
    assert base.default_food is None and base.products == []
    line = _recipe(session, "q").ingredients[0]
    assert line.food is None and line.base_ingredient == base
    assert "Milch" in ingress_client.get("/matching?view=products").text


def test_bls_food_cannot_be_deleted(ingress_client: TestClient, session: Session) -> None:
    food = make_food(session, "Hafer Flocken", source=FoodSource.BLS, source_id="C133000")
    session.commit()

    assert "Löschen" not in ingress_client.get(f"/foods/{food.id}").text
    assert ingress_client.get(f"/foods/{food.id}/delete").status_code == 403
    assert ingress_client.post(f"/foods/{food.id}/delete").status_code == 403
    session.expire_all()
    assert session.get(Food, food.id) is not None
