"""Lebensmittel und ihre Einheiten. Einzige Stelle mit Nährwerten (pro 100 g)."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class FoodSource(enum.StrEnum):
    BLS = "bls"
    OFF = "off"
    REWE = "rewe"
    CUSTOM = "custom"


class Food(Base):
    __tablename__ = "food"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    source: Mapped[FoodSource] = mapped_column(
        Enum(
            FoodSource, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]
        )
    )
    source_id: Mapped[str | None] = mapped_column(String(100), index=True)
    # Kurzer Name für die Einkaufsliste, z. B. „Hähnchenbrust“; leer = aus `name` abgeleitet
    shopping_name: Mapped[str | None] = mapped_column(String(100))
    # Hersteller bei Markenprodukten, z. B. „Berchtesgadener Land“; leer = generisch (BLS, eigen)
    brand: Mapped[str | None] = mapped_column(String(120))
    # EAN/GTIN; ein Produkt mit Barcode gibt es nur einmal, egal aus welcher Quelle
    barcode: Mapped[str | None] = mapped_column(String(14), index=True, unique=True)
    # Packungsgröße laut Handel, z. B. „1l“ oder „200g“
    package: Mapped[str | None] = mapped_column(String(60))

    # Nährwerte pro 100 g
    kcal: Mapped[float]
    protein_g: Mapped[float]
    fat_g: Mapped[float]
    carbs_g: Mapped[float]
    fiber_g: Mapped[float | None]
    sugar_g: Mapped[float | None]
    salt_g: Mapped[float | None]
    extra_nutrients: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    units: Mapped[list[FoodUnit]] = relationship(
        back_populates="food", cascade="all, delete-orphan", order_by="FoodUnit.name"
    )

    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_food_source_id"),)


class FoodUnit(Base):
    """Umrechnung einer Einheit (EL, Stück …) in Gramm für ein Lebensmittel."""

    __tablename__ = "food_unit"

    id: Mapped[int] = mapped_column(primary_key=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    grams: Mapped[float]

    food: Mapped[Food] = relationship(back_populates="units")

    __table_args__ = (UniqueConstraint("food_id", "name", name="uq_food_unit_name"),)
