# Atlas Trading AI v1.0 — Changelog

## 2026-11-04 — v1.0 offline research / safe auto-demo staging

- + 30 reproduzierbare und kausale Strategiekandidaten (SMA, EMA, Momentum, Donchian, ATR) mit fixierter Parameterauswahl.
- + Gebühren- und slippagebewusste, ausschließlich virtuelle Next-Bar-Open-Simulation. Dieselben festen Grundlimits wie v0.9.
- + Walk-forward-Forschung mit strikter Trennung der Trainingsentscheidung von der folgenden Validierung.
- + SHA-gebundene Datenherkunft und explizite Holdout-Sperre ab 2026-02-24; spätere Daten benötigen gesonderte Freigabe.
- + Automatische reproduzierbare Forschungsvorschläge für menschliche Prüfung; KEIN KI-Auto-Merge.
- + Ledger-Hashketten-Prüfer und iPad-Streamlit-Dashboard plus offline HTML-Snapshot.
- + Entwicklungstest-Workflow und vorbereiteter, auf `main` noch NICHT installierter Scheduler für das unveränderte v0.9-Forschungsledger.
- + 49 neue Tests; 49 lokal bestanden, synthetischer Forschungs-Smoke-Test erfolgreich.
- = Kein bestehendes v0.9-Modul verändert. Keine produktive Paper-Kontendatei verändert. Keine Echtgeld-Orders.

Ausstehend: Upload/CI auf GitHub (Schreibzugriff 403), Scheduler-Freigabe, Dashboards-Hosting, echte vorab genehmigte Datensätze. Die neue v1.0-Version ist ein funktionierendes **Forschungs- und Integrationsupdate**, jedoch noch kein autonomer Gewinnerzielungs-Bot.
