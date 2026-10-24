"""JSON-API v1 für UI, Kurzbefehle und Skripte."""

from fastapi import APIRouter

from api.v1 import recipes, system

router = APIRouter()
router.include_router(system.router)
router.include_router(recipes.router)
