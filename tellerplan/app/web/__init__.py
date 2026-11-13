"""Web-Oberfläche: serverseitig gerenderte Seiten für Ingress und Vollbild-App."""

from fastapi import APIRouter, Depends

from web.access import require_login, require_user
from web.pages import (
    foods,
    imports,
    login,
    matching,
    plan,
    recipes,
    settings_page,
    shopping,
    today,
)

router = APIRouter(include_in_schema=False)
router.include_router(login.router)

# Alle übrigen Seiten: auf dem Port der Vollbild-App nur mit Anmeldung über Home Assistant,
# überall nur für freigegebene Benutzer; Verwalter-Seiten prüfen zusätzlich require_admin
protected_pages = APIRouter(dependencies=[Depends(require_login), Depends(require_user)])
for page in (today, shopping, plan, matching, recipes, foods, imports, settings_page):
    protected_pages.include_router(page.router)
router.include_router(protected_pages)
