"""FastAPI-App: Web-Oberfläche (Ingress und Vollbild-App) und JSON-API (Port 8099).

Lokal starten: `uvicorn main:create_app --factory --reload`
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from api.v1 import router as api_v1_router
from db import create_db_engine, create_session_factory
from modules.nutrition.service import set_standard_units
from security import PortAccessMiddleware
from settings import Settings, get_settings, options_path
from web import router as web_router
from web.access import LoginRequired
from web.templating import path_for

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
    set_standard_units(settings.standard_unit_grams)

    app.add_middleware(PortAccessMiddleware, settings=settings)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(web_router)
    app.add_exception_handler(LoginRequired, _to_login)
    return app


def _to_login(request: Request, _error: Exception) -> Response:
    """Ohne Sitzung zur Anmeldung; HTMX-Anfragen laden dafür die ganze Seite neu."""
    target = path_for(request, "login_start")
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)
