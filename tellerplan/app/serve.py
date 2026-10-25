"""Start im Add-on: Datenbank sichern, migrieren, Ingress- und API-Server starten."""

import asyncio
import logging

import uvicorn
from fastapi import FastAPI

import clock
from db import backup_database
from main import create_app
from migrate import has_pending_migrations, upgrade_to_head
from settings import Settings, get_settings

logger = logging.getLogger("tellerplan")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


async def serve_ports(app: FastAPI, settings: Settings) -> None:
    """Betreibt dieselbe App auf Ingress- und API-Port in einem Prozess."""
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port))
        for port in (settings.ingress_port, settings.api_port)
    ]
    await asyncio.gather(*(server.serve() for server in servers))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    settings = get_settings()
    zone = clock.local_zone()
    logger.info("Zeitzone %s, heute ist %s", zone or "des Systems", clock.today().isoformat())
    if has_pending_migrations(settings):
        backup = backup_database(settings.database_path)
        logger.info("Migration steht an, Datenbank gesichert nach %s", backup)
    upgrade_to_head(settings)
    asyncio.run(serve_ports(create_app(settings), settings))


if __name__ == "__main__":
    main()
