"""Zentrale Parameter der App.

Alle konfigurierbaren Werte kommen ausschließlich aus `options.json`
(im Add-on `/data/options.json`, lokal z. B. `dev/options.json`).
Der Pfad zur Datei steht in der Umgebungsvariable `TELLERPLAN_OPTIONS`.
Die Einstellseite ändert Werte über `save_options`; im Add-on gehen sie
zusätzlich an den Supervisor, damit Home Assistant dieselben Werte zeigt.
"""

import json
import logging
import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from annotated_types import Ge, Le
from pydantic import BaseModel, ConfigDict, Field, model_validator

from supervisor import set_own_options, supervisor_token

OPTIONS_ENV_VAR = "TELLERPLAN_OPTIONS"
DEFAULT_OPTIONS_PATH = Path("/data/options.json")
logger = logging.getLogger(__name__)

# Entität einer To-do-Liste in Home Assistant, z. B. „todo.furth“; leer = keine
TODO_ENTITY_PATTERN = r"^(todo\.\w+)?$"


class Settings(BaseModel):
    """Laufzeit-Einstellungen; die Felder entsprechen den Add-on-Optionen."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    # Wertebereiche wie im Schema von config.yaml
    daily_kcal_limit: int = Field(ge=500, le=10000)
    protein_goal_g: int = Field(ge=0, le=500)
    fat_goal_g: int = Field(ge=0, le=500)
    carbs_goal_g: int = Field(ge=0, le=1000)
    meal_names: list[str] = Field(min_length=1)
    plan_default_meal: str
    ranking_protein_weight: float = Field(ge=0, le=1)
    # Einkaufsliste: Stichwörter für Vorratsartikel und Ziel-Liste in Home Assistant
    pantry_keywords: list[str]
    bring_list_entity: str = Field(pattern=TODO_ENTITY_PATTERN)
    api_token: str
    database_path: Path

    # Technische Ports, durch config.yaml des Add-ons festgelegt.
    ingress_port: int = 8000
    api_port: int = 8099

    @model_validator(mode="after")
    def _plan_default_meal_exists(self) -> Settings:
        if self.plan_default_meal not in self.meal_names:
            raise ValueError("plan_default_meal muss einer der meal_names sein")
        return self

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


def options_path() -> Path:
    """Pfad zur options.json aus der Umgebung, sonst der Add-on-Standard."""
    return Path(os.environ.get(OPTIONS_ENV_VAR, DEFAULT_OPTIONS_PATH))


def option_range(name: str) -> tuple[float, float]:
    """Kleinster und größter erlaubter Wert einer Zahlen-Option."""
    metadata = Settings.model_fields[name].metadata
    minimum = next(item.ge for item in metadata if isinstance(item, Ge))
    maximum = next(item.le for item in metadata if isinstance(item, Le))
    return minimum, maximum


def _read_options(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_settings(path: Path) -> Settings:
    """Liest und prüft options.json; relative DB-Pfade gelten relativ zur Datei."""
    raw = _read_options(path)
    settings = Settings.model_validate(raw)
    if not settings.database_path.is_absolute():
        resolved = (path.parent / settings.database_path).resolve()
        settings = settings.model_copy(update={"database_path": resolved})
    return settings


def save_options(path: Path, changes: Mapping[str, Any]) -> Settings:
    """Ändert einzelne Optionen und liefert die neuen Einstellungen.

    Im Add-on gehen alle Optionen zuerst an den Supervisor: Er prüft sie gegen das
    Schema, zeigt sie im Reiter „Konfiguration“ und schreibt sie beim nächsten Start
    wieder nach options.json. Die Datei wird zusätzlich sofort geschrieben, damit die
    App ohne Neustart mit den neuen Werten weiterläuft.
    """
    options = {**_read_options(path), **changes}
    Settings.model_validate(options)
    token = supervisor_token()
    if token:
        set_own_options(options, token)
    path.write_text(json.dumps(options, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Optionen gespeichert: %s", ", ".join(sorted(changes)))
    return load_settings(path)


@lru_cache
def get_settings() -> Settings:
    """Einstellungen der laufenden App (einmal gelesen, dann zwischengespeichert)."""
    return load_settings(options_path())
