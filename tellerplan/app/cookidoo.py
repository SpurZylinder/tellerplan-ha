"""Anbindung an den Cookidoo-Kalender „Meine Woche“ über die Bibliothek `cookidoo-api`.

Einzige Stelle mit Netzwerkaufrufen an Cookidoo, wie `supervisor.py` für Home Assistant.
Die Schnittstelle ist inoffiziell; Fehler kommen darum immer als `CookidooError` mit
einer Meldung für die Oberfläche, damit der Plan auch ohne Cookidoo funktioniert.

Anmeldung: OAuth mit PKCE. E-Mail und Passwort gehen einmal an `login()` und werden nicht
gespeichert. Gespeichert werden nur die Tokens und der Anzeigename, in einer Datei neben
der Datenbank. Die Bibliothek erneuert das Access-Token selbst; jede Erneuerung wird sofort
geschrieben. Tokens erscheinen nie im Log.

Die Bibliothek arbeitet asynchron; die Funktionen hier sind synchron (FastAPI führt
synchrone Routen in einem eigenen Thread aus, dort läuft `asyncio.run`).
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout, CookieJar
from cookidoo_api import (
    Cookidoo,
    CookidooAuthData,
    CookidooAuthException,
    CookidooConfig,
    CookidooException,
    get_localization_options,
)

TIMEOUT_SECONDS = 30
DAYS_PER_WEEK = 7
# Nur der Besitzer darf die Tokens lesen
TOKEN_FILE_MODE = 0o600

logger = logging.getLogger(__name__)


class CookidooError(RuntimeError):
    """Cookidoo nicht erreichbar, Anmeldung abgelehnt oder abgelaufen."""


class NotConnectedError(CookidooError):
    """Es gibt noch keine Verbindung (keine gespeicherten Tokens)."""


@dataclass(frozen=True)
class CalendarRecipe:
    """Ein Rezept aus dem Cookidoo-Katalog, eingeplant an einem Tag."""

    day: date
    recipe_id: str
    name: str
    url: str


@dataclass(frozen=True)
class CookidooAccount:
    """Zugang zu Cookidoo: Datei mit den Tokens und Sprache/Land (z. B. „de-DE“)."""

    token_path: Path
    locale: str

    def username(self) -> str | None:
        """Anzeigename des verbundenen Kontos; None, wenn nicht verbunden."""
        stored = self._stored()
        return stored["username"] if stored else None

    def connect(self, email: str, password: str) -> str:
        """Meldet sich an, speichert die Tokens und liefert den Anzeigenamen."""

        async def login(cookidoo: Cookidoo) -> str:
            await cookidoo.login()
            info = await cookidoo.get_user_info()
            auth_data = cookidoo.auth_data
            if auth_data is None:
                raise CookidooAuthException("Keine Tokens nach der Anmeldung")
            self._write(info.username, auth_data)
            return info.username

        return self._run(login, email=email, password=password)

    def disconnect(self) -> None:
        """Vergisst die Tokens; in Cookidoo selbst ändert sich nichts."""
        self.token_path.unlink(missing_ok=True)

    def read_calendar(self, first: date, last: date) -> list[CalendarRecipe]:
        """Eingeplante Katalog-Rezepte von `first` bis `last`.

        Cookidoo liefert nur Tage mit Rezepten; ein fehlender Tag ist leer. Eigene
        Cookidoo-Rezepte (nur als ID ohne Namen geliefert) bleiben außen vor.
        """

        async def read(cookidoo: Cookidoo) -> list[CalendarRecipe]:
            recipes = []
            for monday in week_starts(first, last):
                for day in await cookidoo.get_recipes_in_calendar_week(monday):
                    day_date = date.fromisoformat(day.id)
                    if first <= day_date <= last:
                        recipes += [
                            CalendarRecipe(day_date, recipe.id, recipe.name, recipe.url)
                            for recipe in day.recipes
                            if not recipe.is_custom
                        ]
            return recipes

        return self._run(read)

    def plan(self, day: date, recipe_ids: list[str]) -> None:
        """Plant Rezepte an einem Tag ein."""

        async def add(cookidoo: Cookidoo) -> None:
            await cookidoo.add_recipes_to_calendar(day, recipe_ids)

        self._run(add)

    def unplan(self, day: date, recipe_id: str) -> None:
        """Nimmt ein Rezept von einem Tag."""

        async def remove(cookidoo: Cookidoo) -> None:
            await cookidoo.remove_recipe_from_calendar(day, recipe_id)

        self._run(remove)

    def _stored(self) -> dict[str, Any] | None:
        try:
            stored = json.loads(self.token_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        return stored if isinstance(stored, dict) and "tokens" in stored else None

    def _write(self, username: str, auth_data: CookidooAuthData) -> None:
        content = json.dumps({"username": username, "tokens": vars(auth_data)})
        self.token_path.write_text(content, encoding="utf-8")
        self.token_path.chmod(TOKEN_FILE_MODE)

    def _tokens_renewed(self, auth_data: CookidooAuthData) -> None:
        stored = self._stored()
        if stored is not None:
            self._write(stored["username"], auth_data)

    def _run[T](
        self, action: Callable[[Cookidoo], Awaitable[T]], email: str = "", password: str = ""
    ) -> T:
        try:
            return asyncio.run(self._with_client(action, email, password))
        except CookidooAuthException as error:
            logger.warning("Cookidoo lehnt die Anmeldung ab: %s", type(error).__name__)
            raise CookidooError(
                "Cookidoo hat die Anmeldung abgelehnt oder sie ist abgelaufen. "
                "Bitte in den Einstellungen neu verbinden."
            ) from error
        except (CookidooException, ClientError, TimeoutError) as error:
            logger.warning("Cookidoo nicht erreichbar: %s", type(error).__name__)
            raise CookidooError("Cookidoo ist gerade nicht erreichbar.") from error

    async def _with_client[T](
        self, action: Callable[[Cookidoo], Awaitable[T]], email: str, password: str
    ) -> T:
        logging_in = bool(email)
        stored = None if logging_in else self._stored()
        if not logging_in and stored is None:
            raise NotConnectedError("Cookidoo ist noch nicht verbunden.")
        timeout = ClientTimeout(total=TIMEOUT_SECONDS)
        async with ClientSession(cookie_jar=CookieJar(unsafe=True), timeout=timeout) as session:
            config = CookidooConfig(
                localization=await self._localization(), email=email, password=password
            )
            cookidoo = Cookidoo(session, config, on_auth_data_update=self._tokens_renewed)
            if stored is not None:
                cookidoo.apply_auth_data(CookidooAuthData(**stored["tokens"]))
            return await action(cookidoo)

    async def _localization(self) -> Any:
        """Lokalisierung zu „de-DE“: Land „de“, Sprache „de-DE“, Seite cookidoo.de."""
        country = self.locale.split("-")[1].lower()
        options = await get_localization_options(country=country, language=self.locale)
        if not options:
            raise CookidooError(f"Cookidoo kennt die Sprache „{self.locale}“ nicht.")
        return options[0]


def week_starts(first: date, last: date) -> list[date]:
    """Montage aller Wochen, die den Zeitraum berühren (Cookidoo liest wochenweise)."""
    monday = first - timedelta(days=first.weekday())
    starts = []
    while monday <= last:
        starts.append(monday)
        monday += timedelta(days=DAYS_PER_WEEK)
    return starts
