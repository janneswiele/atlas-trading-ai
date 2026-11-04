# Atlas Trading AI v0.8.2 – Ex-ante-Benchmark und Exposure-Prüfung

**Status: Zusatzdiagnostik auf Basis von v0.8.1, ausdrücklich keine Handelsfreigabe.**

## Ausgangspunkt

- Repository: `janneswiele/atlas-trading-ai`, Branch `atlas-v0.8`.
- Bereits vorhandener erfolgreicher realer v0.8.1-Lauf: https://github.com/janneswiele/atlas-trading-ai/actions/runs/41743408733.
- Archivierter Ergebnisstand: 1.095 Tage, Ende **2026-10-01T00:00:00Z**, Coinbase-Kraken-Qualitätsprüfung bestanden, 14 primäre 90-Tage-Strategiefenster (7 je Strategie).
- Versiegelter Holdout beginnt am **2026-02-24T00:00:00Z**. Das historische Datum darf **nicht** für Strategievalidierung oder Kalibrierung verwendet werden.
- Status weiterhin `paper_trading_authorized: false`, `passed: false`.

## Neue Funktionen

`atlas_v082.py` liest ausschließlich bereits vorhandene v0.8.1-Forschungsergebnisse und erstellt eine **zusätzliche** Diagnostik. Es ändert **keine** bestehenden Skripte, Einstellungen, Ergebnisse oder Paper-Trading-Daten.

1. Es prüft die Manifest-Hashes aller benötigten Originaldateien, die Datenqualitätsprüfung und den weiterhin versiegelten Holdout.
2. Es überprüft jede 90-Tage-Strategiekurve gegen Original-Coinbase-Kerzen und rekonstruiert den vorhandenen 20%-Buy-and-Hold-Benchmark mit derselben Kostenannahme. Stimmen die Kurven nicht überein, wird abgebrochen.
3. Es simuliert die **vor dem Validierungsfenster liegende** 341-Bar-Kalibrierungsperiode für dieselbe Strategie, mit 200 vorherigen Bars als Indikator-Warmup. Die vorab bestimmte passive Vergleichsallokation ist `min(20%, vergangene Strategievolatilität / vergangene BTC-Volatilität)`. Dieser Anteil bleibt für das gesamte folgende 90-Tage-Fenster konstant. **Kein Blick auf zukünftige Kurse zur Festlegung der Allokation.**
4. Perioden mit weniger als drei **vorherigen** abgeschlossenen Trades oder mit null Signalvolatilität sind als `LOW_TRADE_COUNT_OR_ZERO_SIGNAL_VOLATILITY` markiert und dürfen nicht als belastbare Risiko-Kalibrierung interpretiert werden. Das ist ein **Diagnostik-Mindestwert**, keine Lockerung/Änderung der bestehenden Strategie-Zulassungsregeln.
5. Getrennt ausgewiesen: tatsächliche mittlere/gelegentliche Exposure, realisierte Volatilität, der bisherige 20%-Benchmark, der vorab kalibrierte Benchmark, ein **ausdrücklich ex post** exposure-abgeglichener Referenzwert sowie Abweichung der realisierten Volatilität.
6. CSV, Maschinenbericht, verständliche deutsche Zusammenfassung und zwei Benchmark-Grafiken – jeweils für getrennte 90-Tage-Fenster und ohne vorgetäuschte fortlaufende Kontokurve.

**Methodische Grenzen:** Das ist keine exakte Risikogleichheit, keine statistische Zulassung, kein SPA/Reality Check, keine externe OOS-Validierung und kein Beweis einer profitablen Handelsstrategie. Die Kalibrierung kann bei schwacher Trading-Aktivität fehlschlagen. Recherchen in wiederholt untersuchten historischen Zeiträumen bleiben gegen Overfitting anfällig. Positive Kontroll-Abstände sind deshalb *nur deskriptiv*. Der ursprüngliche Bootstrap und sämtliche offiziellen Freigabe-Gates bleiben unverändert.

## Echte Ergebnisse aus dem ursprünglichen v0.8.1-GitHub-Artefakt (lokal reproduziert)

Die Zahlen stammen aus der realen Coinbase/Kraken-Datenforschung, **nicht** aus den synthetischen Tests.

| Primäre 90-Tage-Fenster | SMA 20/50 | EMA Trend |
|---|---:|---:|
| Verfügbare historische Fenster | 7 | 7 |
| Davon gültige Vorfenster-Kalibrierungen (≥3 abgeschlossene Trades) | 6 | 2 |
| Mittlere tatsächlich gemessene Exposure | 3,31 % | 2,54 % |
| Mittlere Strategierendite je Fenster | +0,22 % | −0,26 % |
| Mittlere Rendite der bisherigen 20%-Passivbenchmark | +3,38 % | +3,38 % |
| Fenster, in denen die Strategie vorab kalibrierten Benchmark schlägt (nur ausreichend kalibrierte Fenster) | 0/6 | 1/2 |
| Median Verhältnis realisierter Volatilität Strategie / vorab kalibrierte Passivbenchmark (gültige Fenster) | 0,95 | 0,20 |

**Befund:** Kein neuer Nachweis für Alpha. Der neue Benchmark wird zwar vor Testbeginn auf historische Volatilität kalibriert, seine **realisierte** Volatilität kann aber besonders bei EMA erheblich abweichen. Weitere Daten, bessere Vorfenster-Schätzungen und eine separat vorregistrierte Prüfung wären nötig.

## GitHub: Installation nur auf Branch `atlas-v0.8`

1. ZIP auf dem iPad herunterladen und mit der App **Dateien** durch Antippen entpacken.
2. Im GitHub-Branch `atlas-v0.8` über `Add file → Upload files` im **Hauptordner** hochladen:
   - `atlas_v082.py`
   - `test_atlas_v082.py`
   - `ATLAS_V082.md`
3. Danach über `Add file → Upload files` im Repository-Ordner **`.github/workflows/`** die Datei `atlas-v082.yml` hochladen. Bei jedem Hochladen **Commit changes** auf dem Branch `atlas-v0.8`.
4. Der GitHub-Workflow `Atlas v0.8.2 Exposure and Causal Benchmark Diagnostics` sollte bei Änderung dieser Dateien automatisch starten. Link nach Hochladen: `https://github.com/janneswiele/atlas-trading-ai/actions/workflows/atlas-v082.yml`.
5. Erst nach dem erfolgreichen Lauf das Actions-Artefakt `atlas-v082-benchmark-diagnostics` herunterladen und die `SUMMARY_V082_DE.md` / `diagnostics.json` ansehen.

Der neue Workflow beschafft die amtlichen Kraken-BTC/EUR-Daten erneut, wiederholt den ursprünglichen versiegelten v0.8.1-Forschungsdurchlauf und erzeugt **danach** ausschließlich zusätzliche Diagnostik. Schlägt irgendein Schritt fehl, gilt die neue Forschung **nicht** als abgeschlossen, auch wenn möglicherweise Artefakte gespeichert wurden.

**Keine Dateien auf `main` überschreiben, kein Merge und keine automatischen Strategie-Freigaben.**

## Optional: lokale Ausführung

```sh
python -m pip install -r requirements-v08.txt
python -m pytest -q
python atlas_v082.py --input /pfad/zum/atlas-v08-research --output atlas-v082-diagnostics
```

`--output` muss auf einen **noch nicht existierenden** Ordner zeigen. Eingabedateien werden niemals verändert. Das Projekt verweigert die Ausgabe in die ursprünglichen Forschungsordner oder Projekt-Stammordner.

## Durchgeführte Prüfungen (vor GitHub-Upload)

- **19 neue synthetische v0.8.2-Tests bestanden**: inkl. Zeitkausalität, Unveränderlichkeit des Holdouts, Hash-/Datenqualitäts-Prüfung, Konto-Schutz, Benchmark-Kosten, Volatilitätskalibrierung und Überschreibschutz.
- **180 lokale Tests erfolgreich**, ohne 2 Dashboard-Prüfungen und 2 Testmodule, deren Abhängigkeiten (`streamlit`, `ccxt`) in der lokalen Python-3.13-Umgebung fehlen. Auf GitHub sind diese Pakete in `requirements-v08.txt` enthalten; **die vollständige aktualisierte Suite muss dort noch laufen**.
- **Echte v0.8.1-Research-Artefakte verarbeitet**: 14 primäre 90-Tage-Fenster, Bericht, CSV, Plots und SHA256SUMS erzeugt. **Kein eigener neuer Online-GitHub-v0.8.2-Lauf** vor dem Upload.
- **Keine Änderungen** an `paper.py`, `paper_state.json`, `paper_config.json`, `strategies.py`, `atlas_v08.py`, Research-Gates oder der produktiven Konfiguration.
