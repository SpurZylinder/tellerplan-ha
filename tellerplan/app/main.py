"""FastAPI-App: Web-Oberfläche (Ingress) und JSON-API (Port 8099).

Lokal starten: `uvicorn main:create_app --factory --reload`
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.v1 import router as api_v1_router
from db import create_db_engine, create_session_factory
from security import PortAccessMiddleware
from settings import Settings, get_settings
from web import create_web_router

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Baut die App; ohne Argument mit den Einstellungen aus options.json."""
    settings = settings or get_settings()
    app = FastAPI(title="Tellerplan", docs_url="/api/docs", openapi_url="/api/openapi.json")

    engine = create_db_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    app.add_middleware(PortAccessMiddleware, settings=settings)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(create_web_router(WEB_DIR / "templates"))
    return app
