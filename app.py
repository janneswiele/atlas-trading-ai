from __future__ import annotations
from datetime import datetime, timedelta, timezone
import time
import pandas as pd
import streamlit as st
from data import fetch_history, TIMEFRAME_MS
from strategies import STRATEGIES
from backtest import backtest
from optimizer import run_walk_forward

st.set_page_config(page_title="Atlas Trading AI", page_icon="📈", layout="wide")
st.title("📈 Atlas Trading AI")
st.caption("Meilenstein 1 · historische Spot-Simulation · Echtgeldhandel nicht implementiert")
with st.sidebar:
    st.header("Backtest")
    exchange=st.selectbox("Datenquelle",["okx","kraken"],help="OKX wird für paginierte Historien bevorzugt. Kraken OHLC-Endpunkte können auf ein rollierendes Fenster begrenzt sein.")
    symbol=st.selectbox("Markt",["BTC/USDT","ETH/USDT","SOL/USDT"])
    timeframe=st.selectbox("Intervall",list(TIMEFRAME_MS),index=1)
    years=st.slider("Historie in Jahren",0.25,5.0,2.0,0.25)
    start_cash=st.number_input("Virtuelles Startkapital",100.0,100000.0,1000.0,100.0)
    fee_pct=st.number_input("Gebühr je Fill (%)",0.0,1.0,0.1,0.01)
    slippage_pct=st.number_input("Slippage je Fill (%)",0.0,1.0,0.05,0.01)
    chosen=st.multiselect("Strategien",STRATEGIES,default=STRATEGIES)
    run=st.button("Historische Tests starten",type="primary",use_container_width=True)

st.info("Diese Version führt historische Tests aus. Live-Paper-Trading, Optimierung und Echtgeldanbindung sind noch nicht enthalten.")
if run:
    end=int(time.time()*1000); start=end-int(years*365.25*24*60*60*1000)
    try:
        with st.spinner("Lade historische Kerzen mit Pagination …"):
            df,info=fetch_history(exchange,symbol,timeframe,start,end)
        st.session_state["df"]=df; st.session_state["info"]=info
        st.session_state["run_cfg"]={"exchange":exchange,"symbol":symbol,"timeframe":timeframe,"fee":fee_pct/100,"slippage":slippage_pct/100,"cash":start_cash,"strategies":chosen}
    except Exception as e:
        st.error(f"Datenabruf fehlgeschlagen: {e}")

if "df" in st.session_state:
    df=st.session_state["df"]; info=st.session_state["info"]; cfg=st.session_state["run_cfg"]
    if cfg["strategies"]:
        st.subheader("Historische Daten")
        a,b,c,d=st.columns(4)
        a.metric("Gültige Kerzen",f"{info['valid_candles']:,}")
        b.metric("Fehlende Intervalle",info["missing_intervals"])
        bdate=lambda v: datetime.fromtimestamp(v/1000,timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if v else "—"
        c.metric("Früheste Kerze",bdate(info["first"]))
        d.metric("Neueste Kerze",bdate(info["last"]))
        if info["warnings"]:
            for w in info["warnings"]: st.warning(w)
        if info["candles"]<300: st.warning("Historie is korter dan 300 kerzen. Ergebnisse können statistisch schwach sein.")
        st.caption(f"Quelle {info['exchange']} · {info['symbol']} · {info['timeframe']} · {info['candles']:,} Kerzen · API neu: {info['api_rows_fetched']:,} · Cache wiederverwendet: {info['cache_rows_reused']:,}")
        n=len(df); cuts=(int(n*.6),int(n*.8)); rows=[]; all_trades=[]; diagnostics=[]
        for strategy in cfg["strategies"]:
            segments={"Training":(0,cuts[0]),"Validierung":(cuts[0],cuts[1]),"Test (Holdout)":(cuts[1],n)}
            by={}
            for label,(lo,hi) in segments.items():
                # Indicators use only historical rows. Segment portfolio resets at each boundary.
                m,t,e,dg=backtest(df,strategy,cfg["cash"],cfg["fee"],cfg["slippage"],start_index=lo,end_index=hi,timeframe=cfg["timeframe"])
                by[label]=m
                if label=="Test (Holdout)":
                    t["market"]=cfg["symbol"]; all_trades.append(t)
                    state=("Keine Einstiegssignale" if dg["entry_conditions"]==0 else "Signale vorhanden, keine Ausführung" if m["trades"]==0 else "Trades simuliert")
                    diagnostics.append({"Strategie":strategy,"Status":state,"Kerzen geprüft":dg["candles_evaluated"],"Einstiegssignale":dg["entry_conditions"],"Ausstiegssignale":dg["exit_conditions"],"Risiko-Ablehnungen":dg["risk_rejections"],"Simulierte Trades":m["trades"],"Stop-Loss":dg["stop_hits"],"Take-Profit":dg["take_hits"]})
            test=by["Test (Holdout)"]
            status="Ausreichende Mindeststichprobe" if test["trades"]>=30 else "Zu wenige Trades für belastbare Einstufung"
            train=by["Training"]; val=by["Validierung"]
            rows.append({"Strategie":strategy,"Training Trades":train["trades"],"Validierung Trades":val["trades"],"Holdout Trades":test["trades"],"Holdout Trefferquote":f"{test['win_rate_pct']:.1f}%","Holdout Netto":f"{test['net_pnl']:+.2f}","Holdout Rendite":f"{test['return_pct']:+.2f}%","Buy & Hold":f"{test['buy_hold_return_pct']:+.2f}%","Max. Drawdown":f"{test['max_drawdown_pct']:.2f}%","Profit Factor":f"{test['profit_factor']:.2f}","Status":status})
        st.subheader("Holdout-Ergebnisse")
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        st.caption("Zeitaufteilung: 60% Training · 20% Validierung · 20% Holdout. Feste Startparameter, keine Optimierung. Signale am Kerzenschluss werden frühestens am nächsten Kerzen-Open ausgeführt. Positionszustand und Eigenkapital starten je Segment neu; die Indikator-Warm-up-Daten stammen ausschließlich aus der Vergangenheit.")
        with st.expander("Erweiterte Forschung: Walk-forward-Parametersuche"):
            st.write("Je Zeitfenster werden begrenzte Parameterkombinationen nur auf älteren Trainingsdaten gerankt und danach auf dem folgenden, getrennten Zeitfenster geprüft. Diese Auswertung wählt keine Strategie für den Live- oder Paper-Betrieb aus.")
            folds=st.slider("Walk-forward-Fenster",2,6,4)
            if st.button("Walk-forward-Tests berechnen"):
                wf=[]
                with st.spinner("Teste Parameter je historischem Zeitfenster …"):
                    for strategy in cfg["strategies"]:
                        try:
                            summary=run_walk_forward(df,strategy,cfg["cash"],cfg["fee"],cfg["slippage"],cfg["timeframe"],folds=folds)
                            wf.append({"Strategie":strategy,"Ausgewertete Fenster":f"{summary['folds_evaluated']}/{folds}","OOS-Trades":summary["total_oos_trades"],"Ø OOS-Rendite":None if summary["mean_oos_return_pct"] is None else round(summary["mean_oos_return_pct"],2),"schlechtester OOS-Drawdown":None if summary["worst_oos_drawdown_pct"] is None else round(summary["worst_oos_drawdown_pct"],2)})
                            st.dataframe(pd.DataFrame([{**r,"Parameter im Fold":r["params"]} for r in summary["fold_results"]]),hide_index=True,use_container_width=True)
                        except Exception as exc:
                            st.warning(f"{strategy}: {exc}")
                if wf: st.dataframe(pd.DataFrame(wf),hide_index=True,use_container_width=True)
        st.subheader("Diagnose")
        st.dataframe(pd.DataFrame(diagnostics),hide_index=True,use_container_width=True)
        if all_trades and len(all_trades[0]):
            trades=pd.concat(all_trades,ignore_index=True)
            st.subheader("Holdout-Trades")
            st.dataframe(trades,hide_index=True,use_container_width=True)
            st.download_button("Trades als CSV herunterladen",trades.to_csv(index=False),file_name="atlas_holdout_trades.csv",mime="text/csv")
        st.line_chart(df.set_index(pd.to_datetime(df.timestamp,unit="ms",utc=True)).close.rename("Schlusskurs"))
        st.caption("Noch offene Forschungsgrenzen: Parameteroptimierung, Walk-forward-Validierung, ausführliche Marktregimeanalyse und permanentes Paper-Trading kommen in Folgemeilensteinen. Keine Strategieauswahl wird als Gewinnversprechen dargestellt.")
    else:
        st.warning("Wähle mindestens eine Strategie aus und starte die Tests erneut.")

# Atlas: automatisches Paper-Trading-Konto
import json
from urllib.request import urlopen

st.divider()
st.subheader("🤖 Automatischer Paper-Bot")

try:
    state_url = (
        "https://raw.githubusercontent.com/"
        "janneswiele/atlas-trading-ai/main/paper_state.json"
    )
    with urlopen(state_url, timeout=10) as response:
        paper = json.load(response)

    col1, col2, col3 = st.columns(3)
    col1.metric("Kontowert", f"{paper['equity_eur']:.2f} €")
    col2.metric("Guthaben", f"{paper['cash_eur']:.2f} €")
    col3.metric("BTC-Bestand", f"{paper['btc']:.8f}")

    st.info(f"Letzte Entscheidung: {paper['last_result']}")
    st.caption(
        f"Letzte Prüfung (UTC): {paper['last_checked_utc']}"
    )
except Exception as exc:
    st.warning(f"Paper-Konto derzeit nicht abrufbar: {exc}")
