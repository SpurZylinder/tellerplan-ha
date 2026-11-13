"""Bekannte Benutzer: HA-Benutzer-ID, Name, zuletzt gesehen."""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class AppUser(Base):
    __tablename__ = "app_user"

    # ID des Benutzers in Home Assistant (z. B. „1a459f2d…“); lokal „local“
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    first_seen: Mapped[datetime]
    last_seen: Mapped[datetime]
