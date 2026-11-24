# Atlas Trading AI v1.0 — Code-Audit und ehrlicher Lieferstatus
**Prüftag: 4. November 2026** · Repository: `janneswiele/atlas-trading-ai` · Basis: `atlas-v0.9` · vorgesehener Branch: `atlas-v1.0-development`

## Vorher überprüft

- GitHub-Standardbranch `main`: bisheriger Paper-Bot, letzter gelesener Status **100,00 EUR**, **0 Trades**, `Halten: keine zugelassene Strategie`.
- GitHub-Branch `atlas-v0.9`: isolierter virtueller Forschungslauf, vier separate 100-EUR-Konten, vollständiger `300 passed`-Workflow vor dieser v1.0-Arbeit. `enabled: true`.
- `atlas-v0.9-data`: aktiviertes, dauerhaftes v0.9-Forschungsledger. Letzter zuvor geprüfter Versuch endete nach Aktivierung mit `Stale or open candle / delayed execution`, nicht mit einem Trade. Die Fehlermeldung ist Teil der sicher persistierten Ereigniskette.
- Geschütztes historisches Holdout ab **2026-02-24T00:00:00Z**, offizieller v0.9-Neudatenstart **2026-10-01T00:00:00Z**. Der historische Holdout wurde für die v1.0-Forschung NICHT geöffnet.
- Die aktuelle GitHub-App-Verbindung verweigerte das Anlegen von `atlas-v1.0-development` mit **403 Resource not accessible by integration**. Es wurden KEINE neuen Commits geschrieben, weder auf `main` noch anderswo.

## Implementierte Komponenten (neu, ohne die 0.9-Forschungsdateien zu bearbeiten)

| Datei | Tatsächlich implementiert |
|---|---|
| `atlas10/policy.py` | OHLC-Prüfung, 4h-Lückenverbot, SHA256-bindende explizite Dataset-Freigabe, historische Holdout-Sperre, eingefrorenes Risiko |
| `atlas10/signals.py` | 30 vordefinierte Varianten: SMA, EMA, Momentum, Donchian, ATR-Ausbruch, ATR-Exit und Volatilitätsfilter |
| `atlas10/backtest.py` | Long-only Simulation, NÄCHSTER Kerzen-Open, Gebühren/Slippage, max. 20% Allokation, Stop-/Take-Open-Prüfung, Drawdown-Tagesstopp, virtuelle Trades und Equity-Kurve |
| `atlas10/research.py` | Chronologische Walk-forward-Folds mit Training-only-Auswahl und separatem Validierungsbericht, nie automatische Trading-Freigabe |
| `atlas10/monitor.py` | Read-only Prüfung der v0.9-Ledger-Hashkette und Siegelprüfung, kein Konto-Schreibzugriff |
| `atlas10/dashboard.py` | Responsives Streamlit-Dashboard, bestehende Konten und experimentelle Forschung, keine Handelsbuttons |
| `atlas10/report.py` | Offline-HTML-Snapshot für iPad aus einem bereits vorhandenen Ledger |
| `atlas10/proposals.py` | Automatische, regelbasierte Verbesserungs-Hypothesen, nur Review, keine Code-Modifikation |
| `atlas_v10.py` | CLI für Forschung, Überwachung, Offline-Snapshot, Vorschläge |
| `.github/workflows/atlas-v10-research.yml` | Neue CI auf dem vorgesehenen Entwicklungsbranch, vollständige Tests und ausdrücklich synthetischer Research-Smoke-Test |
| `STAGED_ONLY/.github/workflows/atlas-v10-forward-scheduler.yml` | Für `main` vorbereiteter minimaler Zeitplan, streng auf vorhandenes v0.9-Forschungsledger, keine Neuanlage/kein Reset; **NICHT INSTALLIERT** |

## Tatsächliche Tests

- **49 neue lokale v1.0-Tests bestanden.** Python-Kompilierung erfolgreich.
- Vollständiger synthetischer Forschungs-Smoke-Test lief erfolgreich: 30 Strategievarianten, 3 Walk-forward-Folds, JSON-Ergebnisse und Vorschlagsdateien erzeugt.
- CI/YAML/Shell-Syntax geprüft. SHA256-basierte Schutzprüfung aller `V09_BASELINE_SHA256.json`-Dateien bestanden.
- Die gesamte alte Suite **konnte in dieser lokalen Umgebung nicht erneut ausgeführt werden**, weil `ccxt` und `streamlit` hier nicht installiert sind und kein Internetzugriff für die Installation besteht. Die letzte zuvor verifizierte GitHub-v0.9-Ausführung hatte **300 bestandene Tests**. Nach Upload soll die neue CI die Alt- und Neutests gemeinsam ausführen.
- Kein Beleg für Handelsprofitabilität. Alle Demo-Kursergebnisse stammen aus explizit **synthetischen** Daten.

## Noch NICHT erledigt / ehrliche Restarbeiten

1. Repository-Upload auf `atlas-v1.0-development` (GitHub-Schreibrecht fehlte).
2. Erfolgreicher integrierter GitHub-v1.0-Workflow-Lauf auf dem neuen Branch.
3. Erstfreigabe des **separat vorbereiteten** v0.9-Forschungsschedulers auf `main` und erfolgreicher neuer Forward-Datenzyklus. Vorher läuft der v1.0-Automat nicht dauerhaft.
4. Hosting des Streamlit-Dashboards; aktuell nur ausführbarer Quellcode und Offline-Snapshot-Erzeuger.
5. Echte, **neu freigegebene** Marktdaten für autonome Forschung; keine automatische Strategie-Freigabe oder echte KI-Code-Selbstbearbeitung.
6. Eine produktionsreife autonome Code-Änderungs-KI mit überprüften Pull-Requests und Review-Gates ist ein späterer Ausbau.

## Unveränderlichkeiten

- `main`, `paper.py`, `paper_config.json`, `paper_state.json` und ursprüngliche Paper-Workflows wurden NICHT bearbeitet.
- `atlas09/` sowie `atlas_v09.py` und deren `source_hash` blieben unverändert, damit das signierte v0.9-Ledger weiterlesbar bleibt.
- `atlas-v0.9-data` wurde weder zurückgesetzt noch ersetzt, nicht in die Archive kopiert.
- Nur virtuelle Orders; keine Echtgeld-API, keine Login-/API-Schlüssel, kein automatischer Champion-Wechsel.
- Der v1.0-Forschungs-Scheduler wird **nicht** ohne ausdrückliche Freigabe nach `.github/workflows/` auf `main` installiert.
