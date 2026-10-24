# Sichtbarkeit von Repo und Image

Datum: 2026-10-24

## Kontext

Home Assistant holt ein Add-on in zwei Schritten:

1. **Add-on-Repository:** Home Assistant klont das Git-Repo anonym, um `repository.yaml` und `tellerplan/config.yaml` zu lesen. Ein privates Repo zeigt im Store einfach nichts an, ohne brauchbare Fehlermeldung.
2. **Image:** Home Assistant lädt das fertige Image `ghcr.io/spurzylinder/tellerplan-aarch64` von GHCR. Ohne Zugangsdaten muss das Paket öffentlich sein.

Ein öffentliches Image enthält den kompletten Python-Code im Klartext. Code-Repo privat und Image öffentlich schützt den Code also nicht.

**Was „öffentlich“ bedeutet:** Jeder kann lesen, klonen, forken, Issues und Pull Requests eröffnen und das Image herunterladen. Pushen, mergen und Images veröffentlichen kann nur, wer Schreibrechte hat, derzeit nur der Account `SpurZylinder`. Pull Requests aus Forks laufen in GitHub Actions mit Lesezugriff und ohne Secrets.

## Entscheidung

Repo und Image bleiben **öffentlich** (Variante A). Im Code steckt nichts Geheimes; persönliche Daten, Tokens und die Datenbank liegen nur auf dem Pi und nie im Repo.

Wird später geschlossener Zugriff nötig, entsteht dafür ein **neues, privates Repo** nach Variante B oder C. Das bestehende öffentliche Repo bleibt dann als Altstand stehen oder wird archiviert, denn seine Git-Historie ist bereits öffentlich und lässt sich nicht zurückholen.

### Varianten

| Variante | Code privat? | Aufwand | Updates |
| --- | --- | --- | --- |
| **A. Alles öffentlich** (gewählt) | nein | keiner | Tag `vX.Y.Z` pushen, Home Assistant zeigt das Update |
| **B. Getrennt** | ja | mittel | Tag im privaten Repo pushen, Version im öffentlichen Repo nachziehen |
| **C. Lokales Add-on** | ja | gering, aber manuell | Ordner neu kopieren, Version erhöhen, in Home Assistant neu bauen |

**B. Getrennt**

- Privates Repo mit dem Code; der Release-Workflow baut das Image und legt es als **privates** Paket auf GHCR ab.
- Kleines öffentliches Repo nur mit `repository.yaml`, `tellerplan/config.yaml`, `DOCS.md` und Icon; `image:` zeigt auf das private Paket.
- In Home Assistant unter *Add-on-Store → ⋮ → Registries* `ghcr.io` mit GitHub-Nutzer und einem Token mit `read:packages` hinterlegen (noch nicht ausprobiert).
- Nachteil: zwei Repos, Version an zwei Stellen, Token in Home Assistant pflegen.

**C. Lokales Add-on**

- Repo privat; kein GHCR und kein Release-Workflow nötig.
- Den Ordner `tellerplan/` per Samba oder SSH nach `/addons/tellerplan` auf den Pi kopieren und in `config.yaml` die Zeile `image:` entfernen, damit Home Assistant das Image aus dem `Dockerfile` selbst baut.
- In Home Assistant *Add-on-Store → ⋮ → Nach Updates suchen*; das Add-on erscheint unter „Lokale Add-ons“.
- Update: Ordner neu kopieren, `version` erhöhen, in Home Assistant „Neu bauen“ (dauert auf dem Pi einige Minuten).

## Folgen

- Niemals Tokens, `options.json`, Datenbanken oder Exporte committen (siehe CLAUDE.md, Abschnitt Sicherheit). Die Git-Historie ist öffentlich.
- `dev/options.example.json` enthält nur den Platzhalter-Token `lokal-geheim`; im Add-on immer einen eigenen, langen Token setzen.
- Nach dem ersten Release das GHCR-Paket `tellerplan-aarch64` auf **public** stellen.
- Optional: Branch-Regel für `main` (kein Force-Push, kein Löschen) und bei Bedarf *Interaction limits* für Fremde.
