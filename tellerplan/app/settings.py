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
# Sprache und Land von Cookidoo, z. B. „de-DE“ (cookidoo.de) oder „de-AT“ (cookidoo.at)
COOKIDOO_LOCALE_PATTERN = r"^[a-z]{2}-[A-Z]{2}$"
# Datei mit den Cookidoo-Tokens, neben der Datenbank (Teil der HA-Backups)
COOKIDOO_TOKEN_FILE = "cookidoo_token.json"
# Basis-URL ohne Pfad, z. B. „http://homeassistant.local:8123“; leer = automatisch
HOMEASSISTANT_URL_PATTERN = r"^(https?://[^/\s]+)?$"


class StandardUnit(BaseModel):
    """Gramm je Einheit für alle Lebensmittel ohne eigene Angabe, z. B. 1 EL = 15 g."""

    model_config = ConfigDict(frozen=True)

    unit: str = Field(min_length=1)
    grams: float = Field(ge=0.1, le=1000)


class MealCategory(BaseModel):
    """Beim Eintragen für `meal` zuerst nur Rezepte dieser Kategorie zeigen."""

    model_config = ConfigDict(frozen=True)

    meal: str
    category: str


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
    # Mahlzeiten, für die beim Eintragen das Rezept vom Vortag (gleiche Mahlzeit) oben steht
    suggest_yesterday_meals: list[str]
    # Beim Eintragen stehen Lebensmittel und Rezepte weiter oben, die in so vielen
    # zurückliegenden Tagen oft gegessen wurden
    frequency_window_days: int = Field(ge=7, le=365)
    recipe_categories: list[str] = Field(min_length=1)
    meal_categories: list[MealCategory]
    standard_units: list[StandardUnit]
    ranking_protein_weight: float = Field(ge=0, le=1)
    # Einkaufsliste: Stichwörter für Vorratsartikel und Ziel-Liste in Home Assistant
    pantry_keywords: list[str]
    bring_list_entity: str = Field(pattern=TODO_ENTITY_PATTERN)
    # Cookidoo-Kalender „Meine Woche“; die Anmeldung selbst steht nicht in den Optionen
    cookidoo_locale: str = Field(pattern=COOKIDOO_LOCALE_PATTERN)
    api_token: str
    # Adresse von Home Assistant aus Sicht des iPhones, z. B. http://homeassistant.local:8123;
    # leer = gleicher Host wie Tellerplan, Port 8123
    homeassistant_url: str = Field(pattern=HOMEASSISTANT_URL_PATTERN)
    database_path: Path

    # Technische Ports, durch config.yaml des Add-ons festgelegt.
    ingress_port: int = 8000
    api_port: int = 8099

    @model_validator(mode="after")
    def _meals_and_categories_exist(self) -> Settings:
        if self.plan_default_meal not in self.meal_names:
            raise ValueError("plan_default_meal muss einer der meal_names sein")
        if unknown := set(self.suggest_yesterday_meals) - set(self.meal_names):
            raise ValueError(f"suggest_yesterday_meals kennt {sorted(unknown)} nicht")
        for pair in self.meal_categories:
            if pair.meal not in self.meal_names:
                raise ValueError(f"meal_categories: Mahlzeit „{pair.meal}“ unbekannt")
            if pair.category not in self.recipe_categories:
                raise ValueError(f"meal_categories: Kategorie „{pair.category}“ unbekannt")
        return self

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"

    @property
    def cookidoo_token_path(self) -> Path:
        return self.database_path.with_name(COOKIDOO_TOKEN_FILE)

    @property
    def standard_unit_grams(self) -> dict[str, float]:
        """Standard-Einheiten als Zuordnung Einheit → Gramm, z. B. {"EL": 15.0}."""
        return {item.unit: item.grams for item in self.standard_units}

    def categories_for_meal(self, meal: str | None) -> list[str]:
        """Kategorien, die beim Eintragen für diese Mahlzeit vorgefiltert werden."""
        return [pair.category for pair in self.meal_categories if pair.meal == meal]


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
