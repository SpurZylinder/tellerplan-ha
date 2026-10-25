"""Web-Oberfläche: serverseitig gerenderte Seiten für den Ingress."""

from fastapi import APIRouter

from web.pages import foods, options, plan, recipes, shopping, today

router = APIRouter(include_in_schema=False)
for page in (today, shopping, plan, recipes, foods, options):
    router.include_router(page.router)
