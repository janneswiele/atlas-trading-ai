# Atlas v0.9 auf dem iPad installieren

## Zuerst nur installieren und testen

1. **Atlas_Trading_AI_v0.9_MEGA_UPDATE.zip** herunterladen. In der Dateien-App
   unter Downloads einmal antippen: iPadOS entpackt die ZIP.
2. Im Browser [den bestehenden Forschungsbranch öffnen](https://github.com/janneswiele/atlas-trading-ai/tree/atlas-v0.8).
   Im Branch-Menü `atlas-v0.9` eingeben und **Create branch from atlas-v0.8** wählen.
   Falls dieser Branch bereits existiert, zuerst dessen Stand prüfen; nicht löschen.
3. Die ZIP enthält `UPLOAD` und `FULL_SOURCE_REFERENCE`. Für dein bestehendes
   Repository **ausschließlich den Inhalt von `UPLOAD`** verwenden. Den Ordnernamen
   `UPLOAD` nicht als zusätzliche Repository-Ebene hochladen.
4. Auf `atlas-v0.9`: **Add file → Upload files**. Die neuen Dateien und Ordner aus
   `UPLOAD` mit ihrer Struktur übernehmen. GitHub muss beispielsweise
   `atlas09/core.py` anzeigen, nicht `UPLOAD/atlas09/core.py` und nicht nur `core.py`.
   Wenn der iPad-Dateiauswahldialog keine Ordner übernimmt, im GitHub-Webeditor
   (`github.dev/janneswiele/atlas-trading-ai`, Branch kontrollieren) Ordner und
   Dateien mit denselben Pfaden erstellen oder die Dateien ordnerweise hochladen.
5. `paper_state.json`, `paper.py`, `paper_config.json` und `atlas-paper.yml` sind
   **nicht im UPLOAD-Ordner**. Keine Datei mit diesen Namen ersetzen.
6. Der versteckte Ordner `.github` kann in der Dateien-App unsichtbar bleiben.
   Dafür liegt außerhalb von UPLOAD die identische sichtbare Datei
   **WORKFLOW_ZUM_KOPIEREN.txt**. Inhalt kopieren; auf GitHub **Add file → Create
   new file**, als Namen exakt `.github/workflows/atlas-v09.yml` eintragen,
   Inhalt einfügen. Nicht `.txt` anhängen und nicht `atlas-paper.yml` bearbeiten.
7. **Commit changes** direkt auf `atlas-v0.9`, z. B. „Install Atlas v0.9 research“.
   Niemals auf `main` und noch nicht mergen. Größere Uploads können mehrere
   Commits benötigen; solange `enabled=false` bleibt, wird nicht gehandelt.
8. Unter [Actions](https://github.com/janneswiele/atlas-trading-ai/actions) den Lauf
   **Atlas v0.9 isolated shadow research** öffnen. Der Job `tests` muss grün sein.
   Der Job `shadow` wird im Lieferzustand absichtlich übersprungen.

`FULL_SOURCE_REFERENCE` ist eine vollständige Quellcode-Referenz für Prüfung und
Neuaufbau, **kein zusätzlicher Upload-Schritt**. Sie enthält keine produktiven
Kontodaten; deshalb kein bestehendes Repository damit ersetzen. Der zusätzliche Prüfstarter
`verify_v09_bundle.py` ist für eine Python-Entwicklungsumgebung gedacht; er prüft
die Referenz in einem temporären Git-Verzeichnis mit synthetischem Testkonto.
Du brauchst ihn auf dem iPad nicht auszuführen: Dort übernimmt GitHub Actions
die Tests im bestehenden Repository.

## Shadow-Forschung später ausdrücklich starten

Das aktiviert ausschließlich vier neue Forschungs-/Simulationskonten, nicht
Strategien im bisherigen Paper-Bot. Kein Echtgeld und kein Bezug auf dein altes
virtuelles Guthaben.

1. Auf `atlas-v0.9` die Datei `atlas_v09_config.json` öffnen, Stiftsymbol:
   nur `"enabled": false` in `"enabled": true` ändern und committen.
2. `atlas_v09_command.json` öffnen: `"action": "disabled"` in
   `"action": "activate"` ändern, `request_id` z. B. auf das aktuelle Datum setzen,
   committen. Möglichst innerhalb der ersten Stunde nach 00/04/08/12/16/20 UTC.
3. Der Workflow legt **atlas-v0.9-data** separat an und protokolliert die Aktivierung.
   Bei unvollständigem Warmup bleibt er bei `WARMUP`; das ist kein Handelsfehler.
   Der erste Aktivierungslauf handelt keine bereits abgeschlossene frühere Kerze.
4. Für den nächsten Lauf `action` auf `cycle` ändern und committen. Danach genügt
   eine Änderung von `request_id` für einen weiteren manuellen Zyklus.
   Nicht erneut `activate` verwenden. Den Datenbranch niemals löschen oder ersetzen.
5. **Noch keine automatische Vierstunden-Ausführung auf einem reinen
   Entwicklungsbranch.** Der Zeitplan benötigt später einen ausdrücklich
   freigegebenen Workflow auf dem Defaultbranch. Es ist nicht nötig, dafür jetzt
   main zu verändern. Nicht den Defaultbranch wechseln, um diese Schutzgrenze
   zu umgehen.

## Dashboard öffnen

Nach einem Lauf: Actions → Lauf → Artifacts → `atlas-v09-shadow-audit` herunterladen,
ZIP in Dateien entpacken und `dashboard.html` öffnen. Das ist eine gespeicherte
Momentaufnahme; sie führt keinen Bot aus. HTML-Vorschau auf iPadOS kann JavaScript
beschränken. Deshalb immer auch den ausgeschriebenen UTC-Zeitstempel prüfen.

Optional kann eine **separate** Streamlit-App desselben Repositories auf Branch
`atlas-v0.9`, Startdatei `atlas_dashboard_v09.py`, eingerichtet werden. Das bestehende
Dashboard auf main nicht umstellen. Diese App liest ausschließlich den öffentlichen
Datenbranch. Bei fehlendem Ledger zeigt sie eine Warnung statt erfundener Kontowerte.
Hosting wurde in dieser Lieferung nicht eingerichtet oder getestet; keine
kostenpflichtigen Optionen buchen. Für den Anfang reicht das HTML-Artefakt.

## Bei Fehlern

- Roter Test-Job: nicht aktivieren, ersten Fehler im Log öffnen.
- `Stale`: zur nächsten gültigen 4h-Prüfzeit erneut starten; keine früheren Kurse nachfüllen.
- `WARMUP`: weiter sammeln, keine Einstiege erwarten.
- `Code/config changed`: eingefrorene Studie nicht überschreiben; neue Studie prüfen lassen.
- `Circuit breaker`: nicht durch Löschen von Dateien „reparieren“; Ursache untersuchen lassen.
- `403` beim Daten-Push: Repository **Settings → Actions → General → Workflow
  permissions** und Branch-Regeln prüfen. Dieser Shadow-Job benötigt Schreibrecht
  auf `atlas-v0.9-data`. Keine Börsenschlüssel und keine Kreditkarte nötig.
- Stoppen: `enabled` auf `false`. Offene virtuelle Positionen werden dann nicht
  weiter verarbeitet; das ist eine Pause, keine echte Liquidation.

Anschließend kann auf GitHub ein überprüfbarer Pull Request von `atlas-v0.9`
vorbereitet werden. **Nicht automatisch mergen.**
