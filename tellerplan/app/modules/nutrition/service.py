"""Menge + Einheit → Gramm → Nährwerte. Einzige Stelle, an der gerechnet wird.

Standard-Einheiten (z. B. 1 EL = 15 g) gelten für jedes Lebensmittel ohne eigene
Angabe. Sie kommen aus den Einstellungen und werden beim Start der App einmal mit
`set_standard_units` gesetzt; eine Einheit am Lebensmittel geht immer vor.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields

from modules.foods.models import Food

GRAMS_PER_100 = 100.0
# Feste Masseneinheiten; alle anderen Einheiten kommen aus food_unit.
MASS_UNITS_IN_GRAMS = {"g": 1.0, "gramm": 1.0, "kg": 1000.0}
# Behälter, die ohne eigene Angabe genau eine Packung des Produkts sind („1 Dose Kokosmilch“)
PACKAGE_UNIT = "packung"
CONTAINER_UNITS = {"dose", "glas", "flasche", "becher", "beutel", "tüte", "schale", "tube"}

# Einheit (klein geschrieben) → (Schreibweise, Gramm); gesetzt aus den Einstellungen
_standard_units: dict[str, tuple[str, float]] = {}


@dataclass(frozen=True)
class Nutrients:
    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0

    def __add__(self, other: Nutrients) -> Nutrients:
        return Nutrients(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)}
        )

    def scaled(self, factor: float) -> Nutrients:
        return Nutrients(**{f.name: getattr(self, f.name) * factor for f in fields(self)})


@dataclass(frozen=True)
class StandardUnit:
    """Eine Standard-Einheit, wie sie in der Oberfläche erscheint: „1 EL = 15 g“."""

    name: str
    grams: float


def set_standard_units(units: Mapping[str, float]) -> None:
    """Standard-Einheiten aus den Einstellungen übernehmen, z. B. {"EL": 15, "TL": 5}."""
    _standard_units.clear()
    _standard_units.update({name.casefold(): (name, grams) for name, grams in units.items()})


def standard_units() -> list[StandardUnit]:
    return [StandardUnit(name, grams) for name, grams in _standard_units.values()]


def _key(unit: str | None) -> str:
    return (unit or "g").strip().casefold()


def _own_unit_grams(food: Food, key: str) -> float | None:
    grams_per_unit = {food_unit.name.casefold(): food_unit.grams for food_unit in food.units}
    if key in grams_per_unit:
        return grams_per_unit[key]
    if key in CONTAINER_UNITS and PACKAGE_UNIT in grams_per_unit:
        return grams_per_unit[PACKAGE_UNIT]
    return None


def uses_standard_unit(food: Food, unit: str | None) -> StandardUnit | None:
    """Die Standard-Einheit, mit der gerechnet wird; None bei eigener Angabe oder Gramm."""
    key = _key(unit)
    if key in MASS_UNITS_IN_GRAMS or _own_unit_grams(food, key) is not None:
        return None
    if key not in _standard_units:
        return None
    return StandardUnit(*_standard_units[key])


def unit_choices(food: Food | None) -> list[StandardUnit]:
    """Einheiten, die sich für das Lebensmittel umrechnen lassen, z. B. für eine Auswahlliste.

    Erst Gramm, dann die eigenen Einheiten (Stück, Packung …), dann die
    Standard-Einheiten, sofern das Lebensmittel sie nicht selbst festlegt.
    """
    choices = [StandardUnit("g", MASS_UNITS_IN_GRAMS["g"])]
    if food is None:
        return choices
    own = {food_unit.name.casefold() for food_unit in food.units}
    choices += [StandardUnit(food_unit.name, food_unit.grams) for food_unit in food.units]
    choices += [unit for unit in standard_units() if unit.name.casefold() not in own]
    return choices


def to_grams(food: Food, quantity: float, unit: str | None) -> float | None:
    """Rechnet eine Menge in Gramm um; None, wenn die Einheit unbekannt ist."""
    key = _key(unit)
    if key in MASS_UNITS_IN_GRAMS:
        return quantity * MASS_UNITS_IN_GRAMS[key]
    own = _own_unit_grams(food, key)
    if own is not None:
        return quantity * own
    if key in _standard_units:
        return quantity * _standard_units[key][1]
    return None


def nutrients_for(food: Food, grams: float) -> Nutrients:
    """Nährwerte einer Menge in Gramm."""
    factor = grams / GRAMS_PER_100
    return Nutrients(
        kcal=food.kcal * factor,
        protein_g=food.protein_g * factor,
        fat_g=food.fat_g * factor,
        carbs_g=food.carbs_g * factor,
    )


def total_nutrients(items: Iterable[tuple[Food, float]]) -> Nutrients:
    """Summe über (Lebensmittel, Gramm)-Paare, z. B. alle Zutaten eines Rezepts."""
    return sum((nutrients_for(food, grams) for food, grams in items), Nutrients())
