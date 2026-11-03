# Atlas Trading AI 0.4

Upgrade des bestehenden Projekts: historische Forschung plus automatisches **Paper-Trading**, keine Echtgeldorders und keine Exchange-Schlüssel. Technische Funktion ist kein Profitabilitätsnachweis.

## Was läuft wo?

- Das iPad zeigt nur das Streamlit-Dashboard. GitHub Actions führt den Bot unabhängig von geöffneten Tabs aus, **nach freigegebener Integration** etwa alle vier Stunden (`17 */4 * * *`, UTC).
- `python paper.py` liest das vorhandene `paper_state.json`, öffentliche BTC/EUR-Kurse von Kraken und die sichere Konfiguration. Der Workflow committet das neue Konto und den Status. `paper.py` ist der einzige v0.4-Automatik-Einstieg.
- `app.py` zeigt das Konto vom Remote-Main-Branch; Reload aktualisiert den Cache. Ein gemeinsamer Commit-Snapshot verhindert gemischte Datei-Versionen. Lokal kann `ATLAS_LOCAL_STATE=1` gesetzt werden; `ATLAS_STATE_REF` dient einer separaten Branch-Vorschau.
- Ohne gültige `strategy_report.json` gibt es **keine neuen Einstiege**. Bestehende Positionen werden weiterhin mit ihrer bisherigen Strategie und den Risikoregeln geprüft. Es wird kein Validierungsergebnis mitgeliefert oder erfunden.

## Start und Tests

Python 3.12 unter Linux (GitHub Actions/Streamlit). Dateisperren verwenden `fcntl`; Windows ist nicht unterstützt.

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python -m streamlit run app.py
```

Für lokale Kontoanzeige: `ATLAS_LOCAL_STATE=1 python -m streamlit run app.py`.
Docker: `docker compose up --build`; Docker wurde hier nicht gebaut. Das Dashboard ist nur Leser; ein lokaler Container startet keinen Hintergrundbot.

## Konto und Migration

`paper_state.json` bleibt die autoritative Datei. Der Upgrade-Patch enthält **keine Kontodatei**. Beim ersten erfolgreichen Zyklus wird der vorhandene Stand validiert und eine bytegenaue `paper_state.pre-v04.json` angelegt. Alte Felder bleiben erhalten, zusätzlich gibt es `legacy_snapshot`, Schema 4, Trades, Entscheidungen und Kontowertpunkte. Konto und neue Trades werden zusammen per temporärer Datei, fsync und atomarem Rename geschrieben; lokale Prozesse verwenden dieselbe Dateisperre. Fehlende/kaputte Kontodateien werden nie mit 100 EUR ersetzt.

Eine vorhandene `paper_trades.csv` bleibt unverändert. v0.4-Kennzahlen beginnen mit der Migration. Falls eine alte Position ohne belegbare Kostenbasis existiert, wird ihr späterer G/V als unbekannt markiert. Es werden keine alten Gebühren, Kaufzeiten oder Kontowertverläufe rekonstruiert. Offene Positionen werden zum letzten gespeicherten Bid bewertet; unrealisierter G/V ist vor hypothetischen Verkaufskosten. Buy & Hold startet gleichzeitig mit v0.4 und berücksichtigt modellierte Kosten.

`paper_status.json` meldet Erfolg/Fehler des letzten Versuchs. Bei Fehlern vor dem Konto-Commit bleibt das Konto unverändert. Ein Prozessabbruch nach Konto-Commit, aber vor Status-Commit kann einen älteren Status hinterlassen: Konto und GitHub-Laufprotokoll vergleichen. Ein GitHub-Push-Fehler kann nicht zuverlässig in dieselbe Remote-Datei geschrieben werden; hierfür Actions prüfen und das 14 Tage aufbewahrte Lauf-Artefakt nutzen.

## Handels- und Risikoregeln

- BTC/EUR, Spot, long-only, maximal eine Position und 20% des freien Guthabens je Einstieg. Kein Hebel, kein automatisches Nachkaufen.
- 0,1% Gebühr und 0,05% Slippage pro Fill. Kauf am aktuellen Ask plus Slippage; Verkauf am Bid minus Slippage. Der tatsächliche Spread kommt hinzu.
- Signale nur aus abgeschlossenen, lückenlosen 4h-Kerzen. Nicht-endliche Preise, falsche OHLC-Beziehungen, doppelte Zeitstempel, Zukunftsdaten, ältere verarbeitete Kerzen, breite Spreads und lokal veraltete Quotes werden abgelehnt.
- Eine bereits verarbeitete Kerze erzeugt keine zweite Order, auch nach Neustart. Versäumte Kerzen werden nicht rückwirkend zum historischen Kurs gehandelt; bewertet wird die neueste gültige Kerze. Mehrere Handelsprüfungen innerhalb einer Kerze sind absichtlich ausgeschlossen.
- 2% simulierter Stop / 4% Gewinnziel, 3% Tagesverlustgrenze (UTC-Prüftage), 10% Drawdown-Sperre ab beobachtetem Höchststand. Limits werden nur bei gültigen Zyklen gemessen; Tagesanfang ist die erste beobachtete Bewertung des Tages.
- Drawdown-Sperre bleibt im Konto gespeichert. Keine automatische Wiederfreigabe. Entsperrung erst nach manueller Prüfung/gesichertem Konto; nicht durch Reset umgehen.
- `paper_config.json`: `trading_enabled: false` ist der manuelle Gesamtschalter. Er pausiert **auch Ausstiege**; Bewertungen laufen weiter. Nur über einen überprüften GitHub-Commit ändern. Das Dashboard schreibt keine Konfiguration.
- Simulierte Stops werden erst beim tatsächlichen Lauf zum dann verfügbaren Preis geprüft. Sie garantieren weder einen Ausstiegskurs noch eine maximale Verlusthöhe.

## Forschung und Strategieauswahl

Bestehende EMA Trend, RSI Reversion (im alten engine.py anders als RSI Reversal bezeichnet), Breakout plus SMA 20/50. Es werden die bereits vorhandenen Signaldefinitionen aus strategies.py verwendet, ohne endlose Parametersuche.

`research.py` erwartet mindestens 1000 lückenlose, abgeschlossene BTC/EUR-4h-Kerzen als CSV (`timestamp` in UTC-Epoch-Millisekunden, `open,high,low,close,volume`). Herkunft und Währung müssen vor der Verwendung geprüft werden. Kraken OHLC liefert nur ein rollierendes kurzes Fenster; eine einzelne Anfrage reicht nicht. Das Upgrade enthält noch keinen langfristigen automatischen BTC/EUR-Archivaufbau.

```bash
python research.py btc_eur_4h.csv
```

Der Befehl erzeugt einmalig `strategy_report.json` und verweigert das Überschreiben einer bestehenden Studie. Parameter sind fest. Zeitaufteilung 60/20/20 mit 200 Warm-up-Kerzen am Anfang. Training und Validierung müssen jeweils mindestens 10 geschlossene Trades, positive Nettorendite, Profit-Faktor ≥1,10, Drawdown nicht schlechter als -10% und mindestens Buy-&-Hold-Rendite erreichen. Das sind vorab gesetzte Forschungsgrenzen, kein statistischer Signifikanznachweis.

Aus den zulässigen Strategien wird einmalig anhand der Validierungsrendite ausgewählt. **Erst danach** wird nur der Gewinner im Holdout ausgewertet. Holdout wird nicht zum Umwählen verwendet. Offene Positionen werden am Segmentende bewertet, aber nicht als geschlossene Gewinne gezählt. Die Freigabe gilt für kommende Kerzen, maximal 30 Tage, nur bei identischem Strategiecode, Markt, Kosten und Risikoannahmen. Ein neuer Bericht benötigt eine neue überprüfte Studie; automatische rollierende Neuauswahl ist bewusst nicht implementiert.

Die Auswahl-Simulation prüft Stops nur an 4h-Opens, verwendet maximal 20% Kapital und modelliert Kosten. Tatsächliche Actions-Verzögerungen und variable Spreads kann sie nicht exakt reproduzieren. Der bestehende Dashboard-Backtest bleibt separat erhalten (ATR-Stops, Intrabar-Annahmen, angenommene Liquidation am Testende). Er und die Walk-forward-Suche erzeugen **keine** Paper-Freigabe. Die Holdout-Vergleichstabelle ist explorativ und darf nicht zur rückblickenden Auswahl dienen.

## Workflow, Fehler und Wiederherstellung

Concurrency `atlas-paper`, kein Abbruch laufender Zyklen, Checkout des aktuellen Main-Standes, 10-Minuten-Timeout, Inhalts-Schreibrecht nur im Paper-Job. Der vorbereitete Workflow läuft ausschließlich auf Main; ein Branch-Test kann kein produktives Konto fortschreiben. Der separate CI-Workflow prüft Syntax und Tests ohne Schreibrechte.

Kein Force-Push, kein automatisches Rebase von Kontodaten. Wenn während eines Laufs ein externer Commit dazukommt, kann der Push sicher scheitern. Nicht blind das Lauf-Artefakt über Main kopieren: letzten erfolgreichen Konto-Commit und fehlgeschlagenes Artefakt vergleichen. Ein nicht gespeicherter Paper-Fill ist keine externe Order und darf nach Prüfung verworfen werden. Der nächste Lauf arbeitet ausschließlich mit dem zuletzt gespeicherten Remote-Konto.

GitHub kann Zeitpläne verzögern/auslassen; öffentliche Repositories können nach 60 Tagen ohne Aktivität deaktivierte Zeitpläne haben. Kein 24/7-Server. Dashboard-Status nach sechs Stunden als überfällig markiert. Der Workflow benötigt die Repository-Berechtigung zum Pushen; Branch-Regeln können ihn verhindern. CI-/Artifact-Nutzung bleibt innerhalb deiner GitHub-Konditionen; keine kostenpflichtigen Dienste wurden aktiviert.

## iPad-Integration

Noch nicht gemergt oder bereitgestellt. Siehe `docs/IPAD_INTEGRATION.md`. Zuerst Branch und PR prüfen, **erst nach ausdrücklicher Freigabe** mergen. Das aktuelle Dashboard zeigt bis dahin weiterhin die bestehende Version.

## Einschränkungen und nächste Schritte

Kein Echtgeldmodus, keine Gewinnerstrategie, keine garantierten Termine. Bestehendes engine.py/SQLite-System bleibt als Legacy-Code unverändert und darf nicht parallel als zweite Paper-Engine gestartet werden. JSON wächst mit der Historie; später archivieren, nicht still kürzen. UTC-Anzeige; iPad-Browser-Layout wurde nicht visuell geprüft. Externe Streamlit-Bereitstellung und neuer GitHub-Workflow brauchen nach Integration einen echten Abnahmelauf.

Nächste Schritte: Schreibzugriff reparieren, PR/CI prüfen, kontrolliert integrieren; danach mehr BTC/EUR-Historie mit belegbarer Herkunft archivieren und einen vorab festgelegten Forschungsbericht erzeugen. Anschließend mehrere Wochen prospektives Paper-Trading beobachten.

Quellen: [GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [Kraken OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data).
