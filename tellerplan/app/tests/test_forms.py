"""Zahlen aus Formularen: deutsche Schreibweise, Einheit des Feldes darf dahinterstehen."""

import pytest

from web.forms import FormError, parse_number, required_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [("50", 50), ("50g", 50), ("50 g", 50), ("50 G", 50), ("1,5 g", 1.5), ("12.5g.", 12.5)],
)
def test_grams_with_or_without_unit(text: str, expected: float) -> None:
    assert required_number(text, "Gramm", unit="g") == expected


def test_kcal_with_unit() -> None:
    assert required_number("2000 kcal", "Tageslimit", unit="kcal") == 2000


@pytest.mark.parametrize("text", ["50 kg", "fünfzig"])
def test_other_text_is_rejected_with_example(text: str) -> None:
    with pytest.raises(FormError, match=r"Gramm: bitte eine Zahl eingeben, z\. B\. 50 oder 50 g\."):
        required_number(text, "Gramm", unit="g")


def test_without_unit_parameter_unit_text_is_not_accepted() -> None:
    with pytest.raises(FormError):
        parse_number("50 g", "Menge")


def test_unit_alone_counts_as_missing() -> None:
    with pytest.raises(FormError, match="Gramm fehlt."):
        required_number("g", "Gramm", unit="g")
