# Atlas Trading AI v0.8.3 – Wie gelangen wir wirklich zu Phase 3?

**Forschungsaudit, nicht Handelsstrategie.** Dieses Update ergänzt vier neue Dateien und verändert weder `main` noch den vorhandenen Trading-Code oder gespeicherte Paper-Trades.

## Was wir konkret gefunden haben

Aus dem **echten** erfolgreichen, Coinbase/Kraken-geprüften Forschungsdurchlauf mit Enddatum **2026-10-01T00:00:00Z**, beschränkt auf die 7 primären nicht überlappenden 90-Tage-Fenster **vor** dem finalen Holdout, stammt folgende Attribution:

| Kennzahl | SMA 20/50 | EMA Trend |
|---|---:|---:|
| Einstiege | 41 | 20 |
| Geschlossene Trades | 41 | 19 |
| Stop-Loss-Ausstiege | 15 | 10 |
| Take-Profit-Ausstiege | 22 | 9 |
| Strategie-Signal-Ausstiege | 4 | 0 |
| Risiko-blockierte Einstiege | 0 | 0 |
| In Position (Anteil der 4h-Zeitabschnitte) | 16,51 % | 12,67 % |
| Tatsächliche mittlere Portfolio-Exposure | 3,31 % | 2,54 % |
| Durchschnittliche Haltedauer abgeschlossener Positionen | 2,54 Tage | 3,96 Tage |

*Die Mittelwerte beziehen sich auf getrennte 90-Tage-Testfenster mit jeweils neu gestarteten 100-Euro-Forschungskonten. Die Beobachtungen sind keine unabhängigen neuen Out-of-sample-Daten und kein Leistungsversprechen.*

**Interpretation:** Die geringe Marktteilnahme entsteht überwiegend durch seltene Signale und kurze Haltezeiten. Fast alle EMA-Ausstiege und die meisten SMA-Ausstiege erfolgen durch die bereits festgelegten Stop-Loss- oder Take-Profit-Regeln an der nächsten 4h-Eröffnung. **Das beweist nicht**, dass andere Stopps oder häufigere Signale mehr Rendite bringen. Exakt diese Unsicherheit sollen die nächsten Experimente adressieren.

## Was das Update sicherstellt

`atlas_v083.py` verwendet nur den **bereits freigegebenen Research-Teil vor dem Holdout**. Es liest und validiert den v0.8.1-Datenqualitätsbericht, die Hashes und Research-Candles, simuliert die Originalstrategien mit unveränderten Risikoregeln und rekonstruiert jeden Einstieg/Ausstieg **unabhängig**. Stimmen Zeitpunkte, Trade-PnL oder jede einzelne Kontokurve nicht mit dem Original überein, stoppt es. Es dokumentiert den wesentlichen Modellvorbehalt: Stops und Take-Profits werden ausschließlich anhand der **nächsten 4h-Eröffnung**, nicht zu garantiert ausführbaren Intrabar-Preisen ausgelöst.

Die Ausgabe umfasst `entry_exit_windows.csv`, `attributed_trades.csv`, `position_decision_bars.csv`, `diagnostics.json`, `SUMMARY_V083_DE.md`, `exit_reasons.png` und Datei-Hashes. Sie wird in einem **neuen** Ordner geschrieben; bestehende Resultate werden nicht überschrieben.

Unverändert bleiben insbesondere `paper.py`, `paper_state.json`, `paper_config.json`, `strategies.py`, `atlas_v08.py`, `atlas_v082.py`, Release-Gates und der finale Holdout. **Keine Echtgeld-Orders, keine automatische Freigabe, kein Parameter-Tuning.**

## Phase 3 – schnell, aber korrekt

1. **Diagnose (dieses Update):** Seltene Signale versus frühe Exits klar zuordnen. Keine rückblickende Gewinnerauswahl.
2. **Vorab registriertes Experiment:** Genau eine fachlich begründete Änderung, realistische Kosten und feste Erfolgskriterien definieren. Die aktuelle Strategie ist die unveränderte Kontrollgruppe.
3. **Neue Forward-Paper-Daten sammeln:** Auf frischen, noch nicht analysierten Marktperioden ausschließlich virtuell vergleichen. Den bereits wiederholt gesehenen historischen Holdout nicht ungeplant öffnen.
4. **Bestehende harte Gates prüfen:** Geschlossene Tradezahlen, Netto-Performance, Profit Factor, Drawdown, risikobereinigte Benchmark, Kostenstress und Robustheit. Keine automatische Freigabe.
5. **Erst bei extern replizierten Ergebnissen Phase 4:** kontrollierte autonome Paper-Strategieauswahl, regelmäßige Qualitätsprüfungen und Absturz-/Datenschutzmechanismen.

Es gibt keinen seriösen Weg, einen stabilen Handelsvorteil oder genügend neue Marktdaten zeitlich zu erzwingen.

## iPad-Installation nur auf `atlas-v0.8`

1. ZIP auf dem iPad in der App **Dateien** entpacken.
2. Die Dateien `atlas_v083.py`, `test_atlas_v083.py`, `ATLAS_V083.md` im **Hauptordner** des Branches `atlas-v0.8` hochladen: https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8
3. Die Datei `.github/workflows/atlas-v083.yml` in den GitHub-Ordner `.github/workflows/` hochladen: https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8/.github/workflows
4. Für beide Uploads `Commit changes` auf `atlas-v0.8`. **Nicht** auf `main` mergen.
5. Unter https://github.com/janneswiele/atlas-trading-ai/actions/workflows/atlas-v083.yml den automatisch gestarteten Workflow prüfen. Erst dessen erfolgreiches Abschlussprotokoll und Artefakt gelten als GitHub-Reproduktion.

Die GitHub-Version lädt Kraken-Archive erneut, wiederholt den ursprünglichen fixen Coinbase-Research-Lauf und führt anschließend ausschließlich die diagnostische v0.8.3-Replayprüfung aus. Wenn Daten fehlen, schlägt der Workflow fehl, statt Resultate zu erfinden.

## Lokale Befehle (nur als Referenz)

```bash
python -m pip install -r requirements-v08.txt
python -m pytest -q
python atlas_v083.py --input atlas-v08-research --output atlas-v083-diagnostics
```

`--input` muss der vollständige, unveränderte v0.8.1-Research-Ordner mit Manifest, Kurshistorie und Hashes sein. Der Output-Ordner darf noch nicht existieren.

**Prüfstatus vor GitHub-Upload:** 19 neue Tests bestanden, 199 lokal ausführbare Tests bestanden (2 Dashboard-Tests wegen `streamlit`/`ccxt` nicht ausgeführt, 2 Testmodule wegen `ccxt` nicht sammelbar); echte Archivdaten lokal ausgewertet. Die vollständige GitHub-Testsuite steht noch aus.
