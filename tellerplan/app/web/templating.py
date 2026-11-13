"""Jinja-Umgebung für alle Seiten.

Links entstehen über `url(name, **params)`: ein Pfad mit Ingress-Präfix, aber ohne
Host. Absolute URLs (`url_for`) würden hinter dem Home-Assistant-Proxy brechen.

Statische Dateien (`url('static', path=…)`) bekommen `?v=` mit einem Hash ihres Inhalts.
Ändert sich eine Datei mit einem Update, ändert sich der Link, und Safari auf dem iPhone
lädt sie neu, statt die alte aus dem Cache zu nehmen.
"""

import hashlib
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from jinja2.runtime import Context

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
# Stellen des Inhalts-Hashes im Link; genug, damit sich Versionen sicher unterscheiden
ASSET_HASH_LENGTH = 10


def path_for(request: Request, name: str, **params: Any) -> str:
    """Pfad einer Route samt Ingress-Präfix, z. B. `/api/hassio_ingress/x/recipes`."""
    root = request.scope.get("root_path", "")
    path = request.app.url_path_for(name, **{key: str(value) for key, value in params.items()})
    return f"{root}{path}"


def asset_version(path: str) -> str:
    """Kurzer Hash des Inhalts einer statischen Datei; leer, wenn es sie nicht gibt."""
    file = STATIC_DIR / path
    try:
        modified = file.stat().st_mtime_ns
    except OSError:
        return ""
    return _content_hash(file, modified)


@lru_cache(maxsize=64)
def _content_hash(file: Path, modified: int) -> str:
    # `modified` gehört zum Schlüssel: Eine geänderte Datei wird neu gehasht (lokal beim Entwickeln)
    return hashlib.sha256(file.read_bytes()).hexdigest()[:ASSET_HASH_LENGTH]


@pass_context
def _url(context: Context, name: str, **params: Any) -> str:
    path = path_for(context["request"], name, **params)
    if name == "static" and (version := asset_version(str(params.get("path", "")))):
        return f"{path}?v={version}"
    return path


def _format_number(value: float | None, digits: int = 0) -> str:
    """Zahl im deutschen Format, z. B. 1234.5 → „1.234,5“; None → „–“."""
    if value is None:
        return "–"
    text = f"{value:,.{digits}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_amount(value: float | None) -> str:
    """Menge ohne überflüssige Nullen, z. B. 1.5 → „1,5“, 2.0 → „2“."""
    if value is None:
        return ""
    return f"{round(value, 2):g}".replace(".", ",")


def external_url(value: str | None) -> str:
    """Nur http(s)-Links durchlassen; `javascript:` & Co. werden zu „#“.

    Jinja maskiert Sonderzeichen, schützt aber nicht vor gefährlichen Schemata in `href`.
    Externe Links (Rezeptquellen, Cookidoo) laufen darum immer durch diesen Filter.
    """
    scheme = urlsplit(value or "").scheme.lower()
    return value if value and scheme in ("http", "https") else "#"


WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def format_day(value: date) -> str:
    """Kurzes Datum mit Wochentag, z. B. „Mo 26.10.“."""
    return f"{WEEKDAYS[value.weekday()]} {value:%d.%m.}"


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["url"] = _url
templates.env.filters["num"] = _format_number
templates.env.filters["day"] = format_day
templates.env.filters["amount"] = format_amount
templates.env.filters["external_url"] = external_url


def render(request: Request, template: str, tab: str | None = None, **context: Any) -> Any:
    """Rendert eine Seite; `tab` markiert den aktiven Eintrag der Tab-Leiste."""
    signed_in = getattr(request.state, "web_session", None) is not None
    return templates.TemplateResponse(
        request, template, {"tab": tab, "signed_in": signed_in, **context}
    )
