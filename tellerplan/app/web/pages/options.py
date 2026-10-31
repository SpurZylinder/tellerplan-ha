"""Seite „Einstellungen“: Tagesziele, Einkaufsliste, Cookidoo, Einstieg zu den Lebensmitteln.

Die Werte bleiben Add-on-Optionen (options.json); die Seite schreibt sie nur zurück.
Die Cookidoo-Verbindung ist keine Option: Sie besteht aus Tokens in einer Datei neben
der Datenbank, E-Mail und Passwort werden nur für die Anmeldung weitergereicht.
"""

import re
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from cookidoo import CookidooAccount, CookidooError
from settings import TODO_ENTITY_PATTERN, Settings, option_range, save_options
from supervisor import SupervisorError, supervisor_token
from web.forms import FormError, clean_text, redirect_to, required_number
from web.templating import render

router = APIRouter(prefix="/settings")


@dataclass(frozen=True)
class GoalField:
    name: str
    label: str
    unit: str

    @property
    def minimum(self) -> float:
        return option_range(self.name)[0]

    @property
    def maximum(self) -> float:
        return option_range(self.name)[1]


GOAL_FIELDS = (
    GoalField("daily_kcal_limit", "Tageslimit", "kcal"),
    GoalField("protein_goal_g", "Eiweiß", "g"),
    GoalField("fat_goal_g", "Fett", "g"),
    GoalField("carbs_goal_g", "Kohlenhydrate", "g"),
)


def cookidoo_account(settings: Settings) -> CookidooAccount:
    return CookidooAccount(settings.cookidoo_token_path, settings.cookidoo_locale)


def _render(
    request: Request,
    values: dict[str, Any],
    error: str | None = None,
    saved: bool = False,
    cookidoo_error: str | None = None,
    cookidoo_email: str = "",
) -> HTMLResponse:
    settings = request.app.state.settings
    return render(
        request,
        "settings.html",
        fields=GOAL_FIELDS,
        values=values,
        error=error,
        saved=saved,
        in_addon=supervisor_token() is not None,
        cookidoo_user=cookidoo_account(settings).username(),
        cookidoo_locale=settings.cookidoo_locale,
        cookidoo_error=cookidoo_error,
        cookidoo_email=cookidoo_email,
    )


def _current_values(settings: Settings) -> dict[str, Any]:
    values = {field.name: getattr(settings, field.name) for field in GOAL_FIELDS}
    values["pantry_keywords"] = "\n".join(settings.pantry_keywords)
    values["bring_list_entity"] = settings.bring_list_entity
    return values


def _parse_goal(field: GoalField, text: str) -> int:
    number = required_number(text, field.label, unit=field.unit)
    if not number.is_integer():
        raise FormError(f"{field.label} muss eine ganze Zahl sein.")
    if not field.minimum <= number <= field.maximum:
        bounds = f"{field.minimum:g} und {field.maximum:g} {field.unit}"
        raise FormError(f"{field.label} muss zwischen {bounds} liegen.")
    return int(number)


def _parse_keywords(text: str) -> list[str]:
    """Ein Stichwort pro Zeile oder durch Kommas getrennt; doppelte fallen weg."""
    words = (word.strip().casefold() for word in re.split(r"[,\n]", text))
    return list(dict.fromkeys(word for word in words if word))


def _parse_list_entity(text: str) -> str:
    entity = clean_text(text) or ""
    if not re.fullmatch(TODO_ENTITY_PATTERN, entity):
        raise FormError("Bring-Liste muss eine To-do-Entität sein, z. B. todo.furth.")
    return entity


@router.get("", response_class=HTMLResponse)
def settings_page(request: Request, saved: bool = False) -> HTMLResponse:
    return _render(request, _current_values(request.app.state.settings), saved=saved)


@router.post("", response_model=None)
def settings_save(
    request: Request,
    daily_kcal_limit: Annotated[str, Form()] = "",
    protein_goal_g: Annotated[str, Form()] = "",
    fat_goal_g: Annotated[str, Form()] = "",
    carbs_goal_g: Annotated[str, Form()] = "",
    pantry_keywords: Annotated[str, Form()] = "",
    bring_list_entity: Annotated[str, Form()] = "",
) -> Response:
    texts = {
        "daily_kcal_limit": daily_kcal_limit,
        "protein_goal_g": protein_goal_g,
        "fat_goal_g": fat_goal_g,
        "carbs_goal_g": carbs_goal_g,
        "pantry_keywords": pantry_keywords,
        "bring_list_entity": bring_list_entity,
    }
    try:
        changes: dict[str, Any] = {
            field.name: _parse_goal(field, texts[field.name]) for field in GOAL_FIELDS
        }
        changes["pantry_keywords"] = _parse_keywords(pantry_keywords)
        changes["bring_list_entity"] = _parse_list_entity(bring_list_entity)
        request.app.state.settings = save_options(request.app.state.options_file, changes)
    except FormError as error:
        return _render(request, texts, error=str(error))
    except SupervisorError as error:
        message = f"Home Assistant hat die Werte nicht übernommen: {error}"
        return _render(request, texts, error=message)
    return redirect_to(request, "settings_page", query={"saved": "1"})


@router.post("/cookidoo", response_model=None)
def cookidoo_connect(
    request: Request,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> Response:
    """Meldet bei Cookidoo an; gespeichert werden nur die Tokens, nie das Passwort."""
    values = _current_values(request.app.state.settings)
    if not email.strip() or not password:
        return _render(
            request,
            values,
            cookidoo_error="Bitte E-Mail und Passwort angeben.",
            cookidoo_email=email,
        )
    try:
        cookidoo_account(request.app.state.settings).connect(email.strip(), password)
    except CookidooError as error:
        return _render(request, values, cookidoo_error=str(error), cookidoo_email=email)
    return redirect_to(request, "settings_page", anchor="#cookidoo")


@router.post("/cookidoo/disconnect", response_model=None)
def cookidoo_disconnect(request: Request) -> Response:
    cookidoo_account(request.app.state.settings).disconnect()
    return redirect_to(request, "settings_page", anchor="#cookidoo")
