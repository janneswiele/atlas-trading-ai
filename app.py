"""Atlas Trading AI — Paper-Trading-Dashboard mit Backtest-Diagnose.

Nur die Dashboard-Datei ersetzen. Die bestehende engine.py mit Kraken-Konfiguration
bleibt unverändert.
"""

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from engine import (
    SYMBOLS,
    STRATEGIES,
    evaluate_strategies,
    fetch_ohlcv,
    get_portfolio,
    get_trade_history,
    reset_paper_account,
    run_paper_cycle,
)

MIN_TRADES = 3
MIN_RETURN_PCT = 0.0
MAX_DRAWDOWN_PCT = -15.0
MIN_PROFIT_FACTOR = 1.05


def rejection_reasons(result):
    """Spiegelt die Auswahlfilter aus engine.evaluate_strategies wider."""
    reasons = []
    trades = int(result["test_trades"])
    ret = float(result["test_return_pct"])
    dd = float(result["test_drawdown_pct"])
    pf = float(result["profit_factor"])
    if trades < MIN_TRADES:
        reasons.append(f"Zu wenige Trades ({trades}/{MIN_TRADES})")
    if ret <= MIN_RETURN_PCT:
        reasons.append(f"Testrendite nicht positiv ({ret:+.2f} %)")
    if dd <= MAX_DRAWDOWN_PCT:
        reasons.append(f"Drawdown zu hoch ({dd:.2f} %)")
    if pf <= MIN_PROFIT_FACTOR:
        reasons.append(f"Profit-Faktor zu niedrig ({pf:.2f})")
    return reasons


st.set_page_config(page_title="Atlas Trading AI", page_icon="📈", layout="wide")
st.title("📈 Atlas Trading AI")
st.caption("Automatisiertes Krypto-Paper-Trading · Keine Echtgeld-Orders")

with st.sidebar:
    st.header("Einstellungen")
    symbols = st.multiselect("Märkte", SYMBOLS, default=SYMBOLS[:3])
    timeframe = st.selectbox("Zeiteinheit", ["15m", "1h", "4h"], index=1)
    initial_cash = st.number_input(
        "Startkapital (virtuell, €)", min_value=10.0, max_value=10000.0,
        value=100.0, step=10.0,
    )
    fee_pct = st.number_input(
        "Gebühr je Order (%)", min_value=0.0, max_value=2.0,
        value=0.1, step=0.05,
    )
    st.caption("Demo: öffentliche Kursdaten, keine Börsen-API-Schlüssel erforderlich.")
    if st.button("Paper-Konto zurücksetzen", type="secondary"):
        reset_paper_account(float(initial_cash))
        st.success("Paper-Konto zurückgesetzt.")

if not symbols:
    st.warning("Bitte mindestens einen Markt auswählen.")
    st.stop()

fee_rate = fee_pct / 100.0
get_portfolio(float(initial_cash))

st.subheader("Marktdaten & Strategie-Auswahl")
market_rows = []
diagnostic_rows = []
frames = {}
winners = {}
errors = []

for symbol in symbols:
    try:
        df = fetch_ohlcv(symbol, timeframe, limit=500)
        frames[symbol] = df
        results, winner = evaluate_strategies(df, fee_rate)
        winners[symbol] = winner
        market_rows.append({
            "Markt": symbol,
            "Letzter Kurs": round(float(df["close"].iloc[-1]), 4),
            "Beste Strategie": winner["strategy"] if winner else "Keine valide Strategie",
            "Validierungsrendite": f'{winner["test_return_pct"]:+.2f} %' if winner else "—",
            "Trades (Test)": winner["test_trades"] if winner else 0,
            "Max. Drawdown": f'{winner["test_drawdown_pct"]:.2f} %' if winner else "—",
        })
        for result in results:
            reasons = rejection_reasons(result)
            diagnostic_rows.append({
                "Markt": symbol,
                "Strategie": result["strategy"],
                "Status": "Zugelassen" if not reasons else "Abgelehnt",
                "Rendite (%)": round(float(result["test_return_pct"]), 2),
                "Trades": int(result["test_trades"]),
                "Trefferquote (%)": round(float(result["win_rate_pct"]), 1),
                "Max. Drawdown (%)": round(float(result["test_drawdown_pct"]), 2),
                "Profit-Faktor": round(float(result["profit_factor"]), 2),
                "Ablehnungsgrund": "—" if not reasons else "; ".join(reasons),
            })
    except Exception as exc:
        errors.append(f"{symbol}: {exc}")

for err in errors:
    st.warning(err)
if market_rows:
    st.dataframe(pd.DataFrame(market_rows), use_container_width=True, hide_index=True)

st.subheader("Backtest-Diagnose")
st.write(
    "Hier siehst du **alle getesteten Strategien**, auch die abgelehnten. "
    "So erkennen wir, ob zu wenige Trades, negative Rendite, Drawdown "
    "oder Profit-Faktor die Freigabe verhindern."
)
if diagnostic_rows:
    st.dataframe(pd.DataFrame(diagnostic_rows), use_container_width=True, hide_index=True)
    st.caption(
        "Testfenster: ungefähr die letzten 30 % von maximal 500 geladenen Kerzen je Markt. "
        "Eine am Testende offene Position wird im bisherigen Backtest als Trade "
        "mitbewertet; dies ist eine Einschränkung, die wir später korrigieren sollten. "
        "Diese Ergebnisse sind keine Gewinnprognose."
    )
    if not any(winner is not None for winner in winners.values()):
        st.info(
            "Keine Strategie erfüllt aktuell alle Filter. "
            "Der Bot eröffnet deshalb bewusst keine neue Position. "
            "Das bedeutet nicht, dass die Handelsfunktion defekt ist."
        )
else:
    st.info("Noch keine Backtest-Ergebnisse verfügbar.")

with st.expander("Welche Regeln muss eine Strategie erfüllen?"):
    st.write(
        "Mindestens **3 Trades**, **positive Testrendite**, "
        "**maximaler Drawdown besser als −15 %** und "
        "**Profit-Faktor größer als 1,05**. "
        "Die Regeln wurden für diese Diagnose nicht verändert."
    )

st.divider()
st.subheader("Paper-Trading")
st.write(
    "Der Bot verarbeitet abgeschlossene Kerzen, nutzt die nach den Tests beste "
    "zugelassene Strategie und simuliert Käufe/Verkäufe. "
    "Pro Markt wird höchstens eine Position gehalten."
)
col1, col2 = st.columns([1, 3])
with col1:
    run_now = st.button("▶ Paper-Bot jetzt ausführen", type="primary", use_container_width=True)
with col2:
    st.caption(
        "Ausführung auf Knopfdruck oder bei automatischem Seiten-Refresh, sofern aktiviert. "
        "Eine dauerhaft laufende Hintergrund-Ausführung bietet diese Demo nicht."
    )
auto = st.toggle("Automatisch alle 60 Sekunden prüfen", value=False)
if auto:
    st_autorefresh(interval=60_000, key="atlas_auto_refresh")

if run_now or auto:
    actions = []
    eligible_count = 0
    for symbol, df in frames.items():
        winner = winners.get(symbol)
        if winner is None:
            continue
        eligible_count += 1
        try:
            action = run_paper_cycle(
                symbol=symbol,
                df=df,
                strategy_name=winner["strategy"],
                fee_rate=fee_rate,
                initial_cash=float(initial_cash),
            )
            if action:
                actions.append(f"{symbol}: {action}")
        except Exception as exc:
            st.error(f"Paper-Trading-Fehler bei {symbol}: {exc}")
    if actions:
        for action in actions:
            st.success(action)
    elif run_now:
        if eligible_count == 0:
            st.info("Kein Kauf: Keine Strategie wurde im Backtest zugelassen. Siehe Backtest-Diagnose oben.")
        else:
            st.info("Keine neue Handelsaktion: Aktuell fehlt ein Einstiegssignal oder die Kerze wurde bereits verarbeitet.")

portfolio = get_portfolio(float(initial_cash))
m1, m2, m3, m4 = st.columns(4)
m1.metric("Virtuelles Guthaben", f'{portfolio["cash"]:.2f} €')
m2.metric("Offene Positionen", str(portfolio["open_positions"]))
m3.metric("Realisierter Gewinn/Verlust", f'{portfolio["realized_pnl"]:+.2f} €')
m4.metric("Kontowert inkl. Positionen", f'{portfolio["equity"]:.2f} €')
if portfolio["positions"]:
    st.markdown("**Offene Positionen**")
    st.dataframe(pd.DataFrame(portfolio["positions"]), use_container_width=True, hide_index=True)

st.divider()
st.subheader("Trade-Verlauf")
history = get_trade_history()
if history:
    st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
else:
    st.info("Noch keine simulierten Trades.")
st.caption(
    "Wichtige Hinweise: Backtests sind keine Gewinnprognose. "
    "Historische Ergebnisse können sich nicht wiederholen. "
    "Gebühren, Slippage und Ausführungsabweichungen können reale Ergebnisse verschlechtern. "
    "Echtgeldhandel ist in dieser Version technisch deaktiviert."
)
