"""Planeinträge: Tag → Rezept mit geplanten Portionen (Vorgabe: Standardportionen)."""

from datetime import date, datetime

from sqlalchemy import ForeignKey, func
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    recipe: Mapped[Recipe] = relationship()
