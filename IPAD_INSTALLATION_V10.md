# Atlas v1.0 installieren – nur mit iPad

## Bevor du etwas hochlädst

- `main` NICHT verändern.
- `atlas-v0.9-data`, `ledger.json`, `paper_state.json`, `paper.py` NICHT löschen, hochladen oder umbenennen.
- `STAGED_ONLY/.github/workflows/atlas-v10-forward-scheduler.yml` ist **NICHT** zur sofortigen Installation auf `main` freigegeben.
- In diesem Paket ist keine echte Konto-/Trading-API enthalten. Alles bleibt virtuell.

## Schritt 1: Branch erstellen

1. Öffne https://github.com/janneswiele/atlas-trading-ai/branches in Safari.
2. Verwende als Basis **`atlas-v0.9`**, NICHT `main`.
3. Erstelle den Branch **`atlas-v1.0-development`**.
4. Kontrolliere, dass GitHub diesen Branch oben ausgewählt anzeigt.

Falls du dem Work-Modus GitHub-Schreibrechte gibst, kann er die folgenden Dateien im Entwicklungsbranch statt per Safari hochladen. Bei der aktuellen Verbindung wurde jedoch 403 gemeldet.

## Schritt 2: Nur das Update-Paket hochladen

1. Lade `Atlas_Trading_AI_v1.0_UPDATE_UPLOAD_ONLY.zip` und öffne die iPad-App **Dateien**.
2. Tippe die ZIP an – iPadOS entpackt sie.
3. Öffne den enthaltenen Ordner `UPLOAD_ONLY`.
4. Lade folgende Inhalte auf **`atlas-v1.0-development`** hoch, mit exakt erhaltenen Pfaden:

   - Root: `atlas_v10.py`, `test_atlas_v10.py`, `ATLAS_V10_AUDIT.md`, `CHANGELOG_V10.md`, `IPAD_INSTALLATION_V10.md`, `requirements-v10.txt`.
   - Ordner `atlas10`: **alle** neuen Python-Dateien einschließlich `__init__.py` und `README.md`.
   - Ordner `examples/atlas10`: synthetischer Datensatz und zugehöriges Manifest.
   - Ordner `.github/workflows`: `atlas-v10-research.yml`.
   - Ordner `STAGED_ONLY/.github/workflows`: die noch nicht aktive Scheduler-Vorlage.

   Link zum Root-Upload: https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v1.0-development

   Ordner-Uploads über GitHub gehen per Safari manchmal nur Datei für Datei. In diesem Fall GitHub-Pfad öffnen, **Add file → Upload files** und im betreffenden Ordner Dateien auswählen. Nach jedem Upload **Commit changes** drücken. Nicht die ZIP-Datei selbst hochladen.

## Schritt 3: Prüfen

1. Öffne GitHub → Actions und suche `Atlas v1.0 isolated research quality checks`.
2. Der Workflow soll die alte und neue Testsuite ausführen und anschließend die synthetische Forschungsprobe.
3. Bei Fehlern die tatsächlichen Logs lesen, NICHT an Risikogrenzen oder am v0.9-Ledger drehen.
4. Die neuen Dateien sollten den Branch `atlas-v1.0-development` enthalten; noch KEIN Merge auf `main`.

## Schritt 4: Demokonto automatisch starten (SEPARATE FREIGABE)

Erst nach erfolgreicher CI und ausdrücklicher Zustimmung wird **eine** zusätzliche Datei aus `STAGED_ONLY/` unter `.github/workflows/atlas-v10-forward-scheduler.yml` auf `main` abgelegt.

Sie startet den **bereits aktivierten** v0.9-Forschungssimulator bei geeigneten vierstündigen Kerzenschlüssen und schreibt nur in `atlas-v0.9-data`. Sie startet keine Aktivierung neu und erzeugt keine Echtgeld-Orders. GitHub Actions kann geplante Läufe auslassen oder verzögern; bei verspäteten Kursen gilt `SAFE_SKIP` statt rückwirkendem Handel.

## Optional: Dashboard

Die Datei `atlas10/dashboard.py` ist eine Streamlit-App. Sie kann später bei einem unterstützten Streamlit-Host bereitgestellt werden. Dazu sind Hosting-Einrichtung und eventuell weitere Zustimmungen notwendig; sie ist **nicht bereits öffentlich gehostet**.

Ein lokales HTML-Dashboard kann man mit einem Python-Lauf erstellen:

`python atlas_v10.py snapshot --ledger ledger.json --out Dashboard.html`

Der erforderliche Ledger ist auf dem getrennten Forschungsdatenbranch, nicht im Update-Paket. Diese HTML-Datei ist eine Momentaufnahme und aktualisiert sich nicht automatisch.

## Forschungsbeispiel

`python atlas_v10.py research --csv examples/atlas10/SYNTHETIC_4h.csv --approval examples/atlas10/SYNTHETIC_4h.approval.json --out atlas-v10-results`

Die Daten sind **synthetisch**, deshalb sind alle Erträge oder Verluste daraus ein technischer Test und kein Handelsnachweis.
