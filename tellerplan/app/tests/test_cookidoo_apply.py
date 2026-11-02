"""Abgleich ausführen: Datenbank und eine Attrappe von Cookidoo, ohne Netzwerk."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from factories import FAKE_TODAY, FakeCalendar, make_food, make_recipe
from modules.planner.cookidoo_apply import SyncPreview, SyncResult, apply, preview
from modules.planner.cookidoo_sync import MoveInCookidoo
from modules.planner.models import PlanEntry
from modules.planner.service import add_entry, delete_entry, removals
from modules.recipes.models import COOKIDOO_SOURCE, Recipe

FIRST = FAKE_TODAY
LAST = FIRST + timedelta(days=14)


def d(offset: int) -> date:
    return FIRST + timedelta(days=offset)


def _cookidoo_recipe(session: Session, rid: str, title: str = "Linsen-Dal") -> Recipe:
    recipe = make_recipe(session, title, ingredients=[(make_food(session), 200, "g")])
    recipe.source, recipe.source_id = COOKIDOO_SOURCE, rid
    return recipe


def _sync(session: Session, calendar: FakeCalendar) -> SyncResult:
    shown = preview(session, calendar, FIRST, LAST)
    result = apply(session, calendar, FIRST, LAST, shown.fingerprint)
    assert isinstance(result, SyncResult)
    return result


def _entries(session: Session) -> list[tuple[date, str | None, date | None]]:
    statement = select(PlanEntry).order_by(PlanEntry.day, PlanEntry.id)
    return [(e.day, e.recipe.source_id, e.cookidoo_day) for e in session.scalars(statement)]


def test_both_directions_and_placeholders(session: Session) -> None:
    _cookidoo_recipe(session, "r2", "Bekannt")
    add_entry(session, d(4), _cookidoo_recipe(session, "r3"))
    add_entry(session, d(5), make_recipe(session, "Ohne Cookidoo"))
    calendar = FakeCalendar((2, "r1"), (3, "r2"))

    result = _sync(session, calendar)

    assert result.error is None
    assert _entries(session) == [
        (d(2), "r1", d(2)),
        (d(3), "r2", d(3)),
        (d(4), "r3", d(4)),
        (d(5), None, None),
    ]
    placeholder = session.scalar(select(Recipe).where(Recipe.source_id == "r1"))
    assert placeholder is not None and placeholder.is_placeholder
    assert placeholder.title == "Rezept r1"
    assert sorted(calendar.entries) == [(d(2), "r1"), (d(3), "r2"), (d(4), "r3")]
    assert preview(session, calendar, FIRST, LAST).plan.in_sync


def test_preview_writes_nothing_and_names_entries(session: Session) -> None:
    entry = add_entry(session, d(4), _cookidoo_recipe(session, "r3", "Ofengemüse"))
    calendar = FakeCalendar((2, "r1"))

    shown = preview(session, calendar, FIRST, LAST)

    assert len(shown.plan.visible) == 2
    assert shown.titles == {entry.id: "Ofengemüse"}
    assert calendar.calls == []
    assert entry.cookidoo_day is None


def test_changed_cookidoo_shows_new_preview_instead_of_writing(session: Session) -> None:
    calendar = FakeCalendar((2, "r1"))
    shown = preview(session, calendar, FIRST, LAST)
    calendar.entries.append((d(3), "r2"))  # in der Cookidoo-App ergänzt

    result = apply(session, calendar, FIRST, LAST, shown.fingerprint)

    assert isinstance(result, SyncPreview)
    assert len(result.plan.visible) == 2
    assert _entries(session) == []


def test_unknown_recipe_twice_gets_one_placeholder(session: Session) -> None:
    _sync(session, FakeCalendar((2, "r1"), (6, "r1")))

    assert len(session.scalars(select(Recipe).where(Recipe.source_id == "r1")).all()) == 1
    assert [day for day, _, _ in _entries(session)] == [d(2), d(6)]


def test_removed_in_cookidoo_deletes_without_note(session: Session) -> None:
    add_entry(session, d(2), _cookidoo_recipe(session, "r1")).cookidoo_day = d(2)

    _sync(session, FakeCalendar())

    assert _entries(session) == []
    assert removals(session) == []


def test_deleted_in_tellerplan_is_removed_in_cookidoo(session: Session) -> None:
    entry = add_entry(session, d(2), _cookidoo_recipe(session, "r1"))
    entry.cookidoo_day = d(2)
    delete_entry(session, entry)
    calendar = FakeCalendar((2, "r1"))

    _sync(session, calendar)

    assert calendar.entries == []
    assert removals(session) == []


def test_failed_removal_keeps_the_note(session: Session) -> None:
    entry = add_entry(session, d(2), _cookidoo_recipe(session, "r1"))
    entry.cookidoo_day = d(2)
    delete_entry(session, entry)
    calendar = FakeCalendar((2, "r1"))
    calendar.fail.add(("unplan", d(2)))

    result = _sync(session, calendar)

    assert result.error is not None
    assert len(removals(session)) == 1
    calendar.fail.clear()
    _sync(session, calendar)
    assert calendar.entries == []
    assert removals(session) == []


def test_move_adds_first_and_leaves_a_note_if_removing_fails(session: Session) -> None:
    entry = add_entry(session, d(5), _cookidoo_recipe(session, "r1"))
    entry.cookidoo_day = d(2)  # in Tellerplan von Tag 2 auf Tag 5 verschoben
    calendar = FakeCalendar((2, "r1"))
    calendar.fail.add(("unplan", d(2)))

    result = _sync(session, calendar)

    assert isinstance(result.failed[0], MoveInCookidoo)
    assert sorted(calendar.entries) == [(d(2), "r1"), (d(5), "r1")]  # nichts verloren
    assert entry.cookidoo_day == d(5)
    assert [(note.day, note.cookidoo_id) for note in removals(session)] == [(d(2), "r1")]
    calendar.fail.clear()
    _sync(session, calendar)
    assert calendar.entries == [(d(5), "r1")]
    assert _entries(session) == [(d(5), "r1", d(5))]


def test_first_cookidoo_error_stops_writes_but_tellerplan_follows(session: Session) -> None:
    add_entry(session, d(3), _cookidoo_recipe(session, "r3"))
    add_entry(session, d(4), _cookidoo_recipe(session, "r4"))
    calendar = FakeCalendar((2, "r1"))
    calendar.fail.add(("plan", d(3)))

    result = _sync(session, calendar)

    assert result.error == "Cookidoo ist gerade nicht erreichbar."
    assert len(result.failed) == 2  # r3 gescheitert, r4 nicht mehr versucht
    assert calendar.calls == []
    assert (d(2), "r1", d(2)) in _entries(session)  # Tellerplan-Seite übernommen


@pytest.mark.parametrize("offset", [-1, 15])
def test_days_outside_the_range_are_ignored_by_cookidoo(session: Session, offset: int) -> None:
    calendar = FakeCalendar((offset, "r1"))

    result = _sync(session, calendar)

    assert result.applied == []
    assert _entries(session) == []
