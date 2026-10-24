# Tellerplan – Dokumentation

Einstieg in die Projektdoku. Dieser Ordner ist der sichtbare Teil des Obsidian-Vaults.

## Notizen

- [[Architektur]] – Ziele, Module, Datenmodell, Abläufe, Ausbaustufen
- [[Entwicklung]] – lokal einrichten, starten, prüfen, migrieren, veröffentlichen
- [[Obsidian]] – wie dieser Vault eingerichtet ist

## Stand

Stufe 1 ist fertig, Stufe 2 steht in einer Grundversion. Als Nächstes: Feinschliff nach dem iPhone-Test, danach Stufe 3. Reihenfolge siehe [[Architektur#Ausbaustufen und offene Punkte]].

- [x] Repo-Gerüst, Home-Assistant-Add-on-Struktur
- [x] FastAPI-App mit zentralen Einstellungen (`settings.py`)
- [x] SQLite + Alembic mit automatischer Migration beim Start
- [x] CI (Ruff + pytest) und Release (arm64-Image nach GHCR)
- [x] UI-Rahmen mit Tab-Leiste (Heute · Rezepte · Plan · Lebensmittel)
- [x] Lebensmittel anlegen, suchen, Einheiten pflegen; Demo-Set
- [x] Nährwertrechnung (`modules/nutrition`)
- [x] Rezepte: Liste im Ranking-Look, Detail, Anlegen, Zutaten aus den Lebensmitteln
- [x] Wochenplan: 1 oder 2 Wochen, Portionen je Eintrag, Tagesvorschau
- [ ] Tagebuch mit vier Mahlzeiten, Tageslimit und Balken (Stufe 3)
- [ ] Importe: BLS, Freitext, Cookidoo (Stufe 4)
