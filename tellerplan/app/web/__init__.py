"""Web-Oberfläche: serverseitig gerenderte Seiten für Ingress und Vollbild-App."""

from fastapi import APIRouter, Depends

from web.access import require_login
from web.pages import foods, login, options, plan, recipes, shopping, today

router = APIRouter(include_in_schema=False)
router.include_router(login.router)

# Alle übrigen Seiten: auf dem Port der Vollbild-App nur mit Anmeldung über Home Assistant
protected_pages = APIRouter(dependencies=[Depends(require_login)])
for page in (today, shopping, plan, recipes, foods, options):
    protected_pages.include_router(page.router)
router.include_router(protected_pages)
