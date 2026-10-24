# Entwicklung

Alles, was man braucht, um Tellerplan lokal zu bauen, zu prüfen und zu veröffentlichen. Hintergrund steht in [[Architektur]].

## Einrichten

```bash
cd tellerplan/app
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
```

Lokale Konfiguration anlegen (der Ordner `dev/` ist nicht im Git):

```bash
cp dev/options.example.json dev/options.json
```

Ein relativer `database_path` gilt relativ zur `options.json`, also landet die Datenbank in `dev/app.db`.

## Starten

```bash
# in tellerplan/app
export TELLERPLAN_OPTIONS=../../dev/options.json   # PowerShell: $env:TELLERPLAN_OPTIONS="../../dev/options.json"
alembic upgrade head
uvicorn main:create_app --factory --reload --host 0.0.0.0 --port 8000
```

Danach `http://localhost:8000` öffnen, am iPhone über die PC-IP im WLAN.

Wie im Add-on, mit Backup, Migration und beiden Ports: `python -m serve`.

## Ports und Zugriff

| Port | Zweck | Zugriff |
| --- | --- | --- |
| 8000 | Ingress (Seiten und API für die Oberfläche) | ohne Login, nur über Home Assistant erreichbar |
| 8099 | JSON-API für Kurzbefehle und Skripte | nur `/api/…`, nur mit `Authorization: Bearer <api_token>` |

Beide Ports bedient dieselbe App in einem Prozess (`serve.py`); die Regeln stehen in `security.py`.

## Prüfen

```bash
ruff check . && ruff format --check .
pytest
```

CI führt beides bei jedem Push und Pull Request aus (`.github/workflows/ci.yml`).

## Datenbank und Migrationen

- Modelle erben von `db.Base` und liegen im jeweiligen Modul unter `modules/`.
- Jede Schemaänderung ist eine Alembic-Migration:

  ```bash
  alembic revision --autogenerate -m "<beschreibung>"
  ```

- Beim Add-on-Start legt `serve.py` zuerst `app.db.bak` an und migriert dann auf den neuesten Stand.

## Release

1. `version` in `tellerplan/config.yaml` erhöhen.
2. Committen, Tag `vX.Y.Z` setzen und pushen.
3. `.github/workflows/release.yml` prüft Tag gegen Version und baut `ghcr.io/spurzylinder/tellerplan-aarch64:X.Y.Z`.
4. Home Assistant zeigt das Update an.

Beim ersten Release muss das Paket in GitHub unter *Packages* auf **public** gestellt werden, damit Home Assistant es ohne Login laden kann.

## Add-on in Home Assistant einbinden

*Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories* und `https://github.com/SpurZylinder/tellerplan-ha` hinzufügen.
