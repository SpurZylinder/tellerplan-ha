"""Bekannte Benutzer (HA-Benutzer-ID, Name, zuletzt gesehen) und ihre Tagesziele."""

from datetime import date, datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class AppUser(Base):
    __tablename__ = "app_user"

    # ID des Benutzers in Home Assistant (z. B. „1a459f2d…“); lokal „local“
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    first_seen: Mapped[datetime]
    last_seen: Mapped[datetime]


class Goal(Base):
    """Eigene Tagesziele eines Benutzers ab einem Tag.

    Für einen Tag gilt der Eintrag mit dem spätesten `valid_from` bis zu diesem Tag;
    vergangene Tage laufen so weiter gegen das damalige Ziel. Ohne Eintrag gelten die
    Vorgabeziele aus den Optionen. Bewusst ohne Fremdschlüssel (wie `diary_entry`).
    """

    __tablename__ = "goal"
    __table_args__ = (UniqueConstraint("user_id", "valid_from", name="uq_goal_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    valid_from: Mapped[date]
    kcal: Mapped[int]
    protein_g: Mapped[int]
    fat_g: Mapped[int]
    carbs_g: Mapped[int]
