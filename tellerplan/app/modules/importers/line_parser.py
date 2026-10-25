"""Zeilenparser: „350 g Brokkoliröschen“ → Menge 350, Einheit g, Name Brokkoliröschen.

Erkennt Brüche (½, 1 ½, 1/2), Bereiche („550 - 600 g“ → Mittelwert),
Zusätze wie „geh.“ und Angaben in Klammern oder nach einem Komma als Notiz.
Einheiten werden vereinheitlicht („Prisen“ → „Prise“, „Pck.“ → „Packung“), damit
sie zu den Einheiten am Lebensmittel passen. Eine Menge ohne Einheit („2 Zwiebeln“)
bekommt „Stück“ – nie Gramm. Zeilen ohne Menge („Salz“, „Öl zum Braten“) bleiben
ohne Menge und Einheit.
"""

import re
from dataclasses import dataclass

from modules.recipes.service import alias_key

COUNT_UNIT = "Stück"

# Schreibweise im Text (klein) → einheitliche Einheit
UNITS = {
    "g": "g",
    "gramm": "g",
    "kg": "kg",
    "ml": "ml",
    "l": "l",
    "liter": "l",
    "tl": "TL",
    "el": "EL",
    "prise": "Prise",
    "prisen": "Prise",
    "msp.": "Msp.",
    "messerspitze": "Msp.",
    "bund": "Bund",
    "stängel": "Stängel",
    "dose": "Dose",
    "dosen": "Dose",
    "würfel": "Würfel",
    "kugel": "Kugel",
    "kugeln": "Kugel",
    "scheibe": "Scheibe",
    "scheiben": "Scheibe",
    "pck.": "Packung",
    "päckchen": "Packung",
    "packung": "Packung",
    "packungen": "Packung",
    "zweig": "Zweig",
    "zweige": "Zweig",
    "zweigchen": "Zweig",
    "blatt": "Blatt",
    "blätter": "Blatt",
    "glas": "Glas",
    "gläser": "Glas",
    "einmachglas": "Glas",
    "flasche": "Flasche",
    "flaschen": "Flasche",
    "becher": "Becher",
    "tasse": "Tasse",
    "tassen": "Tasse",
    "cm": "cm",
    "spritzer": "Spritzer",
    "handvoll": "Handvoll",
    "stück": COUNT_UNIT,
    "stk.": COUNT_UNIT,
}
# Zusätze zwischen Menge und Einheit, die als Notiz erhalten bleiben
MODIFIERS = ("geh.", "gestr.", "knapp", "gut", "ca.", "etwa")
FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}

_FRACTION_CHARS = "".join(FRACTIONS)
_NUMBER = rf"\d+(?:[.,]\d+)?(?:\s*[{_FRACTION_CHARS}])?|\d+/\d+|[{_FRACTION_CHARS}]"
_QUANTITY = re.compile(rf"^\s*(?P<low>{_NUMBER})(?:\s*[-–]\s*(?P<high>{_NUMBER}))?\s+")
_PARENTHESES = re.compile(r"\s*\(([^)]*)\)")
# Komma als Trenner nur mit folgendem Leerzeichen, nicht in „3,5 %“
_NOTE_COMMA = re.compile(r",(?=\s|$)")


@dataclass(frozen=True)
class ParsedLine:
    quantity: float | None
    unit: str | None
    name: str
    note: str | None

    @property
    def key(self) -> str:
        """Schlüssel zum Zuordnen und Lernen: Name klein, Leerraum vereinheitlicht."""
        return alias_key(self.name)


def _number(text: str) -> float:
    text = text.strip()
    if "/" in text:
        numerator, denominator = text.split("/")
        return int(numerator) / int(denominator)
    fraction = FRACTIONS.get(text[-1], 0.0)
    whole = text[:-1].strip() if fraction else text
    return (float(whole.replace(",", ".")) if whole else 0.0) + fraction


def _split_quantity(text: str) -> tuple[float | None, str]:
    match = _QUANTITY.match(text)
    if not match:
        return None, text.strip()
    low = _number(match.group("low"))
    high = _number(match.group("high")) if match.group("high") else low
    return (low + high) / 2, text[match.end() :]


def _take_modifiers(text: str) -> tuple[list[str], str]:
    found = []
    words = text.split()
    while words and words[0].casefold() in MODIFIERS:
        found.append(words.pop(0))
    return found, " ".join(words)


def _take_unit(text: str) -> tuple[str | None, str]:
    first, _, rest = text.partition(" ")
    unit = UNITS.get(first.casefold().rstrip(","))
    if unit is None or not rest:
        return None, text
    return unit, rest


def _split_note(text: str) -> tuple[str, list[str]]:
    notes = [note.strip() for note in _PARENTHESES.findall(text) if note.strip()]
    text = _PARENTHESES.sub("", text)
    name, *after_comma = _NOTE_COMMA.split(text, maxsplit=1)
    if after_comma and after_comma[0].strip():
        notes.append(after_comma[0].strip())
    return " ".join(name.split()), notes


def parse_line(text: str) -> ParsedLine:
    """Zerlegt eine Zutatenzeile; der Originaltext bleibt beim Aufrufer erhalten."""
    quantity, rest = _split_quantity(" ".join(text.split()))
    modifiers, rest = _take_modifiers(rest)
    unit = None
    if quantity is not None:
        unit, rest = _take_unit(rest)
        unit = unit or COUNT_UNIT
    name, notes = _split_note(rest)
    note = ", ".join(modifiers + notes) or None
    return ParsedLine(quantity=quantity, unit=unit, name=name or text.strip(), note=note)
