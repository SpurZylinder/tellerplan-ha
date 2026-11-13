"""Links aus den Vorlagen: statische Dateien mit Inhalts-Hash (Befund K13)."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import web.templating as templating_module
from web.templating import ASSET_HASH_LENGTH, asset_version


def test_static_links_carry_a_content_hash(ingress_client: TestClient) -> None:
    text = ingress_client.get("/").text

    assert f'static/app.css?v={asset_version("app.css")}"' in text
    assert len(asset_version("app.css")) == ASSET_HASH_LENGTH


def test_changed_static_file_gets_a_new_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(templating_module, "STATIC_DIR", tmp_path)
    file = tmp_path / "app.css"
    file.write_text("a {}", encoding="utf-8")
    before = asset_version("app.css")

    file.write_text("b {}", encoding="utf-8")
    os.utime(file, ns=(file.stat().st_atime_ns, file.stat().st_mtime_ns + 1_000_000))

    assert asset_version("app.css") != before
    assert asset_version("fehlt.css") == ""
