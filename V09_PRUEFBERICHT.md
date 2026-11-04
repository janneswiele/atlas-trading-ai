# Atlas v0.9 — Abschluss- und Forschungsbericht

Stand 2026-11-04. Dieses Update ist ein lokal geprüftes, installierbares
Forschungs-Zwischenresultat. Die vollständige operative Abnahme auf GitHub steht
noch aus. Es wurde kein Remote-Upload oder automatischer Betrieb vorgetäuscht.

## Repository und Schutz

Ausgangsbranch `atlas-v0.8`, v0.8.4, Commit
`6fd559561ac2acace285b67c01e46ab8101d7be8`.
56 vorhandene Textdateien wurden übernommen. Der erfolgreiche historische Lauf
41754718952 wurde über GitHub geprüft. Die bestehende Testsuite ergab zusammen
mit dem originalen v0.8.5-Paket 240 erfolgreiche Tests.

Die neue Entwicklung liegt lokal auf `atlas-v0.9`. Der Versuch, diesen Branch
bei GitHub anzulegen, scheiterte mit **HTTP 403 / Resource not accessible by
integration**. Deshalb kein erstellter Remote-Branch und kein v0.9-PR.

Keine Änderungen an vorhandenen Dateien. Insbesondere blieben Produktionscode,
Kontodaten, historische Strategien, Risikokonfiguration und produktiver Workflow
bytegleich. Regressionstest mit `V09_BASELINE_SHA256.json`; zusätzliche Prüfung
aller zuvor versionierten Dateien. Keine Analyse des versiegelten Holdouts.

## Tests

| Prüfung | Ergebnis |
|---|---|
| Bestehende Tests plus gefundene v0.8.5-Tests | 240 bestanden |
| Neue v0.9-Tests | 60 bestanden |
| Gesamtsuite nach frischer Installation | 300 bestanden, 0 fehlgeschlagen, 0 übersprungen |
| Syntax geänderter/neuer Python-Dateien | bestanden |
| Abhängigkeitsprüfung `pip check` | keine gebrochenen Abhängigkeiten |
| Streamlit-AppTest, fehlender Datenbranch | startet ohne unbehandelte Ausnahme, zeigt Warnung |
| YAML und Shell-Syntax des neuen Workflows | lokal bestanden |
| Zwei getrennte Git-Arbeitskopien | Wiederherstellung und Konfliktsperre bestanden |
| Orphan-Datenbranch statt main | lokal bestanden; main unverändert |
| Echter GitHub-v0.9-Workflow-Lauf | nicht ausgeführt, fehlender Schreibzugriff |
| Echter prospektiver Trading-Langzeittest | noch nicht gestartet |
| Entpackte Referenz mit isoliertem Prüfstarter | 300 bestanden; Git-Kontext und synthetische Testfixture separat erzeugt |
| Dreijähriger Research-Komplettlauf / neue SPA-Auswertung | in diesem Update nicht erneut ausgeführt |

Testumgebung: Python 3.12, Linux, eigene frisch angelegte virtuelle Umgebung.
Die tatsächlich installierten Versionen stehen in `requirements-v09-environment.txt`
und werden von `requirements-v09.txt` als Constraints verwendet. Keine fehlenden
Umgebungsabhängigkeiten bei den lokalen Tests.

Neue Tests prüfen Kaufbudget inklusive Gebühren, Slippage, Verkauf, Halt,
Stop/Take-Profit, Tagesverlust-/Drawdown-Sperre, doppelte oder veränderte Kerzen,
fehlende Daten, spätere Quotes, Ablaufzeiten, kein Backfill, kausale Signale,
Zustandsintegrität, Konfigurationssperren, Kostenkonsistenz, API-Ausfälle,
Coinbase-/Kraken-Antwortformate, Dashboard und Remote-Git-Konflikte.

Während der Entwicklung schlugen sechs neue Kostenvergleichstests zunächst wegen
falsch benannter Test-Erwartungsfelder fehl. Die bestehenden v0.8.5-Feldnamen und
Prozent-Einheiten wurden in den Tests korrigiert; die Gebührenformeln wurden nicht
zugunsten der Ergebnisse verändert. Danach erneut betroffene und vollständige
Suite ausgeführt. Es gibt keine verbleibenden Testfehler in der korrekt eingerichteten Testumgebung.

Die erste direkte Prüfung der entpackten Quellcode-Referenz ergab 298 bestandene
und zwei fehlgeschlagene Tests: Der unveränderte v0.8-Test erwartet Git-Metadaten,
der alte Dashboard-Test ein vorhandenes 100-Euro-Konto. Das Archiv enthält
absichtlich weder Git-Interna noch produktive Kontodaten. Der beiliegende
`verify_v09_bundle.py` erzeugt deshalb ausschließlich in einem temporären
Verzeichnis einen Git-Snapshot und eine ausdrücklich synthetische Testfixture.
Mit diesem Prüfkontext bestanden alle 300 Tests. Keine produktive Kontodatei
wurde dafür kopiert, verändert oder in das Update aufgenommen.

## Echte neue Datenprüfung — keine simulierte Performance

Am 4. November 2026 wurden öffentliche Coinbase- und Kraken-Endpunkte tatsächlich
abgerufen. Ergebnisdatei: `research_evidence/v09/market_check.json`.

| Kennzahl | Beobachteter Wert |
|---|---:|
| Gemeinsame abgeschlossene 4h-Kerzen | 206 |
| Erste Kerzenöffnung UTC | 2026-10-01 00:00 |
| Ende exklusiv UTC | 2026-11-04 08:00 |
| Median symmetrische Close-Abweichung | 0,010944 % |
| Maximale symmetrische Close-Abweichung | 0,092748 % |
| Gemeinsam ausgerichtete Kerzen dieses Ausschnitts | 100 % |
| Lücken im abgefragten Ausschnitt | 0 |
| Forward-Orders aus dieser Prüfung | 0 |

Ein erster ausführungsnaher Abruf brach wegen einer mehr als 60 Minuten alten
Schlusskerze ab. Die getrennte Nur-Lese-Prüfung erlaubte danach die Datenanalyse,
**nicht** die Handelsausführung. Beim Abruf war die Kerze rund 126 Minuten alt.
Zusätzlich fehlen noch 34 der erforderlichen 240 post-historischen Warmup-Kerzen.
Die Prüfung ist deshalb ausdrücklich `execution_eligible=false`.

Rohantworten, URLs, Abrufzeiten und Hash-Dateinamen sind im ZIP unter
`EVIDENCE_RAW` enthalten. Diese Datenprüfung ersetzt weder den historischen
Dreijahres-Crosscheck noch sämtliche dortigen Qualitätsmetriken.

## Übernommene echte historische Resultate

Das originale v0.8.5-Ergebnispaket wurde gefunden. Seine enthaltenen Dateien wurden
gegen die mitgelieferten SHA-256-Werte geprüft. Die folgende Tabelle wurde erneut
aus dessen CSV aggregiert; die zugrunde liegenden Backtests wurden für diesen
Bericht nicht noch einmal berechnet. Sie betreffen sieben bereits mehrfach
untersuchte 90-Tage-Fenster, nicht unabhängige Forward-Daten.

Kosten: 0,6 % Gebühr und 0,05 % Slippage je Fill.

| Strategie | Mittlere Netto-Rendite je Fenster | Differenz zu passiver 20%-Startallokation | Geschlossene Trades insgesamt |
|---|---:|---:|---:|
| SMA 20/50 | +0,2237 % | −3,1568 Prozentpunkte | 41 |
| EMA Trend | −0,2647 % | −3,6452 Prozentpunkte | 19 |
| Donchian 30 | −2,4295 % | −5,8101 Prozentpunkte | 70 |
| Momentum 60 | −1,9642 % | −5,3447 Prozentpunkte | 100 |

Die Grafik `historical_fee_sensitivity.png` zeigt die übernommenen Kostenszenarien.
Auch das Szenario ohne Gebühren enthält 0,05 % Slippage. Die passive Referenz
teilt die Anfangsallokation, aber nicht sämtliche dynamischen Risikoeigenschaften.
Diese Differenzen sind daher nicht automatisch risikobereinigtes Alpha.

**Kein belastbarer profitabler Vorteil nachgewiesen. Keine Strategie freigeben.**
Technische Tests und eine gute Datenübereinstimmung ändern diesen Befund nicht.

## Funktionsstand

| Bereich | Nachgewiesener Stand |
|---|---|
| Infrastruktur | vorhandener Code erhalten; neues Paket lokal getestet |
| Historische Forschung | vorhandene v0.8.4 und originale v0.8.5 integriert; Resultate explorativ |
| Strategievalidierung | keine Strategie zugelassen; Holdout weiterhin versiegelt |
| Forward-Testing | implementiert, synthetisch getestet, echte Datenprüfung durchgeführt; nicht aktiviert |
| Automatisiertes Paper-Trading | bestehendes System unverändert; neue Shadow-Automatik noch nicht auf GitHub abgenommen |
| Dashboard | HTML und Streamlit read-only vorhanden; Start getestet; kein Hosting eingerichtet |
| Echtgeldreife | ausdrücklich kein Ziel dieses Updates, keine Echtgeldfunktion |

## Nächste Prioritäten

1. Paket auf atlas-v0.9 installieren und GitHub-Testjob bestätigen.
2. Einen echten Aktivierungs- und Wiederanlauflauf mit erhaltenem Datenbranch prüfen.
3. Vor regelmäßigem Betrieb Rohdatenaufbewahrung und späteren Defaultbranch-Starter
   ausdrücklich freigeben; noch kein Merge auf main.
4. Prospektive Daten sammeln, ohne Parameter oder Kosten nachträglich zu ändern.
5. Erst bei ausreichender Beobachtungsdauer einen vorab registrierten statistischen
   Forward-Auswertungsplan umsetzen. Keine automatische Freigabe und kein Öffnen
   des historischen Holdouts.
