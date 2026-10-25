"""Zentrale Uhr: welcher Tag gerade „heute“ ist.

Im Add-on übergibt der Supervisor die Zeitzone von Home Assistant als `TZ`
(z. B. „Europe/Berlin“). Die Zeitzonendaten kommen aus dem Paket `tzdata`,
damit das auch ohne Zeitzonendaten im Image stimmt. Ohne `TZ` gilt die Zeit
des Rechners, lokal also die eigene.
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TZ_ENV_VAR = "TZ"


def local_zone() -> ZoneInfo | None:
    """Zeitzone aus `TZ`; None, wenn nicht gesetzt oder unbekannt."""
    name = os.environ.get(TZ_ENV_VAR, "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        return None


def now() -> datetime:
    """Aktuelle Uhrzeit in der Zeitzone von Home Assistant, ohne Zonenangabe (für SQLite)."""
    return datetime.now(local_zone()).replace(tzinfo=None)


def today() -> date:
    """Heutiges Datum in der Zeitzone von Home Assistant."""
    return now().date()
