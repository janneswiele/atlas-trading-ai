# Atlas Trading AI — MVP

Ein erster, bewusst sicherer Prototyp für automatisiertes **Paper-Trading** mit einem Streamlit-Dashboard.

## Funktionen
- Öffentliche OHLCV-Kursdaten von Binance über CCXT (keine API-Schlüssel nötig).
- BTC/USDT, ETH/USDT und SOL/USDT; Zeitfenster 15m, 1h oder 4h.
- Drei regelbasierte Strategien: EMA Trend, RSI Reversal und Breakout.
- Historischer Out-of-sample-Test (chronologischer letzter 30%-Abschnitt).
- Auswahl nur bei mindestens 3 Trades, positiver Rendite, Drawdown besser als -15% und Profit Factor über 1,05.
- Virtuelles Konto mit SQLite, simulierte Kauf-/Verkaufsaufträge und Trade-Historie.
- Docker-Deployment für einen Cloud-Server.

## Lokal starten

Python 3.11 oder 3.12 empfohlen.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

Dann im Browser `http://localhost:8501` öffnen.

## Cloud-Server starten

Auf einem Linux-Server mit Docker und Docker Compose:

```bash
git clone <DEIN-REPOSITORY>
cd atlas_trading_ai
docker compose up -d --build
```

Dashboard: `http://SERVER-IP:8501`

**Sicherheit:** Port 8501 nicht ungeschützt öffentlich ins Internet stellen. Für den dauerhaften Betrieb HTTPS und Zugriffsschutz über einen Reverse Proxy (z. B. Caddy) oder ein VPN einrichten.

## Bedienung
1. Märkte und Zeitfenster auswählen.
2. Der Bot lädt abgeschlossene Kerzen und bewertet die Strategien.
3. „Paper-Bot jetzt ausführen“ simuliert höchstens eine Aktion je neu abgeschlossener Kerze und Markt.
4. Das virtuelle Konto und die Trade-Historie werden in SQLite gespeichert.
5. Das Paper-Konto kann über die Seitenleiste zurückgesetzt werden.

## Wichtige Grenzen des MVP
- **Kein Echtgeldhandel:** Es gibt absichtlich keine Order-Funktion und keine Möglichkeit, API-Schlüssel für Echtgeldorders einzutragen.
- Der Bot arbeitet auf abgeschlossenen Kerzen. Die automatische Prüfung läuft im Dashboard alle 60 Sekunden, solange die Browser-Sitzung geöffnet und der Auto-Modus eingeschaltet ist. Der Bot handelt nur einmal je neu abgeschlossener Kerze. Für einen unbeaufsichtigten 24/7-Betrieb ohne geöffnetes Dashboard braucht es als nächsten Schritt einen separaten Scheduler/Worker.
- Der Backtest ist ein vereinfachtes Modell. Er berücksichtigt Gebühren, aber nicht vollständig Spread, Slippage, Orderbuch-Tiefe, Teilausführungen oder Steuern.
- Die Strategieauswahl auf einem kurzen historischen Fenster ist statistisch unsicher. Mehrere Märkte/Strategien erhöhen das Risiko von Zufallstreffern und Overfitting.
- Die Portfolioanzeige bewertet offene Positionen vorläufig mit dem investierten Betrag; sie ist kein Echtzeit-Nettoinventarwert.
- Ergebnisse sind keine Renditeprognose. Vor echtem Einsatz sind längere Tests, unabhängige Validierung und ein belastbarer Risikoplan nötig.

## Nächste Entwicklungsstufe
1. Separater Worker mit zuverlässigem Scheduler und Heartbeat.
2. Mark-to-market-Bewertung und korrekte Equity-/Drawdown-Kurve.
3. Realistische Ausführungssimulation mit Spread und Slippage.
4. Walk-forward-Validierung über mehrere Zeiträume und Märkte.
5. Monitoring, Fehleralarme, tägliche Verlustgrenzen und Kill-Switch.
6. Erst nach unabhängiger Prüfung: optionale Echtgeld-Anbindung mit minimalen Rechten und Auszahlungsrechten deaktiviert.
