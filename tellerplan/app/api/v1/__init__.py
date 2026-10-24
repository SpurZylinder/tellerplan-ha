"""JSON-API v1 für UI, Kurzbefehle und Skripte."""

from fastapi import APIRouter

from api.v1 import system

router = APIRouter()
router.include_router(system.router)
