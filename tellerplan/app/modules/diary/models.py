"""Tagebucheinträge: was zu welcher Mahlzeit gegessen wurde.

Jeder Eintrag hält einen Nährwert-Snapshot, damit spätere Änderungen an
Rezepten oder Lebensmitteln vergangene Tage nicht verändern.
"""

from datetime import date, datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class DiaryEntry(Base):
    __tablename__ = "diary_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    meal: Mapped[str] = mapped_column(String(60))
    # Wem der Eintrag gehört (HA-Benutzer-ID, seit Migration 0019); leer = von vor 0.5.12,
    # noch keinem Benutzer zugeordnet. Bewusst ohne Fremdschlüssel auf app_user.
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # Herkunft: entweder ein Rezept (mit Portionen) oder ein Lebensmittel (mit Menge)
    recipe_id: Mapped[int | None] = mapped_column(
        ForeignKey("recipe.id", ondelete="SET NULL"), index=True
    )
    food_id: Mapped[int | None] = mapped_column(
        ForeignKey("food.id", ondelete="SET NULL"), index=True
    )
    plan_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_entry.id", ondelete="SET NULL"), index=True
    )
    servings: Mapped[float | None]
    quantity: Mapped[float | None]
    unit: Mapped[str | None] = mapped_column(String(40))
    grams: Mapped[float | None]

    # Snapshot zum Zeitpunkt des Eintragens
    label: Mapped[str] = mapped_column(String(300))
    kcal: Mapped[float]
    protein_g: Mapped[float]
    fat_g: Mapped[float]
    carbs_g: Mapped[float]
    # Seit Migration 0017; leer = unbekannt (ältere Einträge, Lebensmittel ohne Angabe)
    fiber_g: Mapped[float | None]
    sugar_g: Mapped[float | None]
    salt_g: Mapped[float | None]
    is_complete: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
