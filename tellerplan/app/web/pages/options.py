"""Seite „Einstellungen“: Tagesziele ändern, Einstieg zu den Lebensmitteln.

Die Werte bleiben Add-on-Optionen (options.json); die Seite schreibt sie nur zurück.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from settings import Settings, option_range, save_options
from supervisor import SupervisorError, supervisor_token
from web.forms import FormError, redirect_to, required_number
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


def _render(
    request: Request,
    values: dict[str, Any],
    error: str | None = None,
    saved: bool = False,
) -> HTMLResponse:
    return render(
        request,
        "settings.html",
        fields=GOAL_FIELDS,
        values=values,
        error=error,
        saved=saved,
        in_addon=supervisor_token() is not None,
    )


def _current_values(settings: Settings) -> dict[str, Any]:
    return {field.name: getattr(settings, field.name) for field in GOAL_FIELDS}


def _parse_goal(field: GoalField, text: str) -> int:
    number = required_number(text, field.label)
    if not number.is_integer():
        raise FormError(f"{field.label} muss eine ganze Zahl sein.")
    if not field.minimum <= number <= field.maximum:
        bounds = f"{field.minimum:g} und {field.maximum:g} {field.unit}"
        raise FormError(f"{field.label} muss zwischen {bounds} liegen.")
    return int(number)


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
) -> Response:
    texts = {
        "daily_kcal_limit": daily_kcal_limit,
        "protein_goal_g": protein_goal_g,
        "fat_goal_g": fat_goal_g,
        "carbs_goal_g": carbs_goal_g,
    }
    try:
        changes = {field.name: _parse_goal(field, texts[field.name]) for field in GOAL_FIELDS}
        request.app.state.settings = save_options(request.app.state.options_file, changes)
    except FormError as error:
        return _render(request, texts, error=str(error))
    except SupervisorError as error:
        message = f"Home Assistant hat die Werte nicht übernommen: {error}"
        return _render(request, texts, error=message)
    return redirect_to(request, "settings_page", query={"saved": "1"})
