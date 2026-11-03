"""Read-only paper account UI; never places trades or changes the ledger."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
import pandas as pd
import streamlit as st
from paper import migrate

@st.cache_data(ttl=60)
def read_document(name, optional=False):
    ref = os.getenv("ATLAS_STATE_REF", "main")
    if os.getenv("ATLAS_LOCAL_STATE") == "1":
        p = Path(name)
        if optional and not p.exists(): return None
        return json.loads(p.read_text())
    # Read all files from one immutable commit, avoiding a mixed ledger/status snapshot.
    if name == "_revision":
        with urlopen("https://api.github.com/repos/janneswiele/atlas-trading-ai/commits/"+ref, timeout=10) as r:
            return json.load(r)["sha"]
    revision = read_document("_revision")
    url = f"https://raw.githubusercontent.com/janneswiele/atlas-trading-ai/{revision}/{name}"
    try:
        with urlopen(url, timeout=10) as r: return json.load(r)
    except HTTPError as exc:
        if optional and exc.code == 404: return None
        raise


def render():
    st.caption("PAPER-KONTO · BTC/EUR · echte gespeicherte Simulation, keine Echtgeldorders")
    if st.button("Kontostand aktualisieren"):
        st.cache_data.clear()
    try:
        raw = read_document("paper_state.json"); s = migrate(raw)
        status = read_document("paper_status.json", True)
        report = read_document("strategy_report.json", True)
        config = read_document("paper_config.json", True)
    except Exception as exc:
        st.error(f"Konto nicht verlässlich lesbar: {type(exc).__name__}. Keine Ersatzwerte angezeigt.")
        return
    price = s.get("last_price_eur")
    equity = s["cash_eur"] + s["btc"]*price if price else s.get("equity_eur")
    a,b = st.columns(2)
    a.metric("Virtueller Kontowert", f"{equity:.2f} €" if equity is not None else "Unbekannt")
    b.metric("Verfügbares Guthaben",f"{s['cash_eur']:.2f} €")
    a,b = st.columns(2)
    a.metric("Offene Positionen", int(s["btc"]>0)); b.metric("Letzter Bewertungskurs", f"{price:,.2f} €" if price else "—")
    last = s.get("last_success_utc", s.get("last_checked_utc"))
    stale = not last or (datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds() > 6*3600
    if status and status["status"] == "failed": st.error("Letzter Versuch fehlgeschlagen; Konto zeigt den letzten gespeicherten Stand.")
    elif stale: st.warning("Automatik überfällig / Status veraltet. GitHub Actions prüfen.")
    else: st.success("Letzter gespeicherter Zyklus aktuell. Kein Nachweis für einen dauerhaft laufenden Server.")
    if config and not config["trading_enabled"]: st.warning("Handel manuell deaktiviert – auch Ausstiege pausieren.")
    if s.get("halted"): st.error("Verlustgrenze erreicht: neue Einstiege gesperrt.")
    st.info(s.get("last_result", "Keine Entscheidung gespeichert"))
    st.write("**Strategie:**", s.get("strategy", "—"))
    st.caption(f"Letzter erfolgreicher neuer Kerzenzyklus: {last or 'unbekannt'} · UTC")
    st.caption("4-Stunden-Prüfungen können verspätet sein oder ausfallen. Simulierte Stops werden erst beim nächsten gültigen Lauf verarbeitet.")
    overview, performance, history, research = st.tabs(["Position", "Performance", "Trades & Entscheidungen", "Strategiefreigabe"])
    with overview:
        if s["btc"]:
            st.dataframe(pd.DataFrame([{"Markt":"BTC/EUR","BTC":s["btc"],"Einstieg €":s["entry_eur"],"Kostenbasis €":s["cost_basis_eur"],"Strategie":s["position_strategy"]}]), hide_index=True)
        else: st.write("Keine offene Position.")
    with performance:
        st.caption(s["accounting_note"])
        trades = pd.DataFrame(s["trades"])
        closed = [t for t in s["trades"] if t["side"] == "SELL" and t["net_pnl_eur"] is not None]
        win = sum(t["net_pnl_eur"]>0 for t in closed)/len(closed)*100 if closed else None
        unreal = s["btc"]*price-s["cost_basis_eur"] if price and s["cost_basis_eur"] is not None else None
        a,b = st.columns(2)
        a.metric("Realisierter G/V seit v0.4", f"{s['realized_pnl_eur']:+.2f} €")
        b.metric("Unrealisierter G/V vor Verkaufskosten",f"{unreal:+.2f} €" if unreal is not None else "Unbekannt")
        a,b = st.columns(2)
        a.metric("Ausführungen / geschlossene Trades", f"{len(trades)} / {len(closed)}")
        b.metric("Trefferquote",f"{win:.1f}%" if win is not None else "—")
        st.metric("Gebühren seit v0.4", f"{s['fees_eur']:.4f} €")
        curve = pd.DataFrame(s["equity_history"])
        if not curve.empty:
            vals = pd.concat([pd.Series([s['benchmark']['initial_equity']]),curve.equity_eur],ignore_index=True)
            st.metric("Max. beobachteter Drawdown",f"{(vals/vals.cummax()-1).min()*100:.2f}%")
            curve["time"] = pd.to_datetime(curve.time)
            st.line_chart(curve.set_index("time")[["equity_eur","buy_hold_eur"]])
            st.caption("Buy & Hold startet mit der ersten v0.4-Bewertung, nach modellierten Kauf-/Verkaufskosten. Zwischenläufe sind unbekannt.")
        else: st.write("Noch keine v0.4-Kontowertkurve. Frühere Werte werden nicht erfunden.")
    with history:
        if s["trades"]:
            table = pd.DataFrame(s["trades"])
            st.dataframe(table,hide_index=True)
            st.download_button("Trade-Historie herunterladen",table.to_csv(index=False),"atlas-paper-trades.csv")
        else: st.write("Keine v0.4-Ausführungen gespeichert.")
        st.caption("Frühere CSV-Trades bleiben unverändert im Repository; sie werden nicht nachträglich als v0.4-Ergebnisse gezählt.")
        if s["decisions"]: st.dataframe(pd.DataFrame(s["decisions"][-100:]), hide_index=True)
    with research:
        if not report: st.warning("Keine geprüfte Strategie hinterlegt. v0.4 eröffnet keine neuen Positionen.")
        else:
            st.write("Im Forschungsbericht ausgewählt:", report["selected"] or "Keine")
            st.caption("Der Bericht allein beweist keine aktuelle Freigabe: Kosten, Codeversion und Ablaufdatum werden bei jedem Zyklus erneut geprüft.")
            st.dataframe(pd.DataFrame([{"Strategie":r["strategy"],"Ablehnung":"; ".join(r["reasons"]) or "Training/Validierung bestanden", "Validierung Rendite %":r["validation"]["return_pct"]} for r in report["candidates"]]),hide_index=True)
            st.json(report)
