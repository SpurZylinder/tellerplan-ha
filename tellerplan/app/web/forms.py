"""Hilfen für HTML-Formulare: deutsche Zahlen lesen, Weiterleitungen."""

from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse

from web.templating import path_for


class FormError(ValueError):
    """Eingabefehler mit einer Meldung für die Oberfläche."""


def parse_number(value: str | None, label: str, required: bool = False) -> float | None:
    """Liest „1,5“ oder „1.5“; leer ergibt None (oder einen Fehler, wenn Pflicht)."""
    text = (value or "").strip().replace(",", ".")
    if not text:
        if required:
            raise FormError(f"{label} fehlt.")
        return None
    try:
        number = float(text)
    except ValueError as error:
        raise FormError(f"{label} ist keine Zahl.") from error
    if number < 0:
        raise FormError(f"{label} darf nicht negativ sein.")
    return number


def required_number(value: str | None, label: str) -> float:
    number = parse_number(value, label, required=True)
    assert number is not None
    return number


def clean_text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def redirect_to(
    request: Request,
    name: str,
    anchor: str = "",
    query: dict[str, str] | None = None,
    **params: Any,
) -> RedirectResponse:
    """303-Weiterleitung nach einem POST (Post/Redirect/Get)."""
    url = path_for(request, name, **params)
    if query:
        url = f"{url}?{urlencode(query)}"
    return RedirectResponse(f"{url}{anchor}", status_code=303)
