"""Rezeptseite von Cookidoo → Entwurf: reine Logik, synthetische Seiten."""

import pytest

from factories import recipe_page
from modules.importers.cookidoo_page import (
    MAX_INGREDIENT_LINES,
    MAX_TEXT_LENGTH,
    RecipePageError,
    draft_from_page,
    same_title,
)

URL = "https://cookidoo.de/recipes/recipe/de-DE/r821223"
NUTRITION = {
    "calories": "430 kcal",
    "proteinContent": "21 g",
    "fatContent": "27 g",
    "carbohydrateContent": "24,5 g",
}


def test_draft_has_title_servings_lines_and_reference_only() -> None:
    page = recipe_page(
        "Tofu-Curry mit Gemüse",
        ["50 g Zwiebel", "1 Knoblauchzehe", "20 g Ingwer, frisch"],
        nutrition=NUTRITION,
    )

    draft = draft_from_page("r821223", URL, page)

    assert draft == {
        "source_id": "r821223",
        "title": "Tofu-Curry mit Gemüse",
        "servings": 4,
        "source_url": URL,
        "total_time": "30 min",
        "ingredients": ["50 g Zwiebel", "1 Knoblauchzehe", "20 g Ingwer, frisch"],
        "reference": {
            "kcal_per_serving": 430,
            "protein_g_per_serving": 21,
            "fat_g_per_serving": 27,
            "carbs_g_per_serving": 24.5,
        },
    }


def test_entities_and_whitespace_are_cleaned() -> None:
    page = recipe_page("Kuchen&nbsp;&amp; Co", ["&frac12;  TL   Salz", "  ", 42])

    draft = draft_from_page("r1", URL, page)

    assert draft["title"] == "Kuchen & Co"
    assert draft["ingredients"] == ["½ TL Salz"]


@pytest.mark.parametrize(
    ("recipe_yield", "servings"),
    [("4 Portionen", 4), ("12 Stück", 12), ("1,5 l", 1.5), (["6 Portionen"], 6), ("", None)],
)
def test_servings_from_yield(recipe_yield: object, servings: float | None) -> None:
    page = recipe_page("Rezept", [], recipe_yield=recipe_yield)

    assert draft_from_page("r1", URL, page)["servings"] == servings


@pytest.mark.parametrize(
    ("duration", "text"),
    [("PT30M", "30 min"), ("PT1H10M", "1 h 10 min"), ("PT2H", "2 h"), ("P1DT2H", "26 h")],
)
def test_total_time_is_readable(duration: str, text: str) -> None:
    page = recipe_page("Rezept", [], total_time=duration)

    assert draft_from_page("r1", URL, page)["total_time"] == text


def test_unknown_duration_and_missing_nutrition_fall_away() -> None:
    draft = draft_from_page("r1", URL, recipe_page("Rezept", [], total_time="30 Minuten"))

    assert draft["total_time"] is None
    assert set(draft["reference"].values()) == {None}


def test_page_is_bounded() -> None:
    lines = ["x" * (MAX_TEXT_LENGTH + 50)] * (MAX_INGREDIENT_LINES + 5)

    draft = draft_from_page("r1", URL, recipe_page("T" * 400, lines))

    assert len(draft["title"]) == MAX_TEXT_LENGTH
    assert len(draft["ingredients"]) == MAX_INGREDIENT_LINES
    assert all(len(line) == MAX_TEXT_LENGTH for line in draft["ingredients"])


@pytest.mark.parametrize(
    "page",
    [
        "<html><body>Rezept nicht gefunden</body></html>",
        '<script type="application/ld+json">{kaputt</script>',
        recipe_page("", ["1 Zwiebel"]),
    ],
)
def test_page_without_recipe_is_an_error(page: str) -> None:
    with pytest.raises(RecipePageError):
        draft_from_page("r1", URL, page)


def test_same_title_ignores_case_punctuation_and_spaces() -> None:
    assert same_title("Linsen-Dal", "linsen dal")
    assert same_title("Tofu-Curry mit Gemüse", "Tofu-Curry mit Gemüse ")
    assert not same_title("Linsen-Dal", "Kichererbsen-Dal")
