"""Start im Add-on: Datenbank sichern, migrieren, Ingress- und API-Server starten."""

import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from db import backup_database
from main import create_app
from migrate import upgrade_to_head
from settings import Settings, get_settings

logger = logging.getLogger("tellerplan")


async def serve_ports(app: FastAPI, settings: Settings) -> None:
    """Betreibt dieselbe App auf Ingress- und API-Port in einem Prozess."""
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port))
        for port in (settings.ingress_port, settings.api_port)
    ]
    await asyncio.gather(*(server.serve() for server in servers))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    backup = backup_database(settings.database_path)
    if backup is not None:
        logger.info("Datenbank gesichert nach %s", backup)
    upgrade_to_head(settings)
    asyncio.run(serve_ports(create_app(settings), settings))


if __name__ == "__main__":
    main()
