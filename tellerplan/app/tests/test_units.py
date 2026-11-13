"""Einheiten: Schreibweisen vereinheitlichen und umrechnen (Befund K10)."""

import pytest

from modules.foods.units import canonical_unit, to_base_unit, to_display_unit


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("EL", "EL"),
        ("el", "EL"),
        (" El ", "EL"),
        ("Stk.", "Stück"),
        ("stück", "Stück"),
        ("gr", "g"),
        ("Zehe", "Zehe"),  # unbekannt: bleibt
    ],
)
def test_canonical_unit(text: str, expected: str) -> None:
    assert canonical_unit(text) == expected


def test_kilogram_and_litre_become_base_units() -> None:
    assert to_base_unit(1.5, "kg") == (1500, "g")
    assert to_base_unit(0.5, "L") == (500, "ml")
    assert to_base_unit(2, "el") == (2, "EL")


def test_large_amounts_are_shown_in_the_larger_unit() -> None:
    assert to_display_unit(1500, "g") == (1.5, "kg")
    assert to_display_unit(999, "g") == (999, "g")
    assert to_display_unit(1000, "ml") == (1, "l")
    assert to_display_unit(3, "EL") == (3, "EL")
