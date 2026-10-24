# Tellerplan – Dokumentation

Einstieg in die Projektdoku. Dieser Ordner ist der sichtbare Teil des Obsidian-Vaults.

## Notizen

- [[Architektur]] – Ziele, Module, Datenmodell, Abläufe, Ausbaustufen
- [[Entwicklung]] – lokal einrichten, starten, prüfen, migrieren, veröffentlichen
- [[Obsidian]] – wie dieser Vault eingerichtet ist

## Stand

Aktuelle Ausbaustufe: **1 – Kern**

- [x] Repo-Gerüst, Home-Assistant-Add-on-Struktur
- [x] FastAPI-App mit zentralen Einstellungen (`settings.py`)
- [x] SQLite + Alembic mit automatischer Migration beim Start
- [x] CI (Ruff + pytest) und Release (arm64-Image nach GHCR)
- [ ] BLS-Import
- [ ] Lebensmittelsuche
- [ ] Tagebuch mit vier Mahlzeiten, Tageslimit und Balken
