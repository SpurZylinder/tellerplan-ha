"""Rezepte, Zutatenzeilen, Grundzutaten. Nährwerte kommen nur aus `food`.

Zuordnung in drei Ebenen: Eine Rezeptzeile („200 ml Milch“) zeigt auf eine
Grundzutat („Milch“); die Grundzutat hat ein Standardprodukt (z. B. laktosefreie
Milch 1,5 % von Berchtesgadener Land) und weitere Produkte zur Auswahl. Nur wenn
im Rezept bewusst ein anderes Produkt gewählt ist, steht es an der Zeile.

Einzige Ausnahme: `RecipeReference` hält Vergleichswerte der Quelle (z. B. Cookidoo).
Sie werden angezeigt, um falsche Zuordnungen zu erkennen, aber nie gerechnet.
"""

from datetime import datetime

from sqlalchemy import JSON, Column, ForeignKey, Index, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base
from modules.foods.models import Food

MANUAL_SOURCE = "manual"

# Produkte einer Grundzutat; ein Produkt kann zu mehreren gehören (Milch und Vollmilch)
base_ingredient_food = Table(
    "base_ingredient_food",
    Base.metadata,
    Column(
        "base_ingredient_id",
        ForeignKey("base_ingredient.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("food_id", ForeignKey("food.id", ondelete="CASCADE"), primary_key=True),
)


class BaseIngredient(Base):
    """Grundzutat wie „Milch“, „Vollmilch“ oder „Kreuzkümmel“ mit ihrem Standardprodukt."""

    __tablename__ = "base_ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    key: Mapped[str] = mapped_column(String(200), unique=True)
    default_food_id: Mapped[int | None] = mapped_column(
        ForeignKey("food.id", ondelete="SET NULL"), index=True
    )
    # Gewürze u. Ä.: zählt als vollständig mit 0 kcal, braucht weder Produkt noch Grammzahl
    no_nutrients: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    default_food: Mapped[Food | None] = relationship()
    products: Mapped[list[Food]] = relationship(
        secondary=base_ingredient_food, order_by="Food.name"
    )


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
    """Eine Zutatenzeile mit Grundzutat; `food_id` nur bei bewusst gewähltem Produkt.

    Rezepte von Hand (ohne Grundzutat) halten ihr Lebensmittel direkt in `food_id`.
    """

    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    raw_text: Mapped[str] = mapped_column(String(300))
    # Erkannter Zutatenname, z. B. „Brokkoliröschen“; Schlüssel für Zuordnung und Lernen
    name: Mapped[str | None] = mapped_column(String(200))
    quantity: Mapped[float | None]
    unit: Mapped[str | None] = mapped_column(String(40))
    base_ingredient_id: Mapped[int | None] = mapped_column(
        ForeignKey("base_ingredient.id", ondelete="SET NULL"), index=True
    )
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("food.id", ondelete="SET NULL"), index=True
    )
    grams: Mapped[float | None]
    is_optional: Mapped[bool] = mapped_column(default=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    base_ingredient: Mapped[BaseIngredient | None] = relationship()
    food: Mapped[Food | None] = relationship()


class IngredientAlias(Base):
    """Zutatenname → Grundzutat, z. B. „frische milch“ → Milch; wird beim Zuordnen gelernt."""

    __tablename__ = "ingredient_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    base_ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("base_ingredient.id", ondelete="CASCADE"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    base_ingredient: Mapped[BaseIngredient] = relationship()


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
