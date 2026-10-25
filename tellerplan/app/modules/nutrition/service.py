"""Menge + Einheit → Gramm → Nährwerte. Einzige Stelle, an der gerechnet wird."""

from collections.abc import Iterable
from dataclasses import dataclass, fields

from modules.foods.models import Food

GRAMS_PER_100 = 100.0
# Feste Masseneinheiten; alle anderen Einheiten kommen aus food_unit.
MASS_UNITS_IN_GRAMS = {"g": 1.0, "gramm": 1.0, "kg": 1000.0}
# Behälter, die ohne eigene Angabe genau eine Packung des Produkts sind („1 Dose Kokosmilch“)
PACKAGE_UNIT = "packung"
CONTAINER_UNITS = {"dose", "glas", "flasche", "becher", "beutel", "tüte", "schale", "tube"}


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


def to_grams(food: Food, quantity: float, unit: str | None) -> float | None:
    """Rechnet eine Menge in Gramm um; None, wenn die Einheit unbekannt ist."""
    key = (unit or "g").strip().casefold()
    if key in MASS_UNITS_IN_GRAMS:
        return quantity * MASS_UNITS_IN_GRAMS[key]
    grams_per_unit = {food_unit.name.casefold(): food_unit.grams for food_unit in food.units}
    if key in grams_per_unit:
        return quantity * grams_per_unit[key]
    if key in CONTAINER_UNITS and PACKAGE_UNIT in grams_per_unit:
        return quantity * grams_per_unit[PACKAGE_UNIT]
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
