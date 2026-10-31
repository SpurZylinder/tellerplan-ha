"""Import von Lebensmitteln im Format „tellerplan-foods“ (z. B. aus tools/rewe_fetch.py).

Anders als Rezeptentwürfe bringen Lebensmittel ihre Nährwerte mit: `foods` ist die
einzige Stelle mit Nährwerten (Regel 1), externe Lebensmitteldaten kommen nur hierüber.

Ein Produkt wird zuerst am Barcode wiedererkannt (dasselbe Produkt aus REWE und Open
Food Facts nur einmal), sonst an Quelle und Quell-ID. Ein erneuter Import aktualisiert
Name, Hersteller, Packung und Nährwerte; Kurzname und Einheiten von Hand bleiben.

Angaben je 100 ml (Getränke, Milch) werden wie je 100 g gespeichert; dazu bekommt das
Produkt die Einheiten „ml“ (1 ml = 1 g) und „l“, damit „200 ml Milch“ genau mit den
Werten der Packung rechnet. Aus der Packungsgröße entsteht die Einheit „Packung“.
"""

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.foods.models import Food, FoodSource, FoodUnit

FORMAT = "tellerplan-foods"
FORMAT_VERSION = 1
REQUIRED = ("kcal", "protein_g", "fat_g", "carbs_g")
OPTIONAL = ("fiber_g", "sugar_g", "salt_g")
SOURCES = {source.value: source for source in (FoodSource.REWE, FoodSource.OFF, FoodSource.CUSTOM)}
VOLUME_BASIS = "100 ml"
# Einheit der Packungsgröße → Gramm (Flüssigkeiten: 1 ml ≈ 1 g, passend zu „je 100 ml“)
PACKAGE_UNITS = {"g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0}
PACKAGE_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|l)\b", re.IGNORECASE)
PACKAGE_UNIT = "Packung"


class FoodImportError(ValueError):
    """Die Datei ist kein gültiger Lebensmittelexport für Tellerplan."""


@dataclass(frozen=True)
class FoodImportResult:
    created: int
    updated: int
    skipped: list[str]


def is_food_document(document: object) -> bool:
    return isinstance(document, dict) and document.get("format") == FORMAT


def _number(entry: dict[str, Any], key: str) -> float | None:
    value = entry.get(key)
    return float(value) if isinstance(value, int | float) else None


def _existing(session: Session, source: FoodSource, entry: dict[str, Any]) -> Food | None:
    barcode = entry.get("barcode")
    if barcode:
        found = session.scalar(select(Food).where(Food.barcode == barcode))
        if found is not None:
            return found
    return session.scalar(
        select(Food).where(Food.source == source, Food.source_id == entry["source_id"])
    )


def package_grams(package: str | None) -> float | None:
    """„1l“ → 1000, „200 g“ → 200, „0,5 kg“ → 500; None, wenn nicht lesbar („2 Stück“)."""
    match = PACKAGE_PATTERN.match(package or "")
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    return amount * PACKAGE_UNITS[match.group(2).lower()]


def _ensure_unit(food: Food, name: str, grams: float) -> None:
    """Einheit anlegen, falls es sie noch nicht gibt (von Hand gepflegte bleiben)."""
    if not any(unit.name.casefold() == name.casefold() for unit in food.units):
        food.units.append(FoodUnit(name=name, grams=grams))


def _units(entry: dict[str, Any]) -> list[tuple[str, float]]:
    """Mitgebrachte Einheiten; unvollständige Angaben werden übergangen."""
    units = entry.get("units")
    if not isinstance(units, list):
        return []
    valid = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        name, grams = unit.get("name"), _number(unit, "grams")
        if isinstance(name, str) and name.strip() and grams is not None and grams > 0:
            valid.append((name.strip(), grams))
    return valid


def _apply(food: Food, entry: dict[str, Any]) -> None:
    food.name = entry["name"].strip()
    food.brand = entry.get("brand") or None
    food.barcode = entry.get("barcode") or None
    food.package = entry.get("package") or None
    for key in (*REQUIRED, *OPTIONAL):
        setattr(food, key, _number(entry, key))
    if entry.get("basis") == VOLUME_BASIS:
        _ensure_unit(food, "ml", 1.0)
        _ensure_unit(food, "l", 1000.0)
    if (grams := package_grams(food.package)) is not None:
        _ensure_unit(food, PACKAGE_UNIT, grams)
    for name, unit_grams in _units(entry):
        _ensure_unit(food, name, unit_grams)


def _problem(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return "kein JSON-Objekt"
    if not isinstance(entry.get("name"), str) or not entry["name"].strip():
        return "Name fehlt"
    if not entry.get("source_id"):
        return f"{entry['name']}: Quell-ID fehlt"
    if entry.get("source") not in SOURCES:
        return f"{entry['name']}: unbekannte Quelle {entry.get('source')!r}"
    missing = [key for key in REQUIRED if _number(entry, key) is None]
    if missing:
        return f"{entry['name']}: Nährwerte fehlen ({', '.join(missing)})"
    return None


def import_foods(session: Session, document: object) -> FoodImportResult:
    """Legt Lebensmittel an oder aktualisiert sie; der Aufrufer schreibt fest."""
    if not is_food_document(document):
        raise FoodImportError(f"Unbekanntes Format, erwartet „{FORMAT}“.")
    assert isinstance(document, dict)
    if document.get("version") != FORMAT_VERSION:
        raise FoodImportError("Diese Version wird nicht unterstützt.")
    entries = document.get("foods")
    if not isinstance(entries, list):
        raise FoodImportError("Die Liste der Lebensmittel fehlt.")

    created = updated = 0
    skipped: list[str] = []
    for entry in entries:
        if problem := _problem(entry):
            skipped.append(problem)
            continue
        source = SOURCES[entry["source"]]
        food = _existing(session, source, entry)
        if food is None:
            food = Food(source=source, source_id=str(entry["source_id"]), units=[])
            session.add(food)
            created += 1
        else:
            updated += 1
        _apply(food, entry)
        session.flush()
    return FoodImportResult(created=created, updated=updated, skipped=skipped)
