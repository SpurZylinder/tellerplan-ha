"""Zeilenparser an echten Zeilen aus der Cookidoo-Sammlung."""

import pytest

from modules.importers.line_parser import ParsedLine, parse_line


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("350 g Brokkoliröschen", ParsedLine(350, "g", "Brokkoliröschen", None)),
        ("½ TL Muskat", ParsedLine(0.5, "TL", "Muskat", None)),
        ("1 ½ TL Salz", ParsedLine(1.5, "TL", "Salz", None)),
        ("1/2 TL Pfeffer", ParsedLine(0.5, "TL", "Pfeffer", None)),
        ("0,5 l Milch", ParsedLine(0.5, "l", "Milch", None)),
        ("2 Prisen Salz", ParsedLine(2, "Prise", "Salz", None)),
        ("1 Pck. Backpulver", ParsedLine(1, "Packung", "Backpulver", None)),
        ("2 Zweige Rosmarin", ParsedLine(2, "Zweig", "Rosmarin", None)),
        (
            "1 geh. TL Gewürzpaste für Gemüsebrühe, selbst gemacht",
            ParsedLine(1, "TL", "Gewürzpaste für Gemüsebrühe", "geh., selbst gemacht"),
        ),
        ("100 g Schinken, gekocht", ParsedLine(100, "g", "Schinken", "gekocht")),
        (
            "2 TL Kreuzkümmel (Cumin), gemahlen",
            ParsedLine(2, "TL", "Kreuzkümmel", "Cumin, gemahlen"),
        ),
        ("1 Ei (Größe M)", ParsedLine(1, "Stück", "Ei", "Größe M")),
        ("550 - 600 g Hähnchenbrustfilets", ParsedLine(575, "g", "Hähnchenbrustfilets", None)),
        ("1 - 1 ½ TL Gewürzmischung", ParsedLine(1.25, "TL", "Gewürzmischung", None)),
        ("2 Zwiebeln", ParsedLine(2, "Stück", "Zwiebeln", None)),
        ("1 rote Paprika", ParsedLine(1, "Stück", "rote Paprika", None)),
        ("1 Knoblauchzehe", ParsedLine(1, "Stück", "Knoblauchzehe", None)),
        ("1 Lorbeerblatt, getrocknet", ParsedLine(1, "Stück", "Lorbeerblatt", "getrocknet")),
        ("70 - 100 g Joghurt 3,5 %Fett", ParsedLine(85, "g", "Joghurt 3,5 %Fett", None)),
        ("280 g Weizenmehl Type 550", ParsedLine(280, "g", "Weizenmehl Type 550", None)),
        ("Salz", ParsedLine(None, None, "Salz", None)),
        ("Öl zum Braten", ParsedLine(None, None, "Öl zum Braten", None)),
    ],
)
def test_real_lines(text: str, expected: ParsedLine) -> None:
    assert parse_line(text) == expected


def test_unit_word_alone_is_a_name() -> None:
    # „1 Würfel“ ohne weiteren Namen: Würfel ist dann die Zutat, nicht die Einheit
    assert parse_line("1 Würfel") == ParsedLine(1, "Stück", "Würfel", None)


def test_key_ignores_case_and_spacing() -> None:
    assert parse_line("2  Rote   Paprika").key == "rote paprika"
