"""Seite „Rezepte importieren“: Entwurfsdatei hochladen (z. B. aus tools/cookidoo_fetch.py)."""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from db import get_session
from modules.importers.service import ImportFormatError, ImportResult, import_document
from web.templating import render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings/import")
SessionDep = Annotated[Session, Depends(get_session)]

# Großzügig für einige Tausend Rezepte; schützt vor versehentlich gewählten großen Dateien.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _render(
    request: Request, result: ImportResult | None = None, error: str | None = None
) -> HTMLResponse:
    return render(request, "imports.html", result=result, error=error)


@router.get("", response_class=HTMLResponse)
def import_page(request: Request) -> HTMLResponse:
    return _render(request)


@router.post("", response_class=HTMLResponse)
def import_upload(
    request: Request, session: SessionDep, file: Annotated[UploadFile, File()]
) -> HTMLResponse:
    # Synchron, damit FastAPI den Import in einem Thread ausführt und die Ports frei bleiben
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        return _render(request, error="Die Datei ist zu groß (höchstens 10 MB).")
    try:
        result = import_document(session, json.loads(content.decode("utf-8")))
    except UnicodeDecodeError, json.JSONDecodeError:
        return _render(request, error="Die Datei ist kein gültiges JSON.")
    except ImportFormatError as error:
        return _render(request, error=str(error))
    session.commit()
    logger.info(
        "Import aus %s: %d neu, %d aktualisiert, %d von %d Zeilen zugeordnet",
        file.filename,
        result.created,
        result.updated,
        result.matched_lines,
        result.lines,
    )
    return _render(request, result=result)
