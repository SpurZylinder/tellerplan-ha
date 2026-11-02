"""Abgleich mit „Meine Woche“ als reine Logik: eine Zeile je Regel aus docs/Cookidoo-Sync.md."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from modules.planner.cookidoo_sync import (
    AddToCookidoo,
    AddToTellerplan,
    CalendarEntry,
    Change,
    DeleteFromTellerplan,
    DropNote,
    MarkSynced,
    MoveInCookidoo,
    MoveInTellerplan,
    PlannedRecipe,
    RemovalNote,
    RemoveFromCookidoo,
    plan_sync,
)

FIRST = date(2026, 11, 2)
LAST = FIRST + timedelta(days=14)
RID = "r821223"


def d(offset: int) -> date:
    """Tag relativ zu heute (`FIRST`)."""
    return FIRST + timedelta(days=offset)


def planned(
    entry_id: int, day: int, base: int | None = None, rid: str | None = RID
) -> PlannedRecipe:
    return PlannedRecipe(entry_id, d(day), rid, None if base is None else d(base))


def cal(day: int, rid: str = RID) -> CalendarEntry:
    return CalendarEntry(d(day), rid, "Linsen-Dal", f"https://cookidoo.de/{rid}")


def note(note_id: int, day: int, rid: str = RID) -> RemovalNote:
    return RemovalNote(note_id, d(day), rid)


CASES: list[
    tuple[str, list[PlannedRecipe], list[CalendarEntry], list[RemovalNote], list[Change]]
] = [
    ("gleicher Tag, abgeglichen", [planned(1, 2, 2)], [cal(2)], [], []),
    ("gleicher Tag, neu", [planned(1, 2)], [cal(2)], [], [MarkSynced(1, d(2))]),
    (
        "nur in Cookidoo",
        [],
        [cal(3)],
        [],
        [AddToTellerplan(d(3), RID, "Linsen-Dal", f"https://cookidoo.de/{RID}", placeholder=False)],
    ),
    ("nur in Tellerplan, nie abgeglichen", [planned(1, 2)], [], [], [AddToCookidoo(1, d(2), RID)]),
    (
        "Cookidoo hat verschoben",
        [planned(1, 1, 1)],
        [cal(3)],
        [],
        [MoveInTellerplan(1, d(1), d(3))],
    ),
    (
        "Tellerplan hat verschoben",
        [planned(1, 3, 1)],
        [cal(1)],
        [],
        [MoveInCookidoo(1, d(1), d(3), RID)],
    ),
    (
        "beide verschoben, Cookidoo gewinnt",
        [planned(1, 3, 1)],
        [cal(5)],
        [],
        [MoveInTellerplan(1, d(3), d(5))],
    ),
    ("in Cookidoo entfernt", [planned(1, 2, 2)], [], [], [DeleteFromTellerplan(1, d(2))]),
    (
        "in Tellerplan gelöscht",
        [],
        [cal(2)],
        [note(7, 2)],
        [RemoveFromCookidoo(d(2), RID), DropNote(7)],
    ),
    ("gelöscht, in Cookidoo auch schon weg", [], [], [note(7, 2)], [DropNote(7)]),
    ("Rezept ohne Cookidoo-ID", [planned(1, 2, rid=None)], [], [], []),
    (
        "vergangene Tage bleiben unberührt",
        [planned(1, -1)],
        [cal(-1)],
        [note(7, -2)],
        [DropNote(7)],
    ),
    (
        "in die Vergangenheit verschoben",
        [planned(1, -1, 2)],
        [cal(2)],
        [],
        [RemoveFromCookidoo(d(2), RID, entry_id=1)],
    ),
    (
        "über das Planende hinaus verschoben",
        [planned(1, 20, 2)],
        [cal(2)],
        [],
        [MoveInCookidoo(1, d(2), d(20), RID)],
    ),
    ("Notiz nach dem Zeitraum bleibt liegen", [], [], [note(7, 20)], []),
    (
        "Basis in der Vergangenheit gilt als neu",
        [planned(1, 2, -3)],
        [],
        [],
        [AddToCookidoo(1, d(2), RID)],
    ),
    (
        "zwei neue Mahlzeiten an verschiedenen Tagen",
        [planned(1, 1)],
        [cal(3)],
        [],
        [
            AddToCookidoo(1, d(1), RID),
            AddToTellerplan(
                d(3), RID, "Linsen-Dal", f"https://cookidoo.de/{RID}", placeholder=False
            ),
        ],
    ),
    (
        "doppeltes Rezept: eines bleibt, eines verschoben",
        [planned(1, 1, 1), planned(2, 4, 4)],
        [cal(1), cal(5)],
        [],
        [MoveInTellerplan(2, d(4), d(5))],
    ),
    (
        "doppeltes Rezept am selben Tag",
        [planned(1, 2, 2), planned(2, 2, 2)],
        [cal(2)],
        [],
        [DeleteFromTellerplan(2, d(2))],
    ),
]


@pytest.mark.parametrize(
    ("planned_items", "calendar", "notes", "expected"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_rules(
    planned_items: list[PlannedRecipe],
    calendar: list[CalendarEntry],
    notes: list[RemovalNote],
    expected: list[Change],
) -> None:
    result = plan_sync(FIRST, LAST, planned_items, calendar, notes, known_ids={RID})

    assert result.changes == expected


def test_unknown_recipe_becomes_a_placeholder() -> None:
    result = plan_sync(FIRST, LAST, [], [cal(3, "r999")], [], known_ids={RID})

    (change,) = result.changes
    assert isinstance(change, AddToTellerplan)
    assert change.placeholder


def test_internal_bookkeeping_is_not_shown() -> None:
    result = plan_sync(FIRST, LAST, [planned(1, 2)], [cal(2)], [note(7, 3)], known_ids={RID})

    assert result.in_sync
    assert result.visible == []
    assert len(result.changes) == 2  # Basis setzen, Notiz löschen


def test_several_recipes_are_handled_independently() -> None:
    result = plan_sync(
        FIRST,
        LAST,
        [planned(1, 1, 1, rid="r1"), planned(2, 2, rid="r2")],
        [cal(3, "r1")],
        [],
        known_ids={"r1", "r2"},
    )

    assert result.changes == [MoveInTellerplan(1, d(1), d(3)), AddToCookidoo(2, d(2), "r2")]


def test_cookidoo_move_picks_the_nearest_day_to_the_base() -> None:
    result = plan_sync(FIRST, LAST, [planned(1, 4, 4)], [cal(1), cal(5)], [], known_ids={RID})

    assert result.changes[0] == MoveInTellerplan(1, d(4), d(5))
    assert isinstance(result.changes[1], AddToTellerplan)
    assert result.changes[1].day == d(1)


def _apply(
    changes: list[Change],
    planned_items: list[PlannedRecipe],
    calendar: list[CalendarEntry],
    notes: list[RemovalNote],
) -> tuple[list[PlannedRecipe], list[CalendarEntry], list[RemovalNote]]:
    """Spielt die Änderungen so nach, wie Schritt 5 sie ausführen soll."""
    items = {item.entry_id: item for item in planned_items}
    days = list(calendar)
    open_notes = list(notes)

    def set_item(entry_id: int, **values: date | None) -> None:
        items[entry_id] = replace(items[entry_id], **values)

    def remove_day(day: date, rid: str) -> None:
        days.remove(next(entry for entry in days if entry.day == day and entry.cookidoo_id == rid))

    for change in changes:
        match change:
            case AddToTellerplan(day=day, cookidoo_id=rid):
                new_id = max(items, default=0) + 1
                items[new_id] = PlannedRecipe(new_id, day, rid, day)
            case MoveInTellerplan(entry_id=entry_id, to_day=to_day):
                set_item(entry_id, day=to_day, cookidoo_day=to_day)
            case DeleteFromTellerplan(entry_id=entry_id):
                del items[entry_id]
            case AddToCookidoo(entry_id=entry_id, day=day, cookidoo_id=rid):
                days.append(CalendarEntry(day, rid, "", ""))
                set_item(entry_id, cookidoo_day=day)
            case MoveInCookidoo(
                entry_id=entry_id, from_day=from_day, to_day=to_day, cookidoo_id=rid
            ):
                remove_day(from_day, rid)
                days.append(CalendarEntry(to_day, rid, "", ""))
                set_item(entry_id, cookidoo_day=to_day)
            case RemoveFromCookidoo(day=day, cookidoo_id=rid, entry_id=entry_id):
                remove_day(day, rid)
                if entry_id is not None:
                    set_item(entry_id, cookidoo_day=None)
            case MarkSynced(entry_id=entry_id, day=day):
                set_item(entry_id, cookidoo_day=day)
            case DropNote(note_id=note_id):
                open_notes = [n for n in open_notes if n.note_id != note_id]
    return list(items.values()), days, open_notes


@pytest.mark.parametrize(
    ("planned_items", "calendar", "notes"),
    [case[1:4] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_second_sync_finds_nothing(
    planned_items: list[PlannedRecipe],
    calendar: list[CalendarEntry],
    notes: list[RemovalNote],
) -> None:
    first = plan_sync(FIRST, LAST, planned_items, calendar, notes, known_ids={RID})
    state = _apply(first.changes, planned_items, calendar, notes)

    second = plan_sync(FIRST, LAST, *state, known_ids={RID})

    assert second.changes == []
