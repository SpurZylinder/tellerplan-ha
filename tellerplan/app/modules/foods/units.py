"""Einheiten: eine Schreibweise je Einheit und Umrechnung auf eine Grundeinheit.

Zeilenparser und Einkaufsliste nutzen dasselbe Verzeichnis, damit „EL“ und „el“,
„Stück“ und „Stk.“ oder „g“ und „gr“ überall dieselbe Einheit sind (Befund K10).
"""

COUNT_UNIT = "Stück"

# Schreibweise (klein) → einheitliche Einheit
UNIT_SPELLINGS = {
    "g": "g",
    "gr": "g",
    "gr.": "g",
    "gramm": "g",
    "kg": "kg",
    "kilogramm": "kg",
    "ml": "ml",
    "milliliter": "ml",
    "l": "l",
    "liter": "l",
    "tl": "TL",
    "tl.": "TL",
    "teelöffel": "TL",
    "el": "EL",
    "el.": "EL",
    "esslöffel": "EL",
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
    "pck": "Packung",
    "pkg.": "Packung",
    "pkg": "Packung",
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
    "stk": COUNT_UNIT,
    "stck.": COUNT_UNIT,
    "stck": COUNT_UNIT,
}

# Einheiten, die sich ohne Lebensmittel umrechnen lassen: Einheit → (Grundeinheit, Faktor)
BASE_UNITS = {"kg": ("g", 1000.0), "l": ("ml", 1000.0)}
# Ab dieser Menge in der Grundeinheit wird wieder die größere Einheit gezeigt
LARGER_UNITS = {"g": ("kg", 1000.0), "ml": ("l", 1000.0)}


def canonical_unit(text: str) -> str:
    """Einheitliche Schreibweise; eine unbekannte Einheit bleibt, wie sie ist."""
    cleaned = text.strip()
    return UNIT_SPELLINGS.get(cleaned.casefold(), cleaned)


def to_base_unit(quantity: float, unit: str) -> tuple[float, str]:
    """Menge in der Grundeinheit, z. B. (1.5, „kg“) → (1500, „g“); sonst unverändert."""
    canonical = canonical_unit(unit)
    base, factor = BASE_UNITS.get(canonical, (canonical, 1.0))
    return quantity * factor, base


def to_display_unit(quantity: float, unit: str) -> tuple[float, str]:
    """Große Mengen in der größeren Einheit, z. B. (1500, „g“) → (1.5, „kg“)."""
    larger, factor = LARGER_UNITS.get(unit, (unit, 1.0))
    if larger != unit and quantity >= factor:
        return quantity / factor, larger
    return quantity, unit
