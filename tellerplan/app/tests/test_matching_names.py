"""Toleranter Namensschlüssel, Vorschläge beim Zuordnen und Zusammenführen von Grundzutaten."""

import sqlite3
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from factories import make_food
from migrate import alembic_config, upgrade_to_head
from modules.importers.service import import_document
from modules.recipes.matching import (
    BaseNameTakenError,
    all_bases,
    base_for_name,
    create_base,
    find_base,
    link_name,
    merge_bases,
    open_groups,
    rename_base,
    set_default_product,
    similar_bases,
)
from modules.recipes.service import alias_key, find_recipe_by_source, summarize
from settings import Settings


def _document(lines: list[str]) -> dict[str, Any]:
    draft = {"source_id": "r1", "title": "Testrezept", "servings": 2, "ingredients": lines}
    return {"format": "tellerplan-recipes", "version": 1, "source": "cookidoo", "recipes": [draft]}


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Zwiebel", "Zwiebeln"),
        ("Tomate", "Tomaten"),
        ("rote Zwiebel", "Rote  Zwiebeln"),
        ("Lachsfilet", "Lachsfilets"),
        ("Cheddar-Käse", "Cheddar Käse"),
        ("Weissmehl", "Weißmehl"),
        ("Salatgurke", "Salatgurken"),
    ],
)
def test_alias_key_ignores_spelling_and_plural(first: str, second: str) -> None:
    assert alias_key(first) == alias_key(second)


@pytest.mark.parametrize(("first", "second"), [("Ei", "Eier"), ("Reis", "Mais"), ("Sahne", "Saft")])
def test_alias_key_keeps_short_and_different_words_apart(first: str, second: str) -> None:
    assert alias_key(first) != alias_key(second)


def test_plural_finds_the_learned_singular(session: Session) -> None:
    onion = create_base(session, "Zwiebel")
    link_name(session, "Zwiebel", onion)

    import_document(session, _document(["2 Zwiebeln", "1 rote Zwiebel"]))

    assert base_for_name(session, "Zwiebeln") == onion
    recipe = find_recipe_by_source(session, "cookidoo", "r1")
    assert recipe is not None
    assert recipe.ingredients[0].base_ingredient == onion
    assert recipe.ingredients[1].base_ingredient is None  # „rote Zwiebel“ ist etwas anderes


def test_open_groups_join_spelling_variants(session: Session) -> None:
    import_document(session, _document(["1 Limette", "2 Limetten"]))

    (group,) = open_groups(session)

    assert group.lines == 2


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("frischer Koriander", "Koriander"),
        ("Räuchertofu", "Tofu"),
        ("Dinkelmehl Type 630", "Mehl"),
        ("Quark", "Magerquark"),
        ("Brokoli", "Brokkoli"),
        ("Risottoreis Arborio", "Risottoreis"),
    ],
)
def test_similar_bases_suggest_existing_ones(session: Session, name: str, expected: str) -> None:
    for base_name in (
        "Koriander",
        "Tofu",
        "Mehl",
        "Magerquark",
        "Brokkoli",
        "Risottoreis",
        "Zucker",
    ):
        create_base(session, base_name)

    suggestions = [base.name for base in similar_bases(all_bases(session), name)]

    assert suggestions[0] == expected
    assert "Zucker" not in suggestions


def test_similar_bases_exclude_the_base_itself(session: Session) -> None:
    ginger = create_base(session, "Ingwer")
    create_base(session, "frischer Ingwer")

    assert [b.name for b in similar_bases(all_bases(session), "Ingwer", exclude=ginger)] == [
        "frischer Ingwer"
    ]


def test_merge_moves_lines_names_and_products(session: Session) -> None:
    fresh = make_food(session, "Ingwer roh", kcal=80)
    other = make_food(session, "Ingwer gemahlen", kcal=300)
    ginger = create_base(session, "Ingwer")
    set_default_product(session, ginger, fresh)
    link_name(session, "Ingwer", ginger)
    fresh_ginger = create_base(session, "frischer Ingwer")
    set_default_product(session, fresh_ginger, other)
    import_document(session, _document(["20 g frischer Ingwer", "10 g Ingwer"]))
    link_name(session, "frischer Ingwer", fresh_ginger)

    moved = merge_bases(session, fresh_ginger, ginger)

    assert moved == 1
    assert find_base(session, "frischer Ingwer") is None
    assert base_for_name(session, "frischer Ingwer") == ginger
    assert other in ginger.products
    recipe = find_recipe_by_source(session, "cookidoo", "r1")
    assert recipe is not None
    assert {line.base_ingredient for line in recipe.ingredients} == {ginger}
    assert round(summarize(recipe).per_serving.kcal) == 12  # 30 g × 80 kcal / 100 / 2


def test_rename_onto_an_existing_name_asks_for_merge(session: Session) -> None:
    create_base(session, "Zwiebeln")
    onion = create_base(session, "Zwiebel roh")

    with pytest.raises(BaseNameTakenError):
        rename_base(session, onion, "Zwiebel")


def test_matching_page_offers_suggestions(ingress_client: TestClient, session: Session) -> None:
    coriander = create_base(session, "Koriander")
    link_name(session, "Koriander", coriander)
    import_document(session, _document(["1 Bund frischer Koriander", "60 g Agavendicksaft"]))
    session.commit()

    page = ingress_client.get("/matching").text
    assert 'name="suggestion" value="Koriander"' in page
    assert 'value="Agavendicksaft" list="base-names"' not in page  # nur ohne Vorschlag vorbelegt
    assert 'list="base-names" value="Agavendicksaft"' in page

    ingress_client.post(
        "/matching/assign", data={"name": "frischer Koriander", "suggestion": "Koriander"}
    )
    session.expire_all()
    assert base_for_name(session, "frischer Koriander") == coriander
    assert len(all_bases(session)) == 1


def test_matching_without_choice_is_rejected(ingress_client: TestClient, session: Session) -> None:
    import_document(session, _document(["60 g Agavendicksaft"]))
    session.commit()

    response = ingress_client.post("/matching/assign", data={"name": "Agavendicksaft"})

    assert "Bitte eine Grundzutat wählen" in response.text
    session.expire_all()
    assert all_bases(session) == []


def test_merge_through_base_page(ingress_client: TestClient, session: Session) -> None:
    onions = create_base(session, "Zwiebeln")
    shallot = create_base(session, "Zwiebel weiß")
    session.commit()

    page = ingress_client.get(f"/bases/{shallot.id}").text
    assert "In „Zwiebeln“ aufgehen lassen" in page

    response = ingress_client.post(
        f"/bases/{shallot.id}/merge", data={"target_name": "Zwiebeln"}, follow_redirects=False
    )
    assert response.headers["location"].endswith(f"/bases/{onions.id}")
    session.expire_all()
    assert [base.name for base in all_bases(session)] == ["Zwiebeln"]


def test_migration_0014_merges_plural_twins_without_changing_nutrients(
    settings: Settings,
) -> None:
    command.upgrade(alembic_config(settings, skip_data_migrations=True), "0013")
    connection = sqlite3.connect(settings.database_path)
    connection.executescript(
        """
        INSERT INTO food (id, name, source, kcal, protein_g, fat_g, carbs_g)
            VALUES (1, 'Speisezwiebel roh', 'custom', 34, 1, 0, 7),
                   (2, 'Gemüsezwiebel roh', 'custom', 30, 1, 0, 6);
        INSERT INTO base_ingredient (id, name, key, default_food_id, no_nutrients)
            VALUES (1, 'Zwiebel', 'zwiebel', 1, 0), (2, 'Zwiebeln', 'zwiebeln', 2, 0);
        INSERT INTO base_ingredient_food VALUES (1, 1), (2, 2);
        INSERT INTO ingredient_alias (id, key, base_ingredient_id)
            VALUES (1, 'zwiebel', 1), (2, 'zwiebeln', 2);
        INSERT INTO recipe (id, title, source, servings, is_favorite)
            VALUES (1, 'Suppe', 'manual', 2, 0);
        INSERT INTO recipe_ingredient (id, recipe_id, position, raw_text, name, quantity, unit,
            base_ingredient_id, is_optional)
            VALUES (1, 1, 1, '100 g Zwiebel', 'Zwiebel', 100, 'g', 1, 0),
                   (2, 1, 2, '200 g Zwiebeln', 'Zwiebeln', 200, 'g', 2, 0),
                   (3, 1, 3, '50 g Zwiebeln', 'Zwiebeln', 50, 'g', 2, 0),
                   (4, 1, 4, '1 ZWIEBELN', 'ZWIEBELN', 1, 'Stück', NULL, 0);
        """
    )
    connection.commit()
    connection.close()

    upgrade_to_head(settings, skip_data_migrations=True)

    connection = sqlite3.connect(settings.database_path)
    bases = connection.execute("SELECT id, name, key, default_food_id FROM base_ingredient")
    assert bases.fetchall() == [(2, "Zwiebeln", "zwiebel", 2)]  # mehr Zeilen gewinnt
    lines = connection.execute("SELECT id, base_ingredient_id, food_id FROM recipe_ingredient")
    # Zeile 1 rechnete mit Speisezwiebel und behält sie; Zeile 4 trifft jetzt den Namen
    assert lines.fetchall() == [(1, 2, 1), (2, 2, None), (3, 2, None), (4, 2, None)]
    aliases = connection.execute("SELECT key, base_ingredient_id FROM ingredient_alias")
    assert aliases.fetchall() == [("zwiebel", 2)]
    products = connection.execute("SELECT * FROM base_ingredient_food ORDER BY food_id")
    assert products.fetchall() == [(2, 1), (2, 2)]
    connection.close()
