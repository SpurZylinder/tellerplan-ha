"""Abgleich mit „Meine Woche“ ausführen: Daten sammeln, Vorschau, Übernehmen.

Die Regeln stehen in `cookidoo_sync` (reine Logik); hier kommen Datenbank und Cookidoo
dazu. Cookidoo wird über die schmale Schnittstelle `CookidooCalendar` angesprochen, die
`cookidoo.CookidooAccount` erfüllt.

Reihenfolge und Fehler:
- Erst alle Schreibzugriffe auf Cookidoo, je Änderung einzeln. Nach dem ersten Fehler
  wird dort nichts mehr geschrieben (oft ist die Anmeldung abgelaufen); was geklappt
  hat, bleibt, der Rest kommt beim nächsten Abgleich erneut.
- Dann die Änderungen in Tellerplan; sie hängen nicht von den Schreibzugriffen ab.
- Verschieben in Cookidoo: erst am neuen Tag einplanen, dann am alten entfernen.
  Scheitert das Entfernen, bleibt eine Notiz – so geht nie ein Rezept verloren.
- Eine Notiz verschwindet erst, wenn das Entfernen in Cookidoo geklappt hat.

Festgeschrieben wird vom Aufrufer (`session.commit()`), wie in den übrigen Modulen.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from cookidoo import CalendarRecipe, CookidooError
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
    SyncPlan,
    plan_sync,
)
from modules.planner.models import CookidooRemoval, PlanEntry
from modules.planner.service import add_entry, delete_entry, move_entry, removals
from modules.recipes.models import COOKIDOO_SOURCE, Recipe
from modules.recipes.service import create_placeholder, find_recipe_by_source

COOKIDOO_CHANGES = (AddToCookidoo, MoveInCookidoo, RemoveFromCookidoo)


class CookidooCalendar(Protocol):
    """Was der Abgleich von Cookidoo braucht; Fehler kommen als `CookidooError`."""

    def read_calendar(self, first: date, last: date) -> list[CalendarRecipe]: ...

    def plan(self, day: date, recipe_ids: list[str]) -> None: ...

    def unplan(self, day: date, recipe_id: str) -> None: ...


@dataclass(frozen=True)
class SyncPreview:
    plan: SyncPlan
    # Für die Anzeige: Rezepttitel je Planeintrag und Rezeptname je Cookidoo-ID
    titles: dict[int, str]
    names: dict[str, str] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Kennung der Vorschau; ändert sich, sobald sich eine sichtbare Änderung ändert."""
        return hashlib.sha256(repr(self.plan.visible).encode("utf-8")).hexdigest()[:16]


@dataclass
class SyncResult:
    applied: list[Change] = field(default_factory=list)
    failed: list[Change] = field(default_factory=list)
    error: str | None = None
    # Neu angelegte Platzhalter (Rezept-IDs); der Aufrufer kann sie danach füllen
    placeholders: list[int] = field(default_factory=list)


def preview(session: Session, calendar: CookidooCalendar, first: date, last: date) -> SyncPreview:
    """Liest „Meine Woche“ und rechnet aus, was sich ändern würde; schreibt nichts."""
    entries = _entries(session, first, last)
    planned = [
        PlannedRecipe(
            entry.id,
            entry.day,
            entry.recipe.source_id if entry.recipe.source == COOKIDOO_SOURCE else None,
            entry.cookidoo_day,
        )
        for entry in entries
    ]
    cookidoo = [
        CalendarEntry(item.day, item.recipe_id, item.name, item.url)
        for item in calendar.read_calendar(first, last)
    ]
    notes = [RemovalNote(note.id, note.day, note.cookidoo_id) for note in removals(session)]
    plan = plan_sync(first, last, planned, cookidoo, notes, _known_ids(session))
    return SyncPreview(
        plan,
        titles={entry.id: entry.recipe.title for entry in entries},
        names={item.cookidoo_id: item.name for item in cookidoo},
    )


def apply(
    session: Session, calendar: CookidooCalendar, first: date, last: date, fingerprint: str
) -> SyncPreview | SyncResult:
    """Übernimmt den Abgleich – aber nur, wenn er noch der gezeigten Vorschau entspricht.

    Liest den Kalender dafür neu. Hat sich seitdem etwas geändert (z. B. in der
    Cookidoo-App), kommt die neue Vorschau zurück und nichts wird geschrieben.
    """
    current = preview(session, calendar, first, last)
    if current.fingerprint != fingerprint:
        return current
    return _execute(session, calendar, current.plan.changes)


def _entries(session: Session, first: date, last: date) -> list[PlanEntry]:
    """Einträge im Zeitraum und solche, die dort zuletzt in Cookidoo standen."""
    statement = (
        select(PlanEntry)
        .where(
            or_(
                PlanEntry.day.between(first, last),
                PlanEntry.cookidoo_day.between(first, last),
            )
        )
        .options(selectinload(PlanEntry.recipe))
        .order_by(PlanEntry.day, PlanEntry.id)
    )
    return list(session.scalars(statement))


def _known_ids(session: Session) -> set[str]:
    statement = select(Recipe.source_id).where(
        Recipe.source == COOKIDOO_SOURCE, Recipe.source_id.is_not(None)
    )
    return {source_id for source_id in session.scalars(statement) if source_id}


def _execute(session: Session, calendar: CookidooCalendar, changes: Sequence[Change]) -> SyncResult:
    result = SyncResult()
    for change in changes:
        if not isinstance(change, COOKIDOO_CHANGES):
            continue
        if result.error is not None:
            result.failed.append(change)
            continue
        try:
            _write_cookidoo(session, calendar, change)
        except CookidooError as error:
            result.error = str(error)
            result.failed.append(change)
        else:
            result.applied.append(change)

    recipes: dict[str, Recipe] = {}
    for change in changes:
        if not isinstance(change, COOKIDOO_CHANGES):
            _write_tellerplan(session, change, recipes, result.placeholders)
            result.applied.append(change)
    session.flush()
    return result


def _write_cookidoo(session: Session, calendar: CookidooCalendar, change: Change) -> None:
    match change:
        case AddToCookidoo(entry_id=entry_id, day=day, cookidoo_id=cookidoo_id):
            calendar.plan(day, [cookidoo_id])
            _entry(session, entry_id).cookidoo_day = day
        case MoveInCookidoo(entry_id=entry_id, from_day=from_day, to_day=to_day, cookidoo_id=rid):
            calendar.plan(to_day, [rid])
            _entry(session, entry_id).cookidoo_day = to_day
            try:
                calendar.unplan(from_day, rid)
            except CookidooError:
                # Am neuen Tag steht es schon; das Entfernen am alten holt der nächste Lauf nach
                session.add(CookidooRemoval(day=from_day, cookidoo_id=rid))
                raise
        case RemoveFromCookidoo(day=day, cookidoo_id=rid, entry_id=entry_id, note_id=note_id):
            calendar.unplan(day, rid)
            if entry_id is not None:
                _entry(session, entry_id).cookidoo_day = None
            if note_id is not None:
                _drop_note(session, note_id)


def _write_tellerplan(
    session: Session, change: Change, recipes: dict[str, Recipe], created: list[int]
) -> None:
    match change:
        case AddToTellerplan(day=day, cookidoo_id=rid, name=name, url=url):
            recipe = _recipe_for(session, rid, name, url, recipes, created)
            add_entry(session, day, recipe).cookidoo_day = day
        case MoveInTellerplan(entry_id=entry_id, to_day=to_day):
            entry = move_entry(session, _entry(session, entry_id), to_day)
            entry.cookidoo_day = to_day
        case DeleteFromTellerplan(entry_id=entry_id):
            entry = _entry(session, entry_id)
            entry.cookidoo_day = None  # in Cookidoo schon weg: keine Notiz hinterlassen
            delete_entry(session, entry)
        case MarkSynced(entry_id=entry_id, day=day):
            _entry(session, entry_id).cookidoo_day = day
        case DropNote(note_id=note_id):
            _drop_note(session, note_id)


def _recipe_for(
    session: Session,
    cookidoo_id: str,
    name: str,
    url: str,
    recipes: dict[str, Recipe],
    created: list[int],
) -> Recipe:
    """Vorhandenes Rezept zur Cookidoo-ID oder ein Platzhalter (je ID nur einmal)."""
    if cookidoo_id not in recipes:
        recipe = find_recipe_by_source(session, COOKIDOO_SOURCE, cookidoo_id)
        if recipe is None:
            recipe = create_placeholder(session, cookidoo_id, name, url)
            created.append(recipe.id)
        recipes[cookidoo_id] = recipe
    return recipes[cookidoo_id]


def _entry(session: Session, entry_id: int) -> PlanEntry:
    entry = session.get(PlanEntry, entry_id)
    if entry is None:
        raise LookupError(f"Planeintrag {entry_id} fehlt")
    return entry


def _drop_note(session: Session, note_id: int) -> None:
    note = session.get(CookidooRemoval, note_id)
    if note is not None:
        session.delete(note)
