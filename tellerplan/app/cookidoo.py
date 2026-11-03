"""Anbindung an den Cookidoo-Kalender „Meine Woche“ über die Bibliothek `cookidoo-api`.

Einzige Stelle mit Netzwerkaufrufen an Cookidoo, wie `supervisor.py` für Home Assistant.
Die Schnittstelle ist inoffiziell; Fehler kommen darum immer als `CookidooError` mit
einer Meldung für die Oberfläche, damit der Plan auch ohne Cookidoo funktioniert.

Anmeldung: OAuth mit PKCE. E-Mail und Passwort gehen einmal an `login()` und werden nicht
gespeichert. Gespeichert werden nur die Tokens und der Anzeigename, in einer Datei neben
der Datenbank. Die Bibliothek erneuert das Access-Token selbst; jede Erneuerung wird sofort
geschrieben. Tokens erscheinen nie im Log.

Antworten von Cookidoo gelten als nicht vertrauenswürdig: Rezept-IDs müssen die Form
`r123` haben, Links werden nur übernommen, wenn sie per https auf die Cookidoo-Seite des
Landes zeigen (sonst aus der ID gebaut), Namen werden gekürzt. Sie landen als Platzhalter
in der Datenbank und als Link in der Oberfläche.

Rezeptseiten (für unbekannte Rezepte aus dem Kalender) kommen ohne Anmeldung von der
öffentlichen Seite des Landes. Der Link wird nur aus der geprüften ID gebaut,
Weiterleitungen werden nicht verfolgt, die Größe ist begrenzt.

Die Bibliothek arbeitet asynchron; die Funktionen hier sind synchron (FastAPI führt
synchrone Routen in einem eigenen Thread aus, dort läuft `asyncio.run`).
"""

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
# Katalog-Rezepte in Cookidoo, z. B. „r821223“
RECIPE_ID_PATTERN = re.compile(r"^r\d{1,12}$")
# Wie `recipe.title`; längere Namen werden gekürzt
MAX_NAME_LENGTH = 300
# Eine Rezeptseite hat rund 100 KB; größere Antworten werden abgelehnt
MAX_PAGE_BYTES = 2 * 1024 * 1024
HTTP_OK = 200
USER_AGENT = "Mozilla/5.0 (Tellerplan, privater Rezeptimport)"

logger = logging.getLogger(__name__)


class CookidooError(RuntimeError):
    """Cookidoo nicht erreichbar, Anmeldung abgelehnt oder abgelaufen."""


class NotConnectedError(CookidooError):
    """Es gibt noch keine Verbindung (keine gespeicherten Tokens)."""


class RecipePageMissingError(CookidooError):
    """Cookidoo liefert zu dieser ID keine Rezeptseite (z. B. 404); andere IDs gehen noch."""


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
            host = urlsplit(cookidoo.localization.url).netloc
            recipes = []
            for monday in week_starts(first, last):
                for day in await cookidoo.get_recipes_in_calendar_week(monday):
                    day_date = date.fromisoformat(day.id)
                    if not first <= day_date <= last:
                        continue
                    recipes += [
                        checked
                        for recipe in day.recipes
                        if not recipe.is_custom
                        and (checked := self._checked(day_date, recipe, host)) is not None
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

    def recipe_page(self, recipe_id: str) -> str:
        """HTML der öffentlichen Rezeptseite; Fehler als `CookidooError`."""
        if not RECIPE_ID_PATTERN.match(recipe_id):
            raise CookidooError(f"„{recipe_id[:20]}“ ist keine Cookidoo-Rezept-ID.")
        try:
            return asyncio.run(self._fetch_page(recipe_id))
        except (CookidooException, ClientError, TimeoutError, UnicodeDecodeError) as error:
            logger.warning("Rezeptseite %s nicht geladen: %s", recipe_id, type(error).__name__)
            raise CookidooError("Die Rezeptseite ist gerade nicht erreichbar.") from error

    async def _fetch_page(self, recipe_id: str) -> str:
        host = urlsplit((await self._localization()).url).netloc
        url = f"https://{host}/recipes/recipe/{self.locale}/{recipe_id}"
        headers = {"User-Agent": USER_AGENT, "Accept-Language": self.locale}
        timeout = ClientTimeout(total=TIMEOUT_SECONDS)
        async with (
            ClientSession(timeout=timeout) as session,
            session.get(url, headers=headers, allow_redirects=False) as response,
        ):
            if response.status != HTTP_OK:
                raise RecipePageMissingError(f"Rezeptseite nicht gefunden ({response.status}).")
            content = await response.content.read(MAX_PAGE_BYTES + 1)
        if len(content) > MAX_PAGE_BYTES:
            raise RecipePageMissingError("Die Rezeptseite ist unerwartet groß.")
        return content.decode("utf-8")

    def _checked(self, day: date, recipe: Any, host: str) -> CalendarRecipe | None:
        """Geprüfter Kalendereintrag; None bei einer ID, die kein Cookidoo-Rezept sein kann."""
        recipe_id = str(recipe.id)
        if not RECIPE_ID_PATTERN.match(recipe_id):
            logger.warning("Cookidoo-Eintrag mit unerwarteter ID übergangen")
            return None
        name = str(recipe.name or recipe_id).strip()[:MAX_NAME_LENGTH] or recipe_id
        return CalendarRecipe(
            day, recipe_id, name, self._link(str(recipe.url or ""), host, recipe_id)
        )

    def _link(self, url: str, host: str, recipe_id: str) -> str:
        """Link aus Cookidoo, wenn er per https auf die Seite des Landes zeigt; sonst aus der ID."""
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.netloc == host:
            return url
        return f"https://{host}/recipes/recipe/{self.locale}/{recipe_id}"

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
