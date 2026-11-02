"""Datenmodell für den Cookidoo-Abgleich: Platzhalter, Vollständigkeit, Notizen beim Löschen."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from factories import make_food, make_recipe
from modules.diary.service import log_recipe
from modules.importers.service import import_document
from modules.planner.service import (
    add_entry,
    delete_entries_of_recipe,
    delete_entry,
    move_entry,
    removals,
)
from modules.recipes.models import COOKIDOO_SOURCE, Recipe
from modules.recipes.service import (
    create_placeholder,
    find_recipe_by_source,
    get_recipe,
    summarize,
)

DAY = date(2026, 11, 4)
COOKIDOO_ID = "r821223"
URL = f"https://cookidoo.de/recipes/recipe/de-DE/{COOKIDOO_ID}"


def _placeholder(session: Session) -> Recipe:
    return create_placeholder(session, COOKIDOO_ID, "Linsen-Dal", URL)


def test_placeholder_has_title_id_link_and_one_serving(session: Session) -> None:
    recipe = _placeholder(session)

    assert (recipe.source, recipe.source_id, recipe.source_url) == (
        COOKIDOO_SOURCE,
        COOKIDOO_ID,
        URL,
    )
    assert recipe.servings == 1
    assert recipe.is_placeholder
    assert find_recipe_by_source(session, COOKIDOO_SOURCE, COOKIDOO_ID) is recipe


def test_recipe_without_ingredients_is_incomplete(session: Session) -> None:
    match = summarize(_placeholder(session)).match

    assert match.empty
    assert not match.complete
    assert not summarize(make_recipe(session, "Von Hand, leer")).match.complete


def test_recipe_with_ingredients_is_no_placeholder(session: Session) -> None:
    recipe = make_recipe(session, ingredients=[(make_food(session), 100, "g")])

    assert not recipe.is_placeholder
    assert summarize(recipe).match.complete


def test_eating_a_placeholder_marks_the_day_incomplete(session: Session) -> None:
    entry = log_recipe(session, DAY, "Mittag", _placeholder(session), 1)

    assert entry.kcal == 0
    assert not entry.is_complete


def test_deleting_a_synced_entry_leaves_a_removal_note(session: Session) -> None:
    entry = add_entry(session, DAY, _placeholder(session))
    entry.cookidoo_day = DAY

    delete_entry(session, entry)

    assert [(note.day, note.cookidoo_id) for note in removals(session)] == [(DAY, COOKIDOO_ID)]


def test_note_uses_the_day_in_cookidoo_not_the_moved_day(session: Session) -> None:
    entry = add_entry(session, DAY, _placeholder(session))
    entry.cookidoo_day = DAY
    move_entry(session, entry, DAY + timedelta(days=2))

    assert entry.cookidoo_day == DAY
    delete_entry(session, entry)
    assert [note.day for note in removals(session)] == [DAY]


def test_unsynced_or_manual_entries_leave_no_note(session: Session) -> None:
    delete_entry(session, add_entry(session, DAY, _placeholder(session)))
    manual = add_entry(session, DAY, make_recipe(session))
    manual.cookidoo_day = DAY  # ohne Cookidoo-ID gibt es nichts zu entfernen
    delete_entry(session, manual)

    assert removals(session) == []


def test_deleting_a_recipe_leaves_notes_for_its_synced_entries(session: Session) -> None:
    recipe = _placeholder(session)
    for offset in (0, 1):
        add_entry(session, DAY + timedelta(days=offset), recipe).cookidoo_day = DAY

    delete_entries_of_recipe(session, recipe)

    assert len(removals(session)) == 2


def test_recipe_delete_page_leaves_notes(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        recipe = _placeholder(session)
        add_entry(session, DAY, recipe).cookidoo_day = DAY
        session.commit()
        recipe_id = recipe.id

    ingress_client.post(f"/recipes/{recipe_id}/delete")

    with ingress_client.app.state.session_factory() as session:
        assert get_recipe(session, recipe_id) is None
        assert [note.cookidoo_id for note in removals(session)] == [COOKIDOO_ID]


def test_import_fills_a_placeholder_but_keeps_maintained_recipes(session: Session) -> None:
    placeholder = _placeholder(session)
    maintained = make_recipe(session, "Gepflegt", ingredients=[(make_food(session), 100, "g")])
    maintained.source, maintained.source_id = COOKIDOO_SOURCE, "r1"
    draft = {"title": "Linsen-Dal", "servings": 4, "ingredients": ["200 g Linsen", "1 Zwiebel"]}
    document = {
        "format": "tellerplan-recipes",
        "version": 1,
        "source": COOKIDOO_SOURCE,
        "recipes": [
            {**draft, "source_id": COOKIDOO_ID},
            {**draft, "source_id": "r1", "title": "Gepflegt"},
        ],
    }

    import_document(session, document)

    assert [line.raw_text for line in placeholder.ingredients] == ["200 g Linsen", "1 Zwiebel"]
    assert placeholder.servings == 4
    assert not placeholder.is_placeholder
    assert len(maintained.ingredients) == 1


def test_placeholder_is_marked_in_recipe_list_and_detail(ingress_client: TestClient) -> None:
    with ingress_client.app.state.session_factory() as session:
        recipe_id = _placeholder(session).id
        session.commit()

    assert "Platzhalter" in ingress_client.get("/recipes").text
    detail = ingress_client.get(f"/recipes/{recipe_id}").text
    assert "Platzhalter aus „Meine Woche“" in detail
    assert "keine Zutaten" in detail
