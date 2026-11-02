# Atlas Trading AI — Forschungsgrundversion

Die Version 0.2 lädt historische Spot-Kerzen, paginiert seit-basiert, speichert lokal in SQLite und testet drei Long-only-Strategien. Zusätzlich gibt es eine begrenzte Walk-forward-Parametersuche, die jeden Fold auf früheren Daten einstellt und auf dem direkt folgenden Zeitfenster prüft. Es gibt **keine** Exchange-Order-Implementierung. Echtgeldhandel kann durch diese Version nicht ausgelöst werden.

## Start

1. Python 3.11 oder neuer installieren.
2. Im Projektordner `pip install -r requirements.txt` ausführen.
3. `streamlit run app.py` starten und die angezeigte Adresse im Browser öffnen.
4. Auf dem iPad müssen iPad und Computer im selben WLAN sein; Streamlit mit `streamlit run app.py --server.address 0.0.0.0` starten und die lokale IP des Computers öffnen. Das iPad selbst führt den Python-Server nicht dauerhaft aus.

## Umfang und Annahmen

- Datenquelle OKX (Standard) oder Kraken, öffentliche Marktdaten ohne Schlüssel.
- Unterstützte Intervalle: 5m, 15m, 1h, 4h, 1d. Die API kann je Exchange/Symbol weniger Historie anbieten.
- SQLite-Kerzen-Cache verhindert wiederholte Abrufe derselben Kerzen.
- EMA Trend, RSI Reversion und Breakout. Signale werden am Schluss der Kerze berechnet und frühestens zum nächsten Open ausgeführt.
- Gebühren und Slippage werden je Fill modelliert. ATR-basierter Stop und Take; wenn beides intrabar berührt wird, gilt konservativ der Stop zuerst. Spot, Long-only, kein Leverage.
- Risikobudget pro Einstieg 0,5% des Kassenstands; Positionswert maximal 20%. Das ist kein Verlustlimit und schützt nicht gegen Kurslücken.
- Forschungsausgabe enthält Holdout-Trades und Diagnosewerte. Die aktuelle Split-Implementierung ist vorläufig und wird vor einer Strategieauswahl noch verbessert.
- Walk-forward-Parameterforschung ist ein Diagnosewerkzeug; der Trainings-Score wählt keine Strategie für einen späteren Live- oder Paper-Betrieb aus.

## Tests

`python -m pytest -q`

## Noch nicht implementiert

Live-Paper-Schleife, persistentes virtuelles Portfolio, Regimeanalyse, vollständige statistische Kennzahlen, Aktien/FX-Adapter, ausführliche Order-/Trade-Auditdaten und Dashboard-Auswertung über mehrere Läufe. Echtgeldhandel bleibt nicht nur deaktiviert, sondern ist in dieser Version nicht vorhanden.
