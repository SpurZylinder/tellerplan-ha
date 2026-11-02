"""Planeinträge: Tag → Rezept mit geplanten Portionen (Vorgabe: Standardportionen).

Für den Abgleich mit Cookidoo („Meine Woche“) merkt sich ein Eintrag, an welchem Tag
er zuletzt in Cookidoo stand; gelöschte abgeglichene Einträge hinterlassen eine Notiz.
"""

from datetime import date, datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base
from modules.recipes.models import Recipe


class PlanEntry(Base):
    __tablename__ = "plan_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"), index=True)
    servings: Mapped[float]
    # Wann die Zutaten an die Einkaufsliste gingen; leer = noch nicht gesendet
    shopping_sent_at: Mapped[datetime | None]
    # Tag, an dem der Eintrag beim letzten Abgleich in Cookidoo stand; leer = nie abgeglichen
    cookidoo_day: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    recipe: Mapped[Recipe] = relationship()


class CookidooRemoval(Base):
    """In Tellerplan gelöscht, in Cookidoo noch zu entfernen (beim nächsten Abgleich)."""

    __tablename__ = "cookidoo_removal"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date]
    cookidoo_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
