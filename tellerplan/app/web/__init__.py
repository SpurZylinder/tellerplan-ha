"""Web-Oberfläche: serverseitig gerenderte Seiten für den Ingress."""

from fastapi import APIRouter

from web.pages import foods, plan, recipes, today

router = APIRouter(include_in_schema=False)
for page in (today, recipes, plan, foods):
    router.include_router(page.router)
