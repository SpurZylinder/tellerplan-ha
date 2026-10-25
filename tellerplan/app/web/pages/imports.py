"""Seite „Importieren“: Rezeptentwürfe oder Lebensmittel als Datei hochladen.

Die Datei sagt selbst, was sie ist („format“): Rezepte aus tools/cookidoo_fetch.py,
Lebensmittel mit Nährwerten aus tools/rewe_fetch.py.
"""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from db import get_session
from modules.foods.importer import (
    FoodImportError,
    FoodImportResult,
    import_foods,
    is_food_document,
)
from modules.importers.service import ImportFormatError, ImportResult, import_document
from web.templating import render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings/import")
SessionDep = Annotated[Session, Depends(get_session)]

# Großzügig für einige Tausend Rezepte; schützt vor versehentlich gewählten großen Dateien.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _render(
    request: Request,
    result: ImportResult | None = None,
    food_result: FoodImportResult | None = None,
    error: str | None = None,
) -> HTMLResponse:
    return render(request, "imports.html", result=result, food_result=food_result, error=error)


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
        document = json.loads(content.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        return _render(request, error="Die Datei ist kein gültiges JSON.")

    if is_food_document(document):
        try:
            food_result = import_foods(session, document)
        except FoodImportError as error:
            return _render(request, error=str(error))
        session.commit()
        logger.info(
            "Lebensmittel-Import aus %s: %d neu, %d aktualisiert, %d übersprungen",
            file.filename,
            food_result.created,
            food_result.updated,
            len(food_result.skipped),
        )
        return _render(request, food_result=food_result)

    try:
        result = import_document(session, document)
    except ImportFormatError as error:
        return _render(request, error=str(error))
    session.commit()
    logger.info(
        "Rezept-Import aus %s: %d neu, %d aktualisiert, %d von %d Zeilen zugeordnet",
        file.filename,
        result.created,
        result.updated,
        result.matched_lines,
        result.lines,
    )
    return _render(request, result=result)
