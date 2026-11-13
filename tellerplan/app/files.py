"""Dateien sicher schreiben.

`write_text_atomic` schreibt erst vollständig in eine Nachbardatei und ersetzt dann
das Ziel in einem Schritt. Bricht das Schreiben ab (Neustart, voller Datenträger),
bleibt die alte Datei heil. Die Nachbardatei entsteht gleich mit den gewünschten
Rechten, nicht erst nachträglich.
"""

import os
from pathlib import Path

# Rechte für neue Dateien, wenn nichts anderes verlangt ist
DEFAULT_FILE_MODE = 0o644


def write_text_atomic(path: Path, content: str, mode: int = DEFAULT_FILE_MODE) -> None:
    """Schreibt `content` (UTF-8) atomar nach `path`; bei Fehler bleibt `path` unverändert."""
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(temporary, flags, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
