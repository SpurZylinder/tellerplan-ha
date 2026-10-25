"""Sitzungen der Vollbild-App: wer sich über Home Assistant angemeldet hat.

Das Cookie enthält einen Zufallswert, die Datenbank nur dessen Hash und den
Refresh-Token von Home Assistant, mit dem die Sitzung regelmäßig geprüft wird.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

import clock
from db import Base

# So oft fragt Tellerplan bei Home Assistant nach, ob der Zugang noch gilt.
CHECK_INTERVAL = timedelta(minutes=30)


class WebSession(Base):
    __tablename__ = "web_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_token: Mapped[str] = mapped_column(Text)
    # client_id der Anmeldung; Home Assistant prüft den Refresh-Token nur mit ihr
    client_id: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime]
    checked_at: Mapped[datetime]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(session: Session, refresh_token: str, client_id: str) -> str:
    """Legt eine Sitzung an und gibt den Wert für das Cookie zurück."""
    token = secrets.token_urlsafe(32)
    now = clock.now()
    session.add(
        WebSession(
            token_hash=_hash(token),
            refresh_token=refresh_token,
            client_id=client_id,
            created_at=now,
            checked_at=now,
        )
    )
    session.flush()
    return token


def find_session(session: Session, token: str | None) -> WebSession | None:
    if not token:
        return None
    return session.scalar(select(WebSession).where(WebSession.token_hash == _hash(token)))


def needs_check(web_session: WebSession) -> bool:
    return clock.now() - web_session.checked_at >= CHECK_INTERVAL


def mark_checked(session: Session, web_session: WebSession) -> None:
    web_session.checked_at = clock.now()
    session.flush()


def delete_session(session: Session, web_session: WebSession) -> None:
    session.delete(web_session)
    session.flush()
