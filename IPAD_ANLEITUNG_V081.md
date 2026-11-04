# Atlas Trading AI v0.8.1 – Kraken-Archivabruf für iPad

**Status:** Installierbares, read-only Forschungs-Add-on; **kein** nachgewiesener Trading-Vorteil, **keine** Handelsfreigabe. Der Zugriff auf die großen echten Kraken-Archive wurde **nicht** in GitHub Actions verifiziert. Die bestehende Atlas-v0.8-Forschung bleibt unverändert.

## Was diese ZIP enthält

1. `atlas_v08_kraken_fetch.py` – holt aus den offiziellen Kraken-OHLCVT-Archiven gezielt `XBTEUR_240.csv` per HTTP-Byte-Range. Die fünf großen Archivteile müssen dafür weder auf das iPad noch vollständig auf den GitHub-Runner geladen werden. Falls der Server keine präzisen Byte-Ranges unterstützt, wird der Lauf klar als BLOCKED abgebrochen (kein unsicherer Download).
2. `test_atlas_v08_kraken_fetch.py` – zwölf synthetische Tests für Mehrteil-ZIPs, fehlende Zeitbereiche, Lücken, widersprüchliche Daten, falsche Börsenmärkte und Fehler beim HTTP-Byte-Range-Zugriff.
3. `.github/workflows/atlas-v08-kraken.yml` – separate GitHub-Actions-Forschung auf dem Branch `atlas-v0.8`: Tests, Kraken-Abruf, Coinbase/Kraken-Kreuzvergleich, Atlas-v0.8-Forschung. Diagnosen werden auch nach einem Fehler gespeichert.
4. `IPAD_ANLEITUNG_V081.md` – diese Anleitung.

**Nichts überschreiben:** Die ZIP enthält weder `paper.py` noch `paper_state.json`, `paper_config.json`, die bestehenden Paper-Workflows, `atlas_v08.py` oder `atlas-v08.yml`. Auf `main` nichts verändern.

## Auf dem iPad installieren

1. ZIP-Datei herunterladen und in der iPad-App **Dateien** einmal antippen, damit ein entpackter Ordner entsteht.
2. Öffne **https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8** in Safari. Kontrolliere: Branch **atlas-v0.8**, NICHT `main`.
3. Lade im Stammverzeichnis nur die Dateien `atlas_v08_kraken_fetch.py`, `test_atlas_v08_kraken_fetch.py` und `IPAD_ANLEITUNG_V081.md` hoch. Unten **Commit changes** drücken.
4. Öffne dann **https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8/.github/workflows**. Lade dort **nur** `atlas-v08-kraken.yml` hoch und bestätige den Commit. Der Dateipfad auf GitHub muss danach exakt `.github/workflows/atlas-v08-kraken.yml` sein.
5. GitHub Actions sollte auf dem Entwicklungsbranch nach der zweiten Änderung den Workflow **Atlas v0.8 Official Kraken Archive Check** automatisch starten. Link: **https://github.com/janneswiele/atlas-trading-ai/actions**. Der Workflow startet Tests und versucht **echte** Daten herunterzuladen. Es ist noch **unbekannt**, ob die Kraken-Server präzise HTTP-Byte-Ranges für GitHub Actions erlauben.
6. Wenn grün: den Workflowbericht und das Artefakt `atlas-v08-official-data-diagnostics` prüfen (Grün heißt nicht profitabel). Wenn rot: Run öffnen, Fehlerschritt suchen, dieses Log/Artefakt im Chat zeigen. Einen BLOCKED-Lauf niemals als erfolgreiche unabhängige Marktvalidierung ansehen.

**Wichtig:** Der neue Workflow läuft beim erstmaligen Push von `atlas-v0.8`. Er ist **nicht** für Echt-Trading vorgesehen. GitHub kann die dauerhafte Nutzung von `workflow_dispatch` eines ausschließlich auf dem Entwicklungsbranch vorhandenen Workflows einschränken; daher gibt es den zusätzlichen Push-Trigger.

## Präziser Datenbereich und Grenzen

Die offiziellen Kraken-Archive enthalten die vollständige Historie bis **2026-06-30** sowie einen separaten Q3-2026-Zusatz. Das Skript fordert **2023-10-02 00:00 UTC bis 2026-10-01 00:00 UTC (Ende exklusiv)** an, also 1.095 Tage. Es macht den Zeitraum nicht heimlich kürzer. Der Binance-Zugriff, API-Schlüssel, echte Trades oder Echtgeld sind nicht erforderlich.

Fehlende Kerzen werden nicht erfunden. Bei unvollständiger Abdeckung oder fehlgeschlagenem Coinbase/Kraken-Vergleich wird der Forschungsprozess blockiert. Der finale Holdout bleibt unberührt. `release_gate.json` bleibt ohne Handelsfreigabe. Selbst bei einem grünen Lauf werden keine Strategien freigeschaltet.

Eine Überprüfung der vollständigen offiziellen SHA-256-Hashes aller fünf großen Archivteile ist bei selektivem Byte-Range-Zugriff nicht möglich. Stattdessen werden ZIP-CRC des einzelnen Marktmitglieds, dessen SHA-256, echte URLs, gemeldete Größen und Quell-Metadaten dokumentiert. Die Herkunft der Antworten wird über HTTPS transportgesichert; dies ist **keine** vollständige Signaturprüfung des mehrteiligen Archivs.

## Verifizierte Tests hier

- Remote-ZIP-Modul: **12/12 isolierte Tests erfolgreich**.
- Lokale Regression ohne `ccxt`- und `streamlit`-Testabhängigkeiten: **161 Tests bestanden, 2 abgewählt**; die `ccxt`-Importtests waren hier nicht ausführbar. Die unabhängige vollständige v0.8-Basissuite bestand zuvor in GitHub Actions **164/164**.
- **Kein** echter Kraken-Großarchivabruf in dieser Umgebung: der direkte Zugriff wurde durch die Netzwerkumgebung verhindert. Dies wird erst durch den GitHub-Actions-Lauf überprüft.

Quellen: Kraken OHLCVT-Archiv https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data ; GitHub Actions https://docs.github.com/en/actions
