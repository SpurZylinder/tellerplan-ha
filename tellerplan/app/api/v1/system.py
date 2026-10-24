"""Systemendpunkte: Erreichbarkeit und Datenbankzustand."""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["System"])


class Health(BaseModel):
    status: str
    database: str


@router.get("/health")
def health(request: Request) -> Health:
    """Prüft, ob die App läuft und die Datenbank antwortet."""
    with request.app.state.engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return Health(status="ok", database="ok")
