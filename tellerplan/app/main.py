"""FastAPI-App: Web-Oberfläche (Ingress) und JSON-API (Port 8099).

Lokal starten: `uvicorn main:create_app --factory --reload`
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.v1 import router as api_v1_router
from db import create_db_engine, create_session_factory
from security import PortAccessMiddleware
from settings import Settings, get_settings, options_path
from web import router as web_router

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(settings: Settings | None = None, options_file: Path | None = None) -> FastAPI:
    """Baut die App; ohne Argumente mit den Einstellungen aus options.json.

    `options_file` ist die Datei, in die die Einstellseite schreibt.
    """
    settings = settings or get_settings()
    app = FastAPI(title="Tellerplan", docs_url="/api/docs", openapi_url="/api/openapi.json")

    engine = create_db_engine(settings)
    app.state.settings = settings
    app.state.options_file = options_file or options_path()
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    app.add_middleware(PortAccessMiddleware, settings=settings)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(web_router)
    return app
