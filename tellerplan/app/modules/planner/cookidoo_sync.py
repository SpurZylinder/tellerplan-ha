"""Abgleich des Plans mit „Meine Woche“ in Cookidoo – als reine Logik.

Kein Netzwerk, keine Datenbank: `plan_sync` bekommt Planeinträge, Kalendereinträge und
Notizen und liefert die nötigen Änderungen. Ausgeführt werden sie woanders (Schritt 5);
so lässt sich jede Regel ohne Cookidoo testen. Die Regeln stehen in docs/Cookidoo-Sync.md.

Schlüssel ist die Cookidoo-ID eines Rezepts. Jeder Planeintrag merkt sich den Tag, an dem
er beim letzten Abgleich in Cookidoo stand (`cookidoo_day`, die Basis). Daran erkennt der
Abgleich, wer verschoben hat:

- Planeintrag und Cookidoo am selben Tag → nichts zu tun.
- Tellerplan hat verschoben (Cookidoo steht noch auf der Basis) → in Cookidoo verschieben.
- Sonst hat Cookidoo verschoben oder beide → Cookidoo gewinnt, Tellerplan folgt.
- Abgeglichen, aber in Cookidoo fehlt er → dort entfernt, also in Tellerplan löschen.
- Nie abgeglichen → in Cookidoo einplanen; nur in Cookidoo → in Tellerplan anlegen
  (als Platzhalter, wenn Tellerplan das Rezept nicht kennt).

Portionen ändert der Abgleich nie; vergangene Tage bleiben unberührt.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

# --- Eingaben ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedRecipe:
    """Ein Planeintrag, so weit der Abgleich ihn braucht."""

    entry_id: int
    day: date
    # None: Rezept ohne Cookidoo-ID, bleibt nur in Tellerplan
    cookidoo_id: str | None
    # Tag beim letzten Abgleich; None = nie abgeglichen
    cookidoo_day: date | None


@dataclass(frozen=True)
class CalendarEntry:
    """Ein Rezept in „Meine Woche“."""

    day: date
    cookidoo_id: str
    name: str
    url: str


@dataclass(frozen=True)
class RemovalNote:
    """In Tellerplan gelöscht, in Cookidoo noch zu entfernen."""

    note_id: int
    day: date
    cookidoo_id: str


# --- Änderungen -------------------------------------------------------------------------


@dataclass(frozen=True)
class AddToTellerplan:
    day: date
    cookidoo_id: str
    name: str
    url: str
    # Tellerplan kennt das Rezept nicht: Platzhalter anlegen
    placeholder: bool


@dataclass(frozen=True)
class MoveInTellerplan:
    entry_id: int
    from_day: date
    to_day: date


@dataclass(frozen=True)
class DeleteFromTellerplan:
    entry_id: int
    day: date


@dataclass(frozen=True)
class AddToCookidoo:
    entry_id: int
    day: date
    cookidoo_id: str


@dataclass(frozen=True)
class MoveInCookidoo:
    entry_id: int
    from_day: date
    to_day: date
    cookidoo_id: str


@dataclass(frozen=True)
class RemoveFromCookidoo:
    day: date
    cookidoo_id: str
    # Eintrag, dessen Basis danach leer wird (in die Vergangenheit verschoben); sonst None
    entry_id: int | None = None


@dataclass(frozen=True)
class MarkSynced:
    """Intern: Planeintrag steht schon richtig, nur die Basis setzen."""

    entry_id: int
    day: date


@dataclass(frozen=True)
class DropNote:
    """Intern: Notiz ist erledigt."""

    note_id: int


Change = (
    AddToTellerplan
    | MoveInTellerplan
    | DeleteFromTellerplan
    | AddToCookidoo
    | MoveInCookidoo
    | RemoveFromCookidoo
    | MarkSynced
    | DropNote
)
INTERNAL = (MarkSynced, DropNote)


@dataclass(frozen=True)
class SyncPlan:
    changes: list[Change] = field(default_factory=list)

    @property
    def visible(self) -> list[Change]:
        """Änderungen für die Vorschau (ohne interne Buchführung)."""
        return [change for change in self.changes if not isinstance(change, INTERNAL)]

    @property
    def in_sync(self) -> bool:
        return not self.visible


# --- Abgleich ---------------------------------------------------------------------------


def plan_sync(
    first: date,
    last: date,
    planned: Iterable[PlannedRecipe],
    calendar: Iterable[CalendarEntry],
    notes: Iterable[RemovalNote],
    known_ids: set[str],
) -> SyncPlan:
    """Änderungen für den Zeitraum `first`–`last` (heute bis Ende des Plans).

    `calendar` muss den ganzen Zeitraum abdecken; ein Tag ohne Eintrag gilt als leer.
    `known_ids` sind die Cookidoo-IDs, zu denen Tellerplan ein Rezept hat.
    """
    in_range = _InRange(first, last)
    planned_by_id: dict[str, list[PlannedRecipe]] = defaultdict(list)
    for item in planned:
        # Mit zählt, was im Zeitraum liegt oder dort zuletzt in Cookidoo stand
        if item.cookidoo_id and (in_range(item.day) or in_range(item.cookidoo_day)):
            planned_by_id[item.cookidoo_id].append(item)
    calendar_by_id: dict[str, list[CalendarEntry]] = defaultdict(list)
    for entry in calendar:
        if in_range(entry.day):
            calendar_by_id[entry.cookidoo_id].append(entry)
    notes_by_id: dict[str, list[RemovalNote]] = defaultdict(list)
    changes: list[Change] = []
    for note in notes:
        if note.day < first:
            changes.append(DropNote(note.note_id))  # Vergangenheit bleibt unberührt
        elif in_range(note.day):
            notes_by_id[note.cookidoo_id].append(note)
        # nach dem Zeitraum: liegen lassen, der Kalender dort ist nicht gelesen

    for cookidoo_id in sorted(planned_by_id.keys() | calendar_by_id.keys() | notes_by_id.keys()):
        changes += _sync_recipe(
            cookidoo_id,
            sorted(planned_by_id[cookidoo_id], key=lambda item: (item.day, item.entry_id)),
            sorted(calendar_by_id[cookidoo_id], key=lambda entry: entry.day),
            notes_by_id[cookidoo_id],
            cookidoo_id in known_ids,
            in_range,
        )
    return SyncPlan(changes)


@dataclass(frozen=True)
class _InRange:
    first: date
    last: date

    def __call__(self, day: date | None) -> bool:
        return day is not None and self.first <= day <= self.last

    def past(self, day: date) -> bool:
        """Vor dem Zeitraum: dort wird nichts mehr geändert. Nach dem Zeitraum darf
        Cookidoo dagegen beschrieben werden (z. B. in drei Wochen verschoben)."""
        return day < self.first


def _take(entries: list[CalendarEntry], day: date) -> CalendarEntry | None:
    """Nimmt einen Kalendereintrag dieses Tages aus der Liste (jeder zählt nur einmal)."""
    for index, entry in enumerate(entries):
        if entry.day == day:
            return entries.pop(index)
    return None


def _sync_recipe(
    cookidoo_id: str,
    planned: list[PlannedRecipe],
    calendar: list[CalendarEntry],
    notes: list[RemovalNote],
    known: bool,
    in_range: _InRange,
) -> list[Change]:
    changes: list[Change] = []
    open_calendar = list(calendar)
    open_planned: list[PlannedRecipe] = []

    # 1. Gleicher Tag auf beiden Seiten: stimmt schon
    for item in planned:
        if in_range(item.day) and _take(open_calendar, item.day) is not None:
            if item.cookidoo_day != item.day:
                changes.append(MarkSynced(item.entry_id, item.day))
        else:
            open_planned.append(item)

    # 2. Tellerplan hat verschoben: Cookidoo steht noch auf der Basis
    remaining: list[PlannedRecipe] = []
    for item in open_planned:
        base = item.cookidoo_day
        if base is not None and in_range(base) and _take(open_calendar, base) is not None:
            if in_range.past(item.day):  # nicht gekocht, zurückgelegt: nicht mehr abgleichen
                changes.append(RemoveFromCookidoo(base, cookidoo_id, item.entry_id))
            else:
                changes.append(MoveInCookidoo(item.entry_id, base, item.day, cookidoo_id))
        else:
            remaining.append(item)

    # 3. Notizen: in Tellerplan gelöscht → in Cookidoo entfernen, falls noch da
    for note in notes:
        if _take(open_calendar, note.day) is not None:
            changes.append(RemoveFromCookidoo(note.day, cookidoo_id))
        changes.append(DropNote(note.note_id))

    # 4. Abgeglichene Einträge ohne Gegenstück an Basis oder Tag: Cookidoo hat verschoben
    #    (Cookidoo gewinnt) oder entfernt (in Tellerplan löschen)
    unsynced: list[PlannedRecipe] = []
    for item in remaining:
        base = item.cookidoo_day
        if base is None or not in_range(base):
            unsynced.append(item)  # nie abgeglichen oder Basis außerhalb: wie neu
        elif in_range.past(item.day):
            pass  # in die Vergangenheit verschoben und in Cookidoo schon entfernt
        elif open_calendar:
            target = min(open_calendar, key=lambda entry: (abs((entry.day - base).days), entry.day))
            open_calendar.remove(target)
            changes.append(MoveInTellerplan(item.entry_id, item.day, target.day))
        else:
            changes.append(DeleteFromTellerplan(item.entry_id, item.day))

    # 5. Nur in Tellerplan → in Cookidoo einplanen
    for item in unsynced:
        if not in_range.past(item.day):
            changes.append(AddToCookidoo(item.entry_id, item.day, cookidoo_id))

    # 6. Nur in Cookidoo → in Tellerplan anlegen
    for entry in open_calendar:
        changes.append(
            AddToTellerplan(entry.day, cookidoo_id, entry.name, entry.url, placeholder=not known)
        )
    return changes
