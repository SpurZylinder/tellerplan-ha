"""Optionen stehen an drei Stellen; dieser Test hält sie gleich (Befund C-C).

- `config.yaml`: Vorgabewerte (`options`) und Prüfregeln (`schema`) für Home Assistant
- `settings.py`: Felder und Wertebereiche, mit denen die App die Optionen liest
- `dev/options.example.json`: Vorlage für die lokale Entwicklung
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic.fields import FieldInfo

from settings import Settings, option_range

APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_YAML = APP_DIR.parent / "config.yaml"
OPTIONS_EXAMPLE = APP_DIR.parents[1] / "dev" / "options.example.json"
# Felder in `Settings`, die keine Add-on-Optionen sind (feste Ports aus config.yaml)
TECHNICAL_FIELDS = {"ingress_port", "api_port"}
# z. B. „int(500,10000)“ oder „float(0,1)“
NUMBER_RULE = re.compile(r"^(int|float)\((?P<low>[^,]*),(?P<high>[^)]*)\)$")
# z. B. „match(^[a-z]{2}-[A-Z]{2}$)“
MATCH_RULE = re.compile(r"^match\((?P<pattern>.*)\)$")


def _config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))


def _option_fields() -> set[str]:
    return set(Settings.model_fields) - TECHNICAL_FIELDS


def _pattern(field: FieldInfo) -> str | None:
    return next((item.pattern for item in field.metadata if hasattr(item, "pattern")), None)


def test_config_defaults_and_schema_cover_all_settings() -> None:
    config = _config()

    assert set(config["options"]) == _option_fields()
    assert set(config["schema"]) == _option_fields()


def test_config_defaults_are_valid_settings() -> None:
    Settings.model_validate(_config()["options"])


def test_options_example_matches_settings() -> None:
    example = json.loads(OPTIONS_EXAMPLE.read_text(encoding="utf-8"))

    assert set(example) == _option_fields()
    Settings.model_validate(example)


@pytest.mark.parametrize(
    "name",
    [name for name, rule in _config()["schema"].items() if isinstance(rule, str)],
)
def test_schema_rule_matches_settings_field(name: str) -> None:
    rule = _config()["schema"][name]
    field = Settings.model_fields[name]

    if number := NUMBER_RULE.match(rule):
        assert option_range(name) == (float(number["low"]), float(number["high"]))
        assert field.annotation is (int if number[1] == "int" else float)
    elif match := MATCH_RULE.match(rule):
        assert _pattern(field) == match["pattern"]
    else:
        assert rule in ("str", "password")
        assert field.annotation in (str, Path)
