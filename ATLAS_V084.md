# Atlas Trading AI v0.8.4 – zwei festgelegte Strategien, Forschung ausschließlich

**Status: RESEARCH ONLY / KEINE TRADING-FREIGABE.** Keine Änderungen an `main`, `paper.py`, `paper_state.json`, `paper_config.json`, an dessen Berechtigungen oder an einer Echtgeld-Anbindung. Der finale globale 20%-Holdout wird niemals ausgewertet. Das historische Entwicklungsfenster ist bereits mehrfach untersucht und deshalb **kein** neuer unabhängiger OOS-Test.

## Erkenntnis aus Deep Research

Deep Research fand Gründe, *Trendfolge/Time-Series-Momentum* gegenüber einem zu komplexen KI-Blackbox-Modell zuerst als nachvollziehbare Hypothese zu testen; es lieferte **keinen** Gewinnnachweis für BTC/EUR. Deshalb **nur zwei feststehende Regeln**, kein Nachoptimieren mit 12/30/100 Parameterkombinationen und kein Auswahlprozess basierend auf alten Daten.

### Kandidat A: Donchian-30 mit Chandelier-Ausstieg

- Vierstündige **abgeschlossene UTC-Kerzen**, ausschließlich BTC/EUR Spot, keine Shorts, kein Hebel.
- Kaufsignal wenn `close[t]` den Höchstwert der `high`-Preise der vorherigen **30 vollständig abgeschlossenen** Kerzen übersteigt UND die vorige Kerze noch nicht über ihrem damaligen 30er-Hoch lag; Kauf frühestens **Open[t+1]**.
- Zusätzlicher Ausstieg bei `close[t] < highest(high[t-21:t]) - 2.5 × ATR14[t]` mit frühestem Verkauf bei **Open[t+1]** (Chandelier Exit, kein hypothetischer intrabar-Stop-Fill).
- **Der bisherige feste 2%-Stop und 4%-Take-Profit bleiben unverändert zusätzlich aktiv.** Auch Tagesverlust 3%, Drawdown 10%, 20%-Initial-Allokation bleiben. Dadurch kann die neue Exit-Regel einen Trade **früher**, aber nie wegen eines gelockerten Risikolimits später schließen.

### Kandidat B: Momentum-60 mit Volatilitätsfilter

- Kauf bei `close[t] > close[t-60]` und 30-Kerzen-Logrenditenvolatilität ≤ **1,5 × Median der 180 vorangegangenen Volatilitätsmessungen**. Reines Zustandswechsel-Kaufsignal, kein Einstieg bei jeder positiven Kerze.
- Ausstieg, sobald Momentum nicht mehr positiv oder Volatilität zu hoch ist. Signale ausschließlich aus Candle t, Ausführung frühestens Open[t+1].
- Gleiche unveränderte Risikolimits und Gebührenannahmen. Kein Tuning von Perioden, Limits oder Schwellen.

### Vergleichsprotokoll

- Reproduziere zuerst unveränderte Ergebnisse der **SMA20/50**- und **EMA Trend**-Baselines bis auf Kontokurvenebene. Abweichungen **brechen ab**.
- Vergleiche alle vier Strategien in denselben **sieben disjunkten historischen 90-Tage-Fenstern**, je mit 100 EUR virtuellem Neustart; 541 vorangegangene Kerzen als Warmup. Keine gefälschten/interpolierten Lücken; alle Quellen nur **vor** dem versiegelten Holdout.
- Feste **20% Buy-and-Hold**-Benchmark plus passiver, anhand der vorherigen 341 Bars kalibrierter Volatilitätsbenchmark; der ist eine Diagnose und beweist keine identische realisierte Volatilität.
- Konservative Forschungsannahmen aus dem Originalartefakt: **0,6% Gebühr pro Fill + 0,05% Slippage**, jeweils x1/x2/x3; kein intrabar-perfect-fill, kein marktnaher Echt-Handelsnachweis.
- Statistische Streuung: Bootstrap der paarweisen *Fenster*-Alpha-Werte, Holm-Korrektur über **zwei** zusätzliche Hypothesen, nur explorativ. Die bisherige Forschungshistorie erhöht die effektive Zahl betrachteter Strategien. Ein p-Wert aus diesen Fenstern ist kein bestätigender Signifikanznachweis.
- Kraken als Gegenprüfung auf **demselben 541+540-Bar-Intervall**: fehlende Bars führen zum Ausschluss genau dieses Fensters, nicht zur Interpolation. Coinbase-Sample ist der unveränderliche primäre Vergleich.
- `release_gate.passed = false`, `paper_trading_authorized = false`, `holdout_evaluated = false`. Nie automatisch Paper-Trading ändern, erst recht kein Echtgeld.

## Bereits lokal mit echten, gegengeprüften Daten beobachtet

Die folgenden Ergebnisse sind wiederverwendete historische Entwicklungsdaten, **nicht** unabhängiges Out-of-sample und **keine** Handelsfreigabe.

| Strategie | abgeschlossene Trades (7 × 90 Tage) | Mittel Netto-Rendite / Fenster | Mittlere Differenz zur passiven 20%-Anlage (Prozentpunkte) | Durchschnittliche Exposure |
|---|---:|---:|---:|---:|
| SMA 20/50 (unverändert) | 41 | +0,22% | -3,16 | 3,31% |
| EMA Trend (unverändert) | 19 | -0,26% | -3,65 | 2,54% |
| Donchian-30 + Chandelier | 70 | **-2,43%** | **-5,81** | 4,52% |
| Momentum-60 + Volatilitätsfilter | 100 | **-1,96%** | **-5,34** | 4,11% |

Die beiden **neuen** Strategien haben in der bisher analysierten Historie nicht überzeugt. Zusätzliche Kostenstress-Szenarien verschlechtern die Ergebnisse. Direkte Kraken-Parität war in **5 von 7** vollständigen Fenstern ohne Dateninterpolation möglich; dort zeigt sich ebenfalls kein belastbarer positiver Vorteil. **Beide Strategien bleiben gesperrt.** Weder mehr Trades noch mehr Kapitalexposure sind an sich ein Erfolgsbeweis.

**Wichtig:** Das Beispiel untersucht bewusst nur die schon bekannten Daten; das finale Holdout bleibt geschützt. Nachträgliches Anpassen der Parameter an die hier gesehenen Verluste würde den Forschungsbeweis entwerten. Der fachlich nächste Schritt ist: die Kandidaten dokumentiert verwerfen oder langfristig **neue** unverbrauchte Paper-Daten für eine *vorab definierte* Hypothese sammeln.

## iPad-Installation (ausschließlich Branch `atlas-v0.8`)

1. `Atlas_Trading_AI_v0.8.4_iPad_Update.zip` in der iPad-App **Dateien** entpacken.
2. Auf `https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8` die drei Dateien `atlas_v084.py`, `test_atlas_v084.py`, `ATLAS_V084.md` hochladen und „Commit changes“ wählen.
3. Auf `https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8/.github/workflows` **nur** `atlas-v084.yml` hochladen und „Commit changes“ wählen.
4. In `https://github.com/janneswiele/atlas-trading-ai/actions` den Workflow **Atlas v0.8.4 Frozen Candidate Research (NO TRADING)** ansehen; der Push löst ihn selbst aus.
5. Unter **Artifacts** `atlas-v084-exploratory-no-trading` öffnen. In `BERICHT_V084_DE.md`, `diagnostics.json`, `historical_paired_windows.csv` stehen Ergebnisse, Datenlücken und Freigabesperre.

Die beiden Zip-Dateien mit Code und lokalen Forschungsdaten dienen zur Übertragung und Archivierung. Nur das **iPad-Update** in GitHub hochladen. Die separate Ergebnisdatei enthält keine benötigten Projektdateien. Ein erfolgreiches GitHub-Action-Ergebnis beweist technischen Betrieb, **nicht** Profitabilität.
