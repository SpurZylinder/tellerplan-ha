"""Erkundung des Cookidoo-Kalenders für den Abgleich (Schritt 1 in docs/Cookidoo-Sync.md).

Läuft am Rechner, nicht im Add-on. Braucht `cookidoo-api` (tools/requirements.txt).
Zugang und Ausgaben liegen in `dev/cookidoo/` (nicht im Git):

    python tools/cookidoo_probe.py login              # Anmeldung (OAuth), fragt E-Mail/Passwort
    python tools/cookidoo_probe.py login --browser    # Anmeldung über den Browser, falls möglich
    python tools/cookidoo_probe.py week               # diese und nächste Woche lesen
    python tools/cookidoo_probe.py week --day 2026-11-09 --weeks 1
    python tools/cookidoo_probe.py roundtrip --recipe r753850 --day 2027-01-15 --yes
    python tools/cookidoo_probe.py add --recipe r753850 --day 2026-11-05 --yes
    python tools/cookidoo_probe.py remove --recipe r753850 --day 2026-11-05 --yes
    python tools/cookidoo_probe.py refresh            # Token erneuern, Ablauf anzeigen

Anmeldung: Beide Wege sind OAuth mit PKCE (Zugang der Cookidoo-Android-App) und
speichern nur die Tokens. `login` fragt E-Mail und Passwort einmal ab, hält sie nur
im Speicher und lässt die Bibliothek das Vorwerk-Formular ausfüllen (`login()`, in
cookidoo-api 0.19.0 der einzige Weg).

`login --browser` braucht `begin_login`/`complete_login`, die es bisher nur im
Entwicklungsstand der Bibliothek gibt. Das Skript zeigt einen Link zur Vorwerk-Anmeldung. Nach dem Anmelden
leitet Vorwerk auf `com.vorwerk.cookidoo://code-grant?code=…&state=…` weiter, eine
Adresse der Cookidoo-App, die der Browser nicht öffnen kann. Diese Adresse kopieren
(Firefox/Edge: F12 → Netzwerk, „Logs beibehalten“ an, letzte Weiterleitung →
Antwort-Kopfzeile `Location`; teils steht sie auch in der Fehlermeldung oder der
Adresszeile) und innerhalb von 5 Minuten einfügen. Ein Passwort speichert das
Skript nicht; die Tokens landen in `dev/cookidoo/token.json` und werden bei jeder
Erneuerung neu geschrieben. Tokens und Codes erscheinen nie in der Ausgabe.

`roundtrip`, `add` und `remove` schreiben in den echten Kalender, nur mit `--yes`.
`roundtrip` plant ein und entfernt sofort wieder, nur für Tage mindestens 60 Tage in
der Zukunft. `add` lässt das Rezept stehen, damit es sich in der Cookidoo-App prüfen
lässt; `remove` nimmt es danach wieder heraus. Beide nur für heute oder später.
"""

import argparse
import asyncio
import getpass
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, CookieJar
from cookidoo_api import (
    Cookidoo,
    CookidooAuthData,
    CookidooConfig,
    CookidooException,
    get_localization_options,
)

DEV_DIR = Path(__file__).resolve().parent.parent / "dev" / "cookidoo"
TOKEN_FILE = DEV_DIR / "token.json"
OUTPUT_FILE = DEV_DIR / "probe_calendar.json"
DEFAULT_LANGUAGE = "de-DE"
# Format von recipe.source_id bei Cookidoo-Rezepten in Tellerplan
TELLERPLAN_ID_PATTERN = re.compile(r"^r\d+$")
MIN_DAYS_AHEAD = 60


def _save_tokens(auth_data: CookidooAuthData) -> None:
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(vars(auth_data)), encoding="utf-8")


async def _client(
    session: ClientSession, language: str, email: str = "", password: str = ""
) -> Cookidoo:
    """Cookidoo-Zugang mit Land und Sprache, z. B. de-DE → Land „de“."""
    country = language.split("-")[-1].lower()
    options = await get_localization_options(country=country, language=language)
    if not options:
        sys.exit(f"Keine Cookidoo-Lokalisierung für {language} gefunden.")
    print(
        f"Lokalisierung: {options[0].country_code} · {options[0].language} · {options[0].url}"
    )
    config = CookidooConfig(localization=options[0], email=email, password=password)
    return Cookidoo(session, config, on_auth_data_update=_save_tokens)


def _restore(cookidoo: Cookidoo) -> None:
    if not TOKEN_FILE.exists():
        sys.exit(
            "Noch nicht angemeldet: zuerst `python tools/cookidoo_probe.py login`."
        )
    cookidoo.load_token(TOKEN_FILE)


def _expiry() -> str:
    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    minutes = (data["expires_at"] - time.time()) / 60
    return f"Access-Token gilt noch {minutes:.0f} Minuten"


async def login(cookidoo: Cookidoo, browser: bool) -> None:
    if not browser:
        await cookidoo.login()
    elif not hasattr(cookidoo, "begin_login"):
        sys.exit(
            "Diese Version von cookidoo-api kann noch nicht über den Browser anmelden."
        )
    else:
        url = await cookidoo.begin_login()
        print("\n1. Diesen Link im Browser öffnen und bei Cookidoo anmelden:\n")
        print(f"   {url}\n")
        print(
            "2. Die Weiterleitung auf com.vorwerk.cookidoo://code-grant?… kopieren (siehe Kopf)."
        )
        callback = input("3. Hier einfügen: ").strip()
        await cookidoo.complete_login(callback)
    cookidoo.save_token(TOKEN_FILE)
    info = await cookidoo.get_user_info()
    print(f"\nAngemeldet als {info.username}. {_expiry()}.")


def _day_summary(day: Any) -> dict[str, Any]:
    return {
        "id": day.id,
        "title": day.title,
        "recipes": [
            {
                "id": recipe.id,
                "name": recipe.name,
                "url": recipe.url,
                "is_custom": recipe.is_custom,
                "id_like_tellerplan": bool(TELLERPLAN_ID_PATTERN.match(recipe.id)),
            }
            for recipe in day.recipes
        ],
        "customer_recipe_ids": day.customer_recipe_ids,
    }


async def read_weeks(
    cookidoo: Cookidoo, first: date, weeks: int
) -> list[dict[str, Any]]:
    days = []
    for week in range(weeks):
        calendar = await cookidoo.get_recipes_in_calendar_week(
            first + timedelta(weeks=week)
        )
        days += [_day_summary(day) for day in calendar]
    return days


def _print_days(days: list[dict[str, Any]]) -> None:
    for day in days:
        names = [f"{r['name']} ({r['id']})" for r in day["recipes"]]
        names += [f"eigenes Rezept {custom}" for custom in day["customer_recipe_ids"]]
        print(f"  {day['id']} {day['title']}: {', '.join(names) or '–'}")


async def week(cookidoo: Cookidoo, first: date, weeks: int) -> None:
    days = await read_weeks(cookidoo, first, weeks)
    _print_days(days)
    OUTPUT_FILE.write_text(
        json.dumps(days, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    odd = {r["id"] for d in days for r in d["recipes"] if not r["id_like_tellerplan"]}
    print(f"\n{len(days)} Tage gespeichert in {OUTPUT_FILE}")
    print(
        "IDs passen alle zu Tellerplan (r…)."
        if not odd
        else f"Andere IDs: {sorted(odd)}"
    )


async def roundtrip(cookidoo: Cookidoo, day: date, recipe_id: str) -> None:
    print(f"Einplanen: {recipe_id} am {day}")
    added = await cookidoo.add_recipes_to_calendar(day, [recipe_id])
    print(f"  Antwort: {[r.id for r in added.recipes]}")
    _print_days(
        [d for d in await read_weeks(cookidoo, day, 1) if d["id"] == day.isoformat()]
    )
    print(f"Entfernen: {recipe_id} am {day}")
    removed = await cookidoo.remove_recipe_from_calendar(day, recipe_id)
    print(f"  Antwort: {[r.id for r in removed.recipes]}")
    _print_days(
        [d for d in await read_weeks(cookidoo, day, 1) if d["id"] == day.isoformat()]
    )


async def _show_day(cookidoo: Cookidoo, day: date) -> None:
    _print_days(
        [d for d in await read_weeks(cookidoo, day, 1) if d["id"] == day.isoformat()]
    )


async def add(cookidoo: Cookidoo, day: date, recipe_id: str) -> None:
    print(f"Einplanen: {recipe_id} am {day}")
    await cookidoo.add_recipes_to_calendar(day, [recipe_id])
    await _show_day(cookidoo, day)
    print("Jetzt in der Cookidoo-App unter „Meine Woche“ prüfen; danach `remove`.")


async def remove(cookidoo: Cookidoo, day: date, recipe_id: str) -> None:
    print(f"Entfernen: {recipe_id} am {day}")
    await cookidoo.remove_recipe_from_calendar(day, recipe_id)
    await _show_day(cookidoo, day)


async def refresh(cookidoo: Cookidoo) -> None:
    print(f"Vorher: {_expiry()}")
    await cookidoo.refresh()
    print(f"Nachher: {_expiry()}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--language", default=DEFAULT_LANGUAGE, help="z. B. de-DE, de-AT"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    login_parser = commands.add_parser("login", help="Anmeldung (OAuth)")
    login_parser.add_argument("--browser", action="store_true", help="über den Browser")
    week_parser = commands.add_parser("week", help="Kalender lesen")
    week_parser.add_argument("--day", type=date.fromisoformat, default=date.today())
    week_parser.add_argument("--weeks", type=int, default=2)
    trip = commands.add_parser("roundtrip", help="einplanen und wieder entfernen")
    trip.add_argument("--recipe", required=True, help="Cookidoo-ID, z. B. r753850")
    trip.add_argument("--day", type=date.fromisoformat, required=True)
    trip.add_argument(
        "--yes", action="store_true", help="wirklich in den Kalender schreiben"
    )
    for name, text in (("add", "einplanen und stehen lassen"), ("remove", "entfernen")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--recipe", required=True, help="Cookidoo-ID, z. B. r753850")
        sub.add_argument("--day", type=date.fromisoformat, required=True)
        sub.add_argument(
            "--yes", action="store_true", help="wirklich in den Kalender schreiben"
        )
    commands.add_parser("refresh", help="Token erneuern")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    if args.command in ("add", "remove") and args.day < date.today():
        sys.exit("Nur für heute oder später; vergangene Tage bleiben unberührt.")
    if args.command in ("roundtrip", "add", "remove") and not args.yes:
        sys.exit("Schreibt in den echten Kalender; mit --yes bestätigen.")
    earliest = date.today() + timedelta(days=MIN_DAYS_AHEAD)
    if args.command == "roundtrip" and args.day < earliest:
        sys.exit(f"Nur für Tage ab {earliest}.")
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    email = password = ""
    if args.command == "login" and not args.browser:
        email = input("Cookidoo-E-Mail: ").strip()
        password = getpass.getpass("Passwort (wird nicht gespeichert): ")
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        cookidoo = await _client(session, args.language, email, password)
        try:
            if args.command == "login":
                await login(cookidoo, args.browser)
                return
            _restore(cookidoo)
            if args.command == "week":
                await week(cookidoo, args.day, args.weeks)
            elif args.command == "roundtrip":
                await roundtrip(cookidoo, args.day, args.recipe)
            elif args.command == "add":
                await add(cookidoo, args.day, args.recipe)
            elif args.command == "remove":
                await remove(cookidoo, args.day, args.recipe)
            else:
                await refresh(cookidoo)
        except CookidooException as error:
            sys.exit(f"Cookidoo meldet: {type(error).__name__}: {error}")


if __name__ == "__main__":
    asyncio.run(main())
