"""Web-Oberfläche: serverseitig gerenderte Seiten für den Ingress."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def create_web_router(templates_dir: Path) -> APIRouter:
    templates = Jinja2Templates(directory=templates_dir)
    router = APIRouter(include_in_schema=False)

    @router.get("/", response_class=HTMLResponse)
    def today(request: Request) -> HTMLResponse:
        settings = request.app.state.settings
        return templates.TemplateResponse(
            request,
            "today.html",
            {
                "daily_kcal_limit": settings.daily_kcal_limit,
                "meal_names": settings.meal_names,
            },
        )

    return router
