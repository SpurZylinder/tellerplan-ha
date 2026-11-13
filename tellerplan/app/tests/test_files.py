"""Atomares Schreiben von Dateien."""

import os
import sys
from pathlib import Path

import pytest

import files as files_module
from files import write_text_atomic


def test_writes_new_file(tmp_path: Path) -> None:
    target = tmp_path / "neu.json"

    write_text_atomic(target, "{}")

    assert target.read_text(encoding="utf-8") == "{}"
    assert not target.with_name("neu.json.tmp").exists()


def test_failed_replace_keeps_old_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "alt.json"
    target.write_text("alt", encoding="utf-8")

    def broken_replace(source: object, destination: object) -> None:
        raise OSError("Datenträger voll")

    monkeypatch.setattr(files_module.os, "replace", broken_replace)

    with pytest.raises(OSError, match="Datenträger voll"):
        write_text_atomic(target, "neu")

    assert target.read_text(encoding="utf-8") == "alt"
    assert not target.with_name("alt.json.tmp").exists()


def test_leftover_temporary_file_is_replaced(tmp_path: Path) -> None:
    target = tmp_path / "datei.json"
    target.with_name("datei.json.tmp").write_text("Rest", encoding="utf-8")

    write_text_atomic(target, "neu")

    assert target.read_text(encoding="utf-8") == "neu"


@pytest.mark.skipif(sys.platform == "win32", reason="Dateirechte nur unter POSIX")
def test_file_gets_the_requested_mode(tmp_path: Path) -> None:
    target = tmp_path / "geheim.json"
    old_umask = os.umask(0)
    try:
        write_text_atomic(target, "{}", 0o600)
    finally:
        os.umask(old_umask)

    assert target.stat().st_mode & 0o777 == 0o600
