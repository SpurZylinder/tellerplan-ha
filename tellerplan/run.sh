#!/bin/sh
# Startet Tellerplan im Add-on: Datenbank sichern, migrieren, Server starten.
set -e
cd /app
exec python -m serve
