# Atlas Trading AI v0.9 — geprüfter Forschungsstand

Stand: 4. November 2026. Basis: `atlas-v0.8`, Commit
`6fd559561ac2acace285b67c01e46ab8101d7be8` (v0.8.4).

**Status: lokal getestetes Sammelupdate, noch nicht auf GitHub installiert.
Keine Strategie freigegeben. Kein Nachweis eines profitablen Trading-Vorteils.**
Der Schreibversuch für den neuen GitHub-Branch wurde mit HTTP 403 abgewiesen.
`main`, der produktive Workflow, `paper.py`, `paper_config.json` und
`paper_state.json` wurden nicht verändert. Der neue lokale Branch heißt `atlas-v0.9`.

## Tatsächlicher Umfang

- Vorhandene v0.5–v0.8.4-Module bleiben bytegleich; SHA-256-Regressionstest.
- Gefundenen v0.8.5-Quellcode samt Tests und Gebührenbericht integriert.
  Keine behauptete Rekonstruktion oder Neuinstallation auf GitHub.
- Neue isolierte Forward-Engine mit vier unabhängigen 100-Euro-Shadow-Konten.
- Bestehende SMA-, EMA-, Donchian- und Momentum-Signalfunktionen wiederverwendet.
- Geschlossene 4h-Kerzen aus vollständigen Coinbase-Stundenkerzen; Kraken-Kontrolle.
- Entscheidung wird gespeichert, bevor ein späterer öffentlicher Kurs abgefragt wird.
- Kauf zum beobachteten Ask plus Slippage, Verkauf zum Bid minus Slippage;
  Gebühren getrennt, keine rückwirkenden Fills oder echten Orders.
- Ereigniskette, Zustandsprüfsumme, Code-/Konfigurationsfingerprint, atomare Dateien,
  lokale Sperre und separater Git-Datenbranch mit normalen Fast-forward-Pushes.
- Dunkles HTML-Dashboard und optionales, ausschließlich lesendes Streamlit-Dashboard.
- Eigener Test-/Shadow-Workflow; Produktion bleibt unverändert.

Das ist noch keine vollständig abgenommene autonome Plattform. Insbesondere ein
realer GitHub-v0.9-End-to-End-Lauf und ein prospektiver Performance-Nachweis fehlen.

## Architektur und Schnittstellen

| Datei | Verantwortung |
|---|---|
| `atlas09/core.py` | Eingangsprüfungen, eingefrorene Regeln, Entscheidungen, virtuelle Fills, Konten, Hashkette |
| `atlas09/market.py` | öffentliche GET-Endpunkte, Rohantworten, 1h→4h, unabhängige Kontrolle |
| `atlas09/persist.py` | begrenzte Git-Schreibmenge, Datenbranch, Konfliktabbruch |
| `atlas09/report.py` | read-only HTML-Momentaufnahme |
| `atlas_v09.py` | explizite Aktivierung, Wiederanlauf, Transaktionsreihenfolge, Fehler |
| `atlas_dashboard_v09.py` | Streamlit-Ansicht von Datenbranch und historischen Ergebnissen |
| `atlas_v085.py` | unveränderte historische Gebühren-/Break-even-Diagnostik |
| `generate_v09_report.py` | Diagramme aus archivierten Ergebnissen und echten beobachteten Preisen |

Es gibt keine automatische Strategieauswahl und keine Order-API. Historische
Ausführung bleibt unverändert, damit die Baselines nicht durch eine neue
Kostenberechnung verschoben werden. Die neue Forward-Abrechnung hat eine zentrale
Fill-Funktion; sechs Kosten-Regressionstests vergleichen sie mit v0.8.5.

## Eingefrorenes Forward-Protokoll

1. `enabled=false` ist der Lieferzustand. Aktivierung ist ein separater Schritt.
2. Tatsächlichen Aktivierungszeitpunkt und Quellcodehash speichern. Vorherige
   Kerzen dienen ausschließlich dem Warmup, nie als Forward-Trades.
3. Alle Kerzen vor **2026-10-01 00:00 UTC** bleiben für v0.9 verboten. Das ist das
   Ende der bisherigen historischen Stichprobe, nicht ihr Holdout-Anfang.
   Dadurch wird auch der gesamte historische Holdout vom Warmup ausgeschlossen.
4. 240 vollständige, zusammenhängende 4h-Kerzen werden benötigt. Das entspricht
   40 Tagen; am 4. November standen erst 206 zur Verfügung. Frühestens am
   10. November 2026 wäre dieser Warmup bei vollständigen Daten erfüllt.
5. Die feste rollende 240-Kerzen-Initialisierung ist Teil des neuen Protokolls.
   Sie ist nicht identisch mit den längeren historischen Warmup-Fenstern.
   Dieselben Signalparameter bedeuten deshalb keine identischen Testbedingungen.
6. Letzter Kerzenschluss höchstens 60 Minuten alt. Ältere Prüfungen werden
   gesperrt. Verpasste Kerzen werden gezählt, niemals nachträglich gehandelt.
7. Beide Börsen müssen denselben verfügbaren Zeitraster abdecken; maximale
   symmetrische Close-Abweichung 1,5 %, Median höchstens 0,25 %.
   Dies ist eine lokale Forward-Prüfung, kein Ersatz für alle historischen v0.8-Gates.
8. Entscheidung mit eindeutiger Ereignisnummer und Timestamp speichern. Mit
   `--git-ledger` wird sie vor dem Kursabruf zum Datenbranch gepusht.
9. Ein neuer Coinbase-Ticker muss einen Trade-Zeitstempel nach der Entscheidung
   und einen gültigen Bid/Ask enthalten. Bis zu drei Abfragen, keine erfundenen
   Kurse, maximal 1 % Spread. Quote maximal 30 Sekunden alt.
10. Entscheidung verfällt nach spätestens fünf Minuten und spätestens 60 Minuten
    nach Kerzenschluss. Abgelaufene Entscheidungen erzeugen keine Fills.
11. Ein virtueller Fill gilt nur als dauerhaftes Forschungsergebnis, wenn der
    aktualisierte Zustand erfolgreich im Datenbranch gespeichert wurde.
12. Keine Änderung eingefrorener Parameter oder des Engine-Codes während einer
    aktivierten Studie. Ein neuer Entwicklungsstand benötigt eine separat
    registrierte Studie; die aktuelle Version bietet bewusst keinen Reset-Knopf.

Der passive Vergleich beginnt beim ersten gültigen Bewertungszeitpunkt mit
20 % BTC-Anfangsallokation, denselben Ausführungskosten und 80 % Cash. Er besitzt
keine Strategie-Stops und ist daher **ein Kontextvergleich mit gleicher
Anfangsallokation, kein garantiert risikogleicher Alpha-Nachweis**.

## Risiko und Kosten

Aus dem Repository verifiziert: maximal 20 % des freien Guthabens je Einstieg,
eine Long-Position pro Konto, 2 % Stop, 4 % Take-Profit, 3 % Tagesverlustlimit,
10 % Maximal-Drawdown, keine Shorts, kein Hebel. Unverändert geschützt.

Die produktive Konfiguration enthält **0,1 % Gebühr** und **0,05 % Slippage**.
Die neue Forschungsstudie verwendet ausdrücklich **0,6 % Gebührenannahme** und
**0,05 % zusätzliche Slippage je Fill**. Dies ist kein aktueller oder persönlicher
Börsentarif. Spread entsteht zusätzlich durch Bid/Ask. Historische v0.8.5-Labels
sind archivierte Bezeichnungen und keine neu überprüften Gebührenangebote.

Zusätzliche konservative Regeln: Kill Switch; Circuit Breaker nach drei
aufeinanderfolgenden fehlgeschlagenen Zyklen; dauerhafte Kontosperre nach
Tagesverlust-/Drawdown-Verletzung. Diese Kontosperre wird nicht stillschweigend am
nächsten Tag aufgehoben. Das ist eine dokumentierte zusätzliche Schutzregel des
Forward-Protokolls; historische Baselines bleiben unverändert.

**Stops werden nur bei gültigen Prüfungen verarbeitet.** Bei Datenfehlern, Kill
Switch oder verpassten Prüfungen können auch virtuelle offene Positionen nicht
zu einem aktuellen Kurs verarbeitet werden. Preisgrenzen sind keine garantierten
Ausführungspreise; Verluste können Limits überschreiten. Kein 24/7-Handelsserver.

## Persistenz und Automatik

`atlas-v0.9-data` enthält ausschließlich `ledger.json`, `quality.json` und
`dashboard.html`. Keine Vermischung mit dem produktiven Paper-Konto. Der Workflow
sperrt parallele Läufe, lädt den existierenden Zustand, prüft Integrität und Code,
speichert Entscheidungen vor dem Fill und pusht ohne Force oder Rebase.
Ein konkurrierender Push oder fehlender Zustand stoppt den Lauf. Explizite
Aktivierung kann nur einen noch nicht existierenden Datenbranch initialisieren.

Die Hashkette erkennt versehentliche Änderungen. Sie ist **keine digitale Signatur**
und schützt nicht vor einem Repository-Eigentümer, der Daten und Hashes gemeinsam
umschreibt. Git-Historie und eingeschränkte Schreibrechte sind zusätzliche,
aber keine absolute Manipulationssicherheit. Der Datenbranch muss erhalten bleiben.

Rohantworten werden mit SHA-256-Dateinamen protokolliert und für 30 Tage als
Actions-Artefakte aufgehoben. Die Kerzen-Hashes und Ausführungsdaten bleiben im
Ledger. Für eine längerfristig vollständige Rohdaten-Auditspur müssen diese
Artefakte zusätzlich archiviert werden. Kein unbegrenztes Rohdatenarchiv im Repo.
Der wachsende JSON-/Git-Verlauf ist für ein kleines Forschungsprojekt praktikabel;
Langzeitbetrieb benötigt später ein versioniertes Archivierungsverfahren.

Der Workflow enthält `17 */4 * * *`, aber **GitHub aktiviert Zeitpläne nur auf dem
Defaultbranch**. Solange `main` unverändert bleibt, startet diese Installation
nicht automatisch alle vier Stunden. Auch der Dispatch-Schalter kann fehlen,
solange der Workflow noch nicht auf dem Defaultbranch registriert ist.
Der sofort nutzbare Weg sind gezielte Commits der Befehlsdatei auf `atlas-v0.9`.
Eine spätere Aufnahme nur des freigegebenen Start-Workflows auf dem Defaultbranch
ist ein separater Review-/Freigabeschritt. In diesem Update wird nichts gemergt.

## Nachweise und Grenzen

Siehe `V09_PRUEFBERICHT.md` für Zahlen und Teststatus. Die tatsächliche lokale
Marktprüfung umfasst nur 206 neue Kerzen. Kein neuer dreijähriger Research-Lauf,
kein neuer Bootstrap-/SPA-Nachweis, keine Holdout-Auswertung und keine echten
Forward-Fills wurden behauptet oder erzeugt. Bestehende statistische Verfahren
und historische Ergebnisse wurden übernommen, nicht als neu unabhängig bestätigt.

Noch offen: echter GitHub-Lauf und Wiederanlauf; operative Rohdatenarchivierung;
langfristige prospektive Beobachtungen; Weiterentwicklung der Statistik speziell
für unregelmäßige Forward-Prüfzeitpunkte; umfangreicheres interaktives Dashboard.
Keine automatische Freigabe und kein Machine-Learning-Parametersuchen.

## Quellen für implementierte Infrastruktur

- Coinbase Candles: https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles
- Coinbase Ticker: https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker
- GitHub Ereignisse/Defaultbranch: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Bestehender bestätigter v0.8.4-Lauf: https://github.com/janneswiele/atlas-trading-ai/actions/runs/41754718952

### Tagesverlust-Referenz und Überwachungslücken

Der Tageswechsel verwendet UTC. Die Tagesreferenz ist der zuletzt gespeicherte
Kontowert beim ersten neuen Prüfzeitpunkt des Tages, kein erfundener
Mitternachtskurs. Bei mehrtägigen Unterbrechungen gibt es keine rekonstruierte
Tageskurve. Die gespeicherten Drawdowns beruhen auf beobachteten Prüfzeitpunkten
und können zwischenzeitliche größere Drawdowns nicht abbilden.
