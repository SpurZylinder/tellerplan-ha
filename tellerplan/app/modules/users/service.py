"""Bekannte Benutzer pflegen.

Wer eine Seite öffnet, wird gemerkt bzw. sein Name aktualisiert. „Zuletzt gesehen“
wird höchstens einmal je `SEEN_INTERVAL` geschrieben, damit nicht jede Anfrage die
Datenbank ändert.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.users.models import AppUser

SEEN_INTERVAL = timedelta(hours=1)


def touch_user(session: Session, user_id: str, name: str, now: datetime) -> AppUser:
    """Legt den Benutzer an oder aktualisiert Name und „zuletzt gesehen“ (nur bei Bedarf)."""
    user = session.get(AppUser, user_id)
    if user is None:
        user = AppUser(id=user_id, name=name, first_seen=now, last_seen=now)
        session.add(user)
        session.flush()
        return user
    if user.name != name and name:
        user.name = name
    if now - user.last_seen >= SEEN_INTERVAL:
        user.last_seen = now
    session.flush()
    return user


def known_users(session: Session) -> list[AppUser]:
    """Alle bekannten Benutzer, nach Name."""
    return list(session.scalars(select(AppUser).order_by(AppUser.name)))
