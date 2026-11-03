# Atlas v0.8 – Forschungsupdate, erste Ausbaustufe

Basis: bestehendes Repository, main `3ba5da608b8f41021523deced026f6a918d73381`.
Dieses Update implementiert die Vor-Holdout-Forschung. Es ist **keine vollständige Umsetzung aller vorgeschlagenen Release-Gates** und keine Handelsfreigabe.

## Was ergänzt wird

- `atlas_v08.py`: eigenständiger Forschungseinstieg auf Basis der bestehenden v0.6-Datenvalidatoren und SMA-/EMA-Signale. Kein neues Trading-Projekt.
- Coinbase BTC/EUR 1h-Download mit unveränderten JSON-Antworten und Request-Metadaten; 4h nur aus vier vollständigen Stunden derselben Quelle. Fehlende Stunden bleiben Lücken.
- Import der offiziellen Kraken-Datei für BTC/EUR, 240 Minuten, ohne Kopfzeile: Unix-Sekunden,Open,High,Low,Close,Volume,Trades. Die Wahl des richtigen Marktes ist vor Verwendung manuell zu prüfen; CSV-Hashes beweisen nicht die Herkunft.
- Quellenvergleich über den gesamten angeforderten Zeitraum: 99,5 % gemeinsame Kerzen, Median ≤0,25 %, p99 ≤1 %, Anteil >1,5 % ≤0,1 %, Return-Korrelation ≥0,995. Verfügbarkeit sowie O/H/L/C werden exportiert. Zeitstempel müssen exakt auf UTC-4h-Grenzen liegen. Korrelation wird niemals über eine Lücke berechnet.
- Globaler kalenderbasierter Holdout: letzte 20 % bleiben von allen Strategieauswertungen ausgeschlossen, auch bei Lücken. Vollständige Rohdaten und Qualitätsprüfung umfassen den Holdout, Strategieergebnisse nicht. Das beweist nicht, dass niemand diese historischen Kurse früher gesehen hat.
- Disjunkte 60-/90-/180-Tage-Fenster innerhalb zusammenhängender Forschungsabschnitte; 90 Tage primär. Fenster verschiedener Horizonte überlappen und sind keine unabhängigen Beobachtungen. Feste Parameter, kein Fit und keine Gewinnerauswahl.
- 10/20/50 % nur als Forschungsszenarien, mit passend allokiertem passivem Portfolio, 1x/2x/3x Kosten, SMA-/EMA-Nachbarn. EMA-Baseline wird direkt aus `generate_signals` bezogen, aktuell 20/50/200. SMA-Baseline bleibt 20/50.
- Stationary Bootstrap für gepaarte einfache Bar-Überrenditen, 10.000 Replikationen, mittlere Blocklängen 18/42/84; Holm-Korrektur über **alle ausgegebenen Bootstrap-Tests dieses Laufs**. Es ist weder SPA noch ein Schutz gegen Auswahl über frühere Forschungsläufe. CI betrifft den Mittelwert der Bar-Überrenditen, nicht kumuliertes Alpha. Bootstrap setzt schwache Stationarität voraus.
- Newey-West/Bartlett-Langfristvarianz mit 42 Lags für die diagnostische Sharpe-Kennzahl; nominale annualisierte Volatilität wird separat ausgegeben.
- Rohdaten-/Code-/Konfigurationshashes, UTC-Grenzen, Git-SHA, Python- und tatsächlich installierte Paketversionen. Ein bestehender Output-Ordner wird niemals überschrieben.
- Neuer Workflow testet den gesamten Bestand bei Pull Requests und Push auf `atlas-v0.8`; Forschung nur manuell. Leserechte, feste Action-SHAs, Ergebnis-Artefakte auch nach Fehlern.

## Was bewusst weiter offen ist

Der finale Holdout wird in dieser Ausbaustufe nicht geöffnet. `release_gate.json` bleibt immer `passed: false`, `paper_trading_authorized: false`. Noch ausstehend: separat freigegebener, registrierter finaler Holdout-Lauf; vollständige Release-Gates; SPA/Reality-Check; Regime-Schwellen 5/15 %; automatische Beschaffung/Zusammenführung sämtlicher Kraken-Quartalsarchive; Reparatur durch 15m-Candles; komplette Sensitivitäts-/Trade-Count-Zusammenfassungen. Es gibt keine erfundenen Holdout-Ergebnisse.

Die Gebühren von standardmäßig 0,6 % pro Fill und Slippage von 0,05 % sind **explizite Forschungsannahmen**, keine Zusage des persönlichen Börsentarifs. Vor finaler Registrierung Zielbörse und Gebührenstand bestätigen; `--fee-rate` ist frei einstellbar. Kraken nennt zum Prüfzeitpunkt 0,8 % Taker im ersten Spot-Tier. 2x/3x multiplizieren Gebühr und Slippage. Die Paper-Konfiguration bleibt unverändert.

Gleiche Startallokation ist kein Beweis gleichen Risikos: Buy & Hold driftet mit dem Kurs und hat andere Exposure. Es werden daher Exposure und Drawdowns zusätzlich berichtet. Cashzins ist null. Offene Trades werden zum hypothetischen Netto-Liquidationswert bewertet, aber nicht als abgeschlossene Trades gezählt. Profit Factor ohne Verluste ist `null` plus Kennzeichen, keine erfundene 99.

Das bestehende v0.7-Modell prüft Stops, Tagesverlust und Drawdown am nächsten 4h-Open. v0.8 übernimmt diese Modellierung aus der Forschung; keine garantierten Stoppreise und keine exakte Nachbildung real verspäteter GitHub-Läufe. Jede Testperiode startet mit 100 EUR neu. Charts zeigen getrennte Fenster und keine vorgetäuschte durchgehende Kontokurve.

## Ausführen

```bash
python -m pip install -r requirements-v08.txt
python -m pytest -q
python atlas_v08.py --days 1095 --end 2026-11-03T00:00:00Z \
  --kraken-csv /pfad/XBTEUR_240.csv --output atlas-research-output
```

Das Datum ist nur ein Beispiel. Ohne `--end` wird die letzte abgeschlossene 4h-Grenze einmalig eingefroren. Ohne vollständige Kraken-Datei erzeugt der Lauf einen BLOCKED-Bericht und Exitcode 2; er behauptet keine vollständige Datenvalidierung. Fehlende Historie in den Archiven bis zum gewählten Ende muss zunächst ergänzt werden. Mit `--coinbase-csv` ist ein archivierter normalisierter Datensatz möglich: timestamp in UTC-Millisekunden,open,high,low,close,volume. Beide Imports werden unverändert in `raw/` archiviert.

Neue Ergebnisse immer in einen neuen Output-Ordner schreiben. Kleinere `--bootstrap`-Werte ab 100 sind nur für technische Smoke-Tests vorgesehen. Für Forschung 10.000 beibehalten. Rohdaten können mehr als 730 Tage umfassen, obwohl Lücken die Anzahl nutzbarer Fenster stark reduzieren.

## Integration und iPad

Der GitHub-Schreibzugriff wurde am 03.11.2026 getestet: HTTP 403, `Resource not accessible by integration`. Es wurde deshalb noch kein Remote-Branch/PR für v0.8 erzeugt.

Für die verbundene GitHub-App muss der Repository-Zugriff auf `janneswiele/atlas-trading-ai` inklusive **Contents: write** und **Workflows: write** freigegeben sein. Auf dem iPad in GitHub unter Einstellungen → Applications → Installed GitHub Apps → verbundene App → Configure den Repository-Zugriff prüfen; gegebenenfalls eine angebotene Berechtigungsaktualisierung bestätigen. Eine Read-only-App lässt sich nicht durch Anmeldung in Safari zu einer Schreib-App machen. Keine Tokens oder Passwörter in den Chat senden.

Alternativ kann jemand mit Schreibzugriff den beigefügten Patch in einem Checkout anwenden:

```bash
git switch -c atlas-v0.8 origin/main
git apply --check Atlas_v08.patch
git apply Atlas_v08.patch
python -m pip install -r requirements-v08.txt
python -m pytest -q
git add atlas_v08.py test_atlas_v08.py requirements-v08.txt ATLAS_V08.md .github/workflows/atlas-v08.yml
git commit -m "Add sealed-holdout v0.8 research diagnostics"
git push -u origin atlas-v0.8
```

Danach Draft-PR erstellen; kein automatischer Merge. Bei zwischenzeitlichen Änderungen zuerst Patchprüfung durchführen. Es werden ausschließlich fünf neue Dateien ergänzt. Kein Kontostand, Trade-Datensatz, produktiver Workflow, Dashboard oder bestehender Python-Code wird überschrieben.

Nach einem später genehmigten Merge erscheint „Atlas v0.8 Research and Tests“ unter Actions → Run workflow. Manuelle Workflows müssen auf dem Standardbranch vorhanden sein; auf dem PR laufen zunächst die automatischen Tests. Ein grüner Testjob belegt Codefunktion, keinen Trading-Vorteil.

## Quellen für Schnittstellen und Einschränkungen

- Coinbase Candles: https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles
- Kraken Archive: https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data
- Kraken Gebühren: https://www.kraken.com/features/fee-schedule
- GitHub manueller Workflow: https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow

## Tatsächlich ausgeführte Prüfungen

- Python 3.12, Anforderungen aus `requirements-v08.txt` installiert; `pip check`: keine Konflikte.
- Bestand vor Erweiterung: 141 Tests bestanden.
- Gesamtsuite nach Erweiterung: **164 Tests bestanden**, darunter 23 neue v0.8-Tests; 8,75 Sekunden auf der Testumgebung.
- `compileall`: erfolgreich. Bestehende Streamlit-AppTest-Prüfungen inklusive Dashboard und Backtest-Pfad bestanden.
- Vollständiger synthetischer 730-Tage-Smoke-Test mit 100 Bootstrap-Replikationen: 390 Forschungszeilen und Charts erzeugt, `RESEARCH_COMPLETE_HOLDOUT_SEALED`, weiterhin keine Freigabe. Diese Zahlen beschreiben ausschließlich technische Testausgaben und keine Marktperformance.
- Git-Diff bestätigt: produktive Paper-Engine, Kontodaten, Risikokonfiguration, Dashboard, Signale und produktiver Zeitplan unverändert.
- Echter Coinbase-API-Zugriff in dieser Umgebung: HTTP 403. Ein realer 1095-Tage-Lauf und GitHub-Actions-Ausführung wurden deshalb **nicht erfolgreich getestet**. Es gibt keinen Nachweis eines Trading-Vorteils.


## iPad-ZIP: Installation auf atlas-v0.8 (04.11.2026)

Diese ZIP enthält genau fünf Ergänzungsdateien. Sie ist ein Update für das bestehende v0.7-Repository und nicht allein startfähig. Keine vorhandenen Dateien löschen. Insbesondere paper_state.json, Trade-Dateien, paper_config.json und .github/workflows/atlas-paper.yml unverändert lassen.

1. ZIP in der iPad-App Dateien speichern und einmal antippen: Sie wird entpackt.
2. In Safari https://github.com/janneswiele/atlas-trading-ai öffnen. Bei Bedarf „Desktop-Website anfordern“.
3. Branch-Auswahl „main“ öffnen, `atlas-v0.8` eingeben und den neuen Branch von main erstellen. Falls dieser Branch bereits existiert, auswählen und vor Upload auf vorhandene gleichnamige Dateien prüfen.
4. Auf `atlas-v0.8` über Add file → Upload files die vier Dateien atlas_v08.py, test_atlas_v08.py, requirements-v08.txt und ATLAS_V08.md auswählen. Direkt in die Repository-Wurzel hochladen, nicht in einen zusätzlichen Update-Ordner. Commit ausschließlich auf atlas-v0.8.
5. Die fünfte Datei gehört nach `.github/workflows/atlas-v08.yml`. Falls der versteckte Ordner auf dem iPad nicht auswählbar ist: Add file → Create new file, als vollständigen Namen `.github/workflows/atlas-v08.yml` eintragen. Den gesamten YAML-Block unten hineinkopieren (ohne die Markdown-Zeichen ```). Wieder auf atlas-v0.8 committen. Den bestehenden atlas-paper.yml NICHT öffnen oder ersetzen.
6. Pull requests → New pull request: base `main`, compare `atlas-v0.8`. Einen Draft-PR erstellen; keinen Merge ausführen. Falls schon ein passender v0.8-PR besteht, wird er durch die Commits automatisch aktualisiert.
7. Unter Actions bzw. Checks die Tests kontrollieren. Ein grüner Testlauf bedeutet keine Handelsfreigabe. Forschung ist weiterhin getrennt und manuell; der neue manuelle Workflow ist erst nach einer später freigegebenen Aufnahme auf den Standardbranch über Run workflow verfügbar.

Die ZIP selbst nicht einfach als Datei ins Repository hochladen: GitHub entpackt sie dort nicht automatisch. Maßgeblich sind die fünf entpackten Dateien an ihren Zielpfaden. Falls GitHub nur „Fork“ statt Commit auf deinen Branch anbietet, fehlt in dieser Browser-Sitzung der passende Kontozugriff.

### Kraken-Beschaffung: geprüft, noch nicht gelöst

Die offizielle Kraken-Seite nennt am Prüfdatum ein vollständiges Archiv bis 30.09.2026 in fünf Teilen von jeweils ungefähr 2 GB sowie eine SHA-256-Prüfliste. Quelle:
https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data

Schon der Download der kleinen offiziellen Prüfliste von assets.kraken.com scheitert hier mit HTTP 403. Daher wurde kein ungetesteter Großdownload in den Workflow aufgenommen und keine vollständige Historie in die ZIP gepackt. Die ZIP enthält Programmdateien, keine Marktdaten.

Für das Forschungsende nach September muss die Historie zusätzlich vollständig ergänzt werden, etwa aus überlappenden offiziellen REST-Daten, mit Prüfung auf widersprüchliche Duplikate und Lücken. Alternativ kann ein passendes früheres Forschungsende bewusst festgelegt werden. Ein Ende wird nicht heimlich verschoben, nur damit der Daten-Test besteht. Ohne Kraken-CSV bleibt der Forschungsjob BLOCKED. Der reine Testjob funktioniert ohne historische Downloads.

### Workflow zum Kopieren, falls .github unsichtbar ist

```yaml
name: Atlas v0.8 Research and Tests
on:
  pull_request:
  push:
    branches: [atlas-v0.8]
  workflow_dispatch:
    inputs:
      end:
        description: 'Closed 4h UTC end (blank freezes last closed boundary)'
        required: false
        type: string
      kraken_csv:
        description: 'Path to official BTC/EUR 240m CSV in checkout; empty yields blocked data report'
        required: false
        type: string
permissions:
  contents: read
concurrency:
  group: atlas-v08-${{ github.ref }}
  cancel-in-progress: false
jobs:
  research:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: '3.12'
          cache: pip
          cache-dependency-path: requirements-v08.txt
      - name: Install dependencies
        run: python -m pip install -r requirements-v08.txt
      - name: Syntax and complete regression suite
        run: |
          python -m compileall -q .
          python -m pytest -q
      - name: Run research (manual only; never trade)
        if: github.event_name == 'workflow_dispatch'
        env:
          RESEARCH_END: ${{ inputs.end }}
          KRAKEN_CSV: ${{ inputs.kraken_csv }}
        shell: bash
        run: |
          args=(--days 1095 --output atlas-research-output)
          if [[ -n "$RESEARCH_END" ]]; then args+=(--end "$RESEARCH_END"); fi
          if [[ -n "$KRAKEN_CSV" ]]; then args+=(--kraken-csv "$KRAKEN_CSV"); fi
          python atlas_v08.py "${args[@]}"
      - name: Preserve diagnostic bundle even on failure
        if: always() && github.event_name == 'workflow_dispatch'
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: atlas-v08-research
          path: atlas-research-output/
          if-no-files-found: warn
          retention-days: 14
```
