# Atlas v0.8.5 – Gebührenrealismus und Break-even (nur Forschung)

**Keine Strategie freigegeben.** Ausschließlich bisherige historische Entwicklungsfenster, kein neuer OOS-Beweis. Globaler Holdout versiegelt.

## Bestehende vier Strategien, unveränderte Signale und Risikoregeln

| Modell | 0,0% Gebühr: Return je Fenster | 0,6% Gebühr: Return je Fenster | 0,8% Gebühr: Return je Fenster | 0,8% Gebühr: Alpha vs passive 20% |
|---|---:|---:|---:|---:|
| SMA 20/50 | +1.65% | +0.22% | -0.24% | -3.53 pp |
| EMA Trend | +0.42% | -0.26% | -0.49% | -3.78 pp |
| Donchian30_Chandelier22_ATR14x2p5 | +0.04% | -2.43% | -3.23% | -6.52 pp |
| TSMOM60_Vol30_180x1p5 | +1.46% | -1.96% | -3.07% | -6.36 pp |

## Stop/Take-Profit-Kostendruck (vereinfachte hypothetische Schwellenfills)
Bei unverändertem 2% Stop und 4% Take-Profit, zusätzlich 0,05% Slippage pro Fill:

| Gebühr je Ausführung | Nettoertrag TP | Nettoverlust Stop | nötige Gewinnquote bei ausschließlichen TP-/Stop-Exits |
|---|---:|---:|---:|
| 0.0% | +3.95% | -2.05% | 34.2% |
| 0.5% | +2.91% | -3.02% | 50.9% |
| 0.6% | +2.71% | -3.22% | 54.3% |
| 0.8% | +2.30% | -3.60% | 61.1% |
| 1.2% | +1.48% | -4.37% | 74.7% |

Die Tabelle ist eine Kostenidentität, kein Prognosemodell. Gaps, andere Ausstiege und Marktverhalten verändern echte Gewinnquoten.
Bei Kraken Pro ist 0,8% Taker-Gebühr in der niedrigsten Spot-Stufe öffentlich ausgewiesen (4. November 2026).
Quelle: https://www.kraken.com/pro/fees
Auch niedrigere Gebühren verwandeln ein negatives Forschungsergebnis nicht automatisch in ein robustes Handelssignal.
Weitere Daten und Einschränkungen: fee_diagnostics.json und historical_fee_scenarios.csv.
