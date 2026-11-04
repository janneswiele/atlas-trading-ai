# Atlas Trading AI v0.8.5: Kosten- und Break-even-Prüfung

**Nur Forschung, keine Handelsfreigabe.** Ausschließlich `atlas-v0.8`-Forschungsbranch. Der globale finale 20%-Holdout wird nicht ausgewertet. `main`, `paper.py`, `paper_state.json`, `paper_config.json`, Live-/Paper-Workflows und Handelsfreigaben bleiben unverändert.

## Warum diese Version?

Die beiden v0.8.4-Strategien Donchian-30+Chandelier und Momentum-60+Volatilitätsfilter waren trotz unveränderter 2%-Stop/4%-Take-Profit-Schwellen in sieben bereits mehrfach untersuchten 90-Tage-Fenstern netto schlechter als eine passive 20%-BTC/EUR-Position. Atlas verwendet in der Forschung 0,6% Gebühren **pro Fill** plus 0,05% Slippage pro Fill. Die tatsächlichen Kosten sind wichtig: Die öffentlich ausgewiesene niedrigste Kraken-Pro-Spotstufe für Taker beträgt derzeit 0,8% pro Fill. Quellen: https://www.kraken.com/pro/fees und https://support.kraken.com/articles/201893638-how-trading-fees-work-on-kraken (Stand 4. November 2026). Gebühren hängen von Börse, Paar, Maker/Taker und 30-Tage-Volumen ab; **0,5% ist nur ein illustratives Szenario**, kein zugesagter Tarif.

## Festgelegtes Diagnoseprotokoll

Auf **genau denselben sieben bereits bekannten**, nicht überlappenden, historischen 90-Tage-Fenstern, unter vollständig identischen Entry-/Exit- und Risiko-Regeln, werden SMA 20/50, EMA Trend, Donchian 30 + Chandelier, TSMOM 60 + Volatilitätsfilter mit je fünf **nicht optimierten** Gebührenannahmen verglichen:

| Szenario | Gebühr pro Kauf/Verkauf | Zusätzliche Slippage pro Fill |
|---|---:|---:|
| Unrealistische gebührenfreie Diagnose | 0,0% | 0,05% |
| Illustrative niedrigere Gebühr | 0,5% | 0,05% |
| Ursprüngliche Forschungsannahme | 0,6% | 0,05% |
| Veröffentlichtes Kraken-Pro-Tier-1-Taker-Beispiel | 0,8% | 0,05% |
| Zusätzlicher Stress | 1,2% | 0,05% |

Der passive 20%-Benchmark wird **je Szenario mit denselben Kosten** berechnet. Trades werden weiterhin ausschließlich frühestens am Open der nächsten 4h-Kerze simuliert. Historische Coinbase/Kraken-Datenqualität und die unveränderten SMA-/EMA-Baselines werden vor dem Lauf gegen originale Dateien und Kontokurven geprüft; die Forschung stoppt, wenn diese nicht reproduzierbar sind. Kein Fitting, keine neue Signalselektion. Alle Kosten sind illustrative Ausführungsannahmen und keine live beobachteten Fill-Preise.

## Bereits lokal gemessene Forschungsresultate

Auf den bekannten Vor-Holdout-Fenstern (kein unabhängiges OOS) ergab sich folgende **mittlere Nettorendite pro Fenster**, Startwert pro Fenster 100 EUR:

| Strategie | 0,0% Gebühr | 0,6% Gebühr | 0,8% Gebühr |
|---|---:|---:|---:|
| SMA 20/50 | +1,65% | +0,22% | −0,24% |
| EMA Trend | +0,42% | −0,26% | −0,49% |
| Donchian-30 + ATR | +0,04% | −2,43% | −3,23% |
| Momentum-60 | +1,46% | −1,96% | −3,07% |

Alle vier Strategien blieben bei 0,8% unter der passiven 20%-BTC/EUR-Benchmark. Das reine Reduzieren von Gebühren liefert noch **keinen belegten, handelbaren Vorteil**.

### Warum 2% Stop / 4% Take-Profit kostensensitiv sind

Bei hypothetischer Ausführung exakt an den Stop-/Take-Profit-Schwellen und den oben genannten Gebühren/Slippage gilt näherungsweise:

| Gebühr je Fill | Netto-TP | Netto-Stop | nötige TP-Trefferquote, wenn es nur diese zwei Ausstiege gäbe |
|---|---:|---:|---:|
| 0,6% | +2,71% | −3,22% | 54,3% |
| 0,8% | +2,30% | −3,60% | 61,1% |

Diese Rechnung ist **keine Vorhersage**; im realen Backtester erfolgen Stop/TP-Ausstiege am nächsten 4h-Open, ggf. mit Gap und anderen Signal-Ausstiegen.

## Sicherheitsstatus und Folgerung

- `release_gate.passed=false`, `paper_trading_authorized=false`, `holdout_evaluated=false`.
- Keine Änderung an Handelsparametern, Strategien, Gebühren im produktiven Paper-Simulator oder am `main`-Branch.
- Diese Kostenvergleiche sind **explorativ** auf bereits gesehenen Daten. Es ist unzulässig, daraus nachträglich eine Gewinnerstrategie herauszupicken.
- Nächster Forschungsschritt: **Vorab festgelegte Hypothese auf künftig neuen Paper-Daten**, mit zeitstempelgenauen simulierten Order-Ausführungen, realistischem Gebührenmodell und unabhängiger Beurteilung. Die bisherigen Strategien bleiben gesperrt.

## iPad-Installation

1. `Atlas_Trading_AI_v0.8.5_iPad_Update.zip` in der Dateien-App entpacken.
2. `atlas_v085.py`, `test_atlas_v085.py`, `ATLAS_V085.md` auf `https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8` hochladen und committen.
3. **Nur** `atlas-v085.yml` nach `https://github.com/janneswiele/atlas-trading-ai/upload/atlas-v0.8/.github/workflows` hochladen und committen.
4. In `https://github.com/janneswiele/atlas-trading-ai/actions` den Forschungsworkflow `Atlas v0.8.5 Fee Feasibility Audit (RESEARCH ONLY)` beobachten.
5. Das GitHub-Artefakt `atlas-v085-fee-audit-no-trading` enthält den deutschsprachigen Forschungsbericht, die vollständige Kostentabelle, Prüfprotokolle und die unveränderte Sperre.

**Wichtig:** Keine historische Diagnose ist ein Nachweis künftig profitablen Tradings. Hier wird ausschließlich auf dem Forschungsbranch gearbeitet, nie mit realem Geld.
