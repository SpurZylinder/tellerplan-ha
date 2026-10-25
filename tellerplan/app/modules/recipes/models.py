"""Rezepte, Zutatenzeilen und gelernte Zuordnungen. Nährwerte kommen nur aus `food`.

Einzige Ausnahme: `RecipeReference` hält Vergleichswerte der Quelle (z. B. Cookidoo).
Sie werden angezeigt, um falsche Zuordnungen zu erkennen, aber nie gerechnet.
"""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base
from modules.foods.models import Food

MANUAL_SOURCE = "manual"


class Recipe(Base):
    __tablename__ = "recipe"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    source: Mapped[str] = mapped_column(String(40), default=MANUAL_SOURCE)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_id: Mapped[str | None] = mapped_column(String(100), index=True)
    servings: Mapped[float]
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    is_favorite: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None] = mapped_column(Text)
    # Kochschritte, ein Schritt pro Zeile
    instructions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeIngredient.position",
    )
    reference: Mapped[RecipeReference | None] = relationship(
        cascade="all, delete-orphan", uselist=False
    )

    # Ein Rezept je Quelle und Quell-ID, damit ein zweiter Import nichts doppelt anlegt
    __table_args__ = (Index("uq_recipe_source_id", "source", "source_id", unique=True),)


class RecipeIngredient(Base):
    """Eine Zutatenzeile; `food_id` leer bedeutet: noch nicht zugeordnet."""

    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    raw_text: Mapped[str] = mapped_column(String(300))
    # Erkannter Zutatenname, z. B. „Brokkoliröschen“; Schlüssel für Zuordnung und Lernen
    name: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[float | None]
    unit: Mapped[str | None] = mapped_column(String(40))
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("food.id", ondelete="SET NULL"), index=True
    )
    grams: Mapped[float | None]
    is_optional: Mapped[bool] = mapped_column(default=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    food: Mapped[Food | None] = relationship()


class IngredientAlias(Base):
    """Standardartikel je Zutatenname, z. B. „milch“ → laktosefreie Milch 1,5 %."""

    __tablename__ = "ingredient_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("food.id", ondelete="CASCADE"), index=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    food: Mapped[Food] = relationship()


class RecipeReference(Base):
    """Nährwerte pro Portion laut Quelle – nur zum Vergleich, nie in der Rechnung."""

    __tablename__ = "recipe_reference"

    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
    )
    kcal: Mapped[float | None]
    protein_g: Mapped[float | None]
    fat_g: Mapped[float | None]
    carbs_g: Mapped[float | None]
