"""Zentrale Parameter der App.

Alle konfigurierbaren Werte kommen ausschließlich aus `options.json`
(im Add-on `/data/options.json`, lokal z. B. `dev/options.json`).
Der Pfad zur Datei steht in der Umgebungsvariable `TELLERPLAN_OPTIONS`.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

OPTIONS_ENV_VAR = "TELLERPLAN_OPTIONS"
DEFAULT_OPTIONS_PATH = Path("/data/options.json")


class Settings(BaseModel):
    """Laufzeit-Einstellungen; die Felder entsprechen den Add-on-Optionen."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    daily_kcal_limit: int = Field(gt=0)
    protein_goal_g: int = Field(ge=0)
    fat_goal_g: int = Field(ge=0)
    carbs_goal_g: int = Field(ge=0)
    meal_names: list[str] = Field(min_length=1)
    plan_default_meal: str
    ranking_protein_weight: float = Field(ge=0, le=1)
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


def load_settings(path: Path) -> Settings:
    """Liest und prüft options.json; relative DB-Pfade gelten relativ zur Datei."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    settings = Settings.model_validate(raw)
    if not settings.database_path.is_absolute():
        resolved = (path.parent / settings.database_path).resolve()
        settings = settings.model_copy(update={"database_path": resolved})
    return settings


@lru_cache
def get_settings() -> Settings:
    """Einstellungen der laufenden App (einmal gelesen, dann zwischengespeichert)."""
    return load_settings(options_path())
