"""Jinja-Umgebung für alle Seiten.

Links entstehen über `url(name, **params)`: ein Pfad mit Ingress-Präfix, aber ohne
Host. Absolute URLs (`url_for`) würden hinter dem Home-Assistant-Proxy brechen.
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from jinja2.runtime import Context

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def path_for(request: Request, name: str, **params: Any) -> str:
    """Pfad einer Route samt Ingress-Präfix, z. B. `/api/hassio_ingress/x/recipes`."""
    root = request.scope.get("root_path", "")
    path = request.app.url_path_for(name, **{key: str(value) for key, value in params.items()})
    return f"{root}{path}"


@pass_context
def _url(context: Context, name: str, **params: Any) -> str:
    return path_for(context["request"], name, **params)


def _format_number(value: float | None, digits: int = 0) -> str:
    """Zahl im deutschen Format, z. B. 1234.5 → „1.234,5“; None → „–“."""
    if value is None:
        return "–"
    text = f"{value:,.{digits}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_amount(value: float | None) -> str:
    """Menge ohne überflüssige Nullen, z. B. 1.5 → „1,5“, 2.0 → „2“."""
    if value is None:
        return ""
    return f"{round(value, 2):g}".replace(".", ",")


WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _format_day(value: date) -> str:
    """Kurzes Datum mit Wochentag, z. B. „Mo 26.10.“."""
    return f"{WEEKDAYS[value.weekday()]} {value:%d.%m.}"


def _add_days(value: date, days: int) -> date:
    return value + timedelta(days=days)


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["url"] = _url
templates.env.filters["num"] = _format_number
templates.env.filters["day"] = _format_day
templates.env.filters["amount"] = _format_amount
templates.env.filters["add_days"] = _add_days


def render(request: Request, template: str, tab: str | None = None, **context: Any) -> Any:
    """Rendert eine Seite; `tab` markiert den aktiven Eintrag der Tab-Leiste."""
    signed_in = getattr(request.state, "web_session", None) is not None
    return templates.TemplateResponse(
        request, template, {"tab": tab, "signed_in": signed_in, **context}
    )
