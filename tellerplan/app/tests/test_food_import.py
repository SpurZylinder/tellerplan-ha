"""Import von Lebensmitteln (Format „tellerplan-foods“, z. B. aus tools/rewe_fetch.py)."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.foods.importer import FoodImportError, import_foods, package_grams
from modules.foods.models import Food, FoodSource
from modules.foods.service import set_unit
from modules.nutrition.service import to_grams

MILK = {
    "source": "rewe",
    "source_id": "4099936001270",
    "barcode": "4099936001270",
    "name": "Frankenland Frischmilch 1l 1,5%",
    "brand": "Frankenland - Die Frankenmilch",
    "package": "1l",
    "basis": "100 ml",
    "kcal": 47,
    "protein_g": 3.4,
    "fat_g": 1.5,
    "carbs_g": 4.9,
    "sugar_g": 4.9,
    "salt_g": 0.13,
}


def _document(*foods: dict[str, Any]) -> dict[str, Any]:
    return {"format": "tellerplan-foods", "version": 1, "foods": list(foods), "skipped": []}


def _by_barcode(session: Session, barcode: str) -> Food:
    food = session.scalar(select(Food).where(Food.barcode == barcode))
    assert food is not None
    return food


def test_import_creates_product_with_units(session: Session) -> None:
    result = import_foods(session, _document(MILK))

    milk = _by_barcode(session, "4099936001270")
    assert (result.created, result.updated) == (1, 0)
    assert (milk.source, milk.brand, milk.package, milk.kcal) == (
        FoodSource.REWE,
        "Frankenland - Die Frankenmilch",
        "1l",
        47,
    )
    assert to_grams(milk, 200, "ml") == 200  # je 100 ml gespeichert, 1 ml = 1 g
    assert to_grams(milk, 1, "Packung") == 1000


def test_same_barcode_from_other_source_updates_instead_of_duplicating(session: Session) -> None:
    import_foods(session, _document({**MILK, "source": "off", "kcal": 48}))

    result = import_foods(session, _document(MILK))

    milks = session.scalars(select(Food).where(Food.barcode == MILK["barcode"])).all()
    assert (result.created, result.updated) == (0, 1)
    assert len(milks) == 1
    assert milks[0].kcal == 47


def test_reimport_keeps_hand_maintained_units_and_short_name(session: Session) -> None:
    import_foods(session, _document(MILK))
    milk = _by_barcode(session, MILK["barcode"])
    milk.shopping_name = "Milch"
    set_unit(session, milk, "Glas", 250)
    set_unit(session, milk, "Packung", 1030)  # von Hand genauer

    import_foods(session, _document({**MILK, "kcal": 46}))

    assert milk.shopping_name == "Milch"
    assert to_grams(milk, 1, "Glas") == 250
    assert to_grams(milk, 1, "Packung") == 1030
    assert milk.kcal == 46


def test_products_without_barcode_are_recognised_by_source_id(session: Session) -> None:
    pepper = {**MILK, "source_id": "rewe-123", "barcode": None, "name": "Pfeffer", "basis": "100 g"}
    import_foods(session, _document(pepper))

    result = import_foods(session, _document(pepper))

    assert (result.created, result.updated) == (0, 1)


def test_incomplete_entries_are_skipped_with_reason(session: Session) -> None:
    incomplete = {**MILK, "barcode": "4000000000000", "source_id": "4000000000000"}
    del incomplete["protein_g"]

    result = import_foods(session, _document(incomplete, {**MILK, "source": "irgendwo"}))

    assert result.created == 0
    assert result.skipped == [
        "Frankenland Frischmilch 1l 1,5%: Nährwerte fehlen (protein_g)",
        "Frankenland Frischmilch 1l 1,5%: unbekannte Quelle 'irgendwo'",
    ]


@pytest.mark.parametrize(
    ("package", "grams"),
    [
        ("1l", 1000),
        ("200g", 200),
        ("0,5 kg", 500),
        ("250 ml", 250),
        ("2 Stück", None),
        (None, None),
    ],
)
def test_package_grams(package: str | None, grams: float | None) -> None:
    assert package_grams(package) == grams


def test_wrong_format_is_rejected(session: Session) -> None:
    with pytest.raises(FoodImportError, match="Version"):
        import_foods(session, {"format": "tellerplan-foods", "version": 9, "foods": []})


def test_upload_page_imports_foods(ingress_client: TestClient) -> None:
    content = json.dumps(_document(MILK)).encode()

    response = ingress_client.post(
        "/settings/import", files={"file": ("rewe_lebensmittel.json", content, "application/json")}
    )

    assert "Lebensmittel importiert" in response.text
    assert "1 neu, 0 schon vorhanden" in response.text
    search = ingress_client.get("/foods/search?q=frischmilch").text
    assert "Frankenland - Die Frankenmilch" in search
