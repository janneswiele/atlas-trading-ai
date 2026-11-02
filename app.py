import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from engine import (
    SYMBOLS, STRATEGIES, fetch_ohlcv, evaluate_strategies,
    get_portfolio, run_paper_cycle, get_trade_history, reset_paper_account
)

st.set_page_config(page_title="Atlas Trading AI", page_icon="📈", layout="wide")
st.title("📈 Atlas Trading AI")
st.caption("Automatisiertes Krypto-Paper-Trading · Keine Echtgeld-Orders")

with st.sidebar:
    st.header("Einstellungen")
    symbols = st.multiselect("Märkte", SYMBOLS, default=SYMBOLS[:3])
    timeframe = st.selectbox("Zeiteinheit", ["15m", "1h", "4h"], index=1)
    initial_cash = st.number_input("Startkapital (virtuell, €)", min_value=10.0, max_value=10000.0, value=100.0, step=10.0)
    fee_pct = st.number_input("Gebühr je Order (%)", min_value=0.0, max_value=2.0, value=0.1, step=0.05)
    st.caption("Demo: öffentliche Kursdaten, keine Börsen-API-Schlüssel erforderlich.")
    if st.button("Paper-Konto zurücksetzen", type="secondary"):
        reset_paper_account(float(initial_cash))
        st.success("Paper-Konto zurückgesetzt.")

if not symbols:
    st.warning("Bitte mindestens einen Markt auswählen.")
    st.stop()

fee_rate = fee_pct / 100.0

# Initialisiere das virtuelle Konto einmalig.
portfolio = get_portfolio(float(initial_cash))

st.subheader("Marktdaten & Strategie-Auswahl")
market_rows = []
frames = {}
errors = []
for symbol in symbols:
    try:
        df = fetch_ohlcv(symbol, timeframe, limit=500)
        frames[symbol] = df
        results, winner = evaluate_strategies(df, fee_rate)
        market_rows.append({
            "Markt": symbol,
            "Letzter Kurs": round(float(df["close"].iloc[-1]), 4),
            "Beste Strategie": winner["strategy"] if winner else "Keine valide Strategie",
            "Validierungsrendite": f'{winner["test_return_pct"]:.2f}%' if winner else "—",
            "Trades (Test)": winner["test_trades"] if winner else 0,
            "Max. Drawdown": f'{winner["test_drawdown_pct"]:.2f}%' if winner else "—",
        })
    except Exception as exc:
        errors.append(f"{symbol}: {exc}")

if errors:
    for err in errors:
        st.warning(err)

if market_rows:
    st.dataframe(pd.DataFrame(market_rows), use_container_width=True, hide_index=True)

st.divider()
st.subheader("Paper-Trading")
st.write("Der Bot verarbeitet abgeschlossene Kerzen, nutzt die nach Out-of-sample-Tests beste Strategie und simuliert Käufe/Verkäufe. Pro Markt wird höchstens eine Position gehalten.")

col1, col2 = st.columns([1, 3])
with col1:
    run_now = st.button("▶ Paper-Bot jetzt ausführen", type="primary", use_container_width=True)
with col2:
    st.caption("Die Ausführung erfolgt auf Knopfdruck oder beim automatischen Seiten-Refresh, sofern aktiviert.")

auto = st.toggle("Automatisch alle 60 Sekunden prüfen", value=False)
if auto:
    st_autorefresh(interval=60_000, key="atlas_auto_refresh")
if run_now or auto:
    actions = []
    for symbol, df in frames.items():
        try:
            _, winner = evaluate_strategies(df, fee_rate)
            if winner:
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
        st.info("Keine neue Handelsaktion. Der Bot wartet auf ein Signal oder eine neue abgeschlossene Kerze.")

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

st.caption("Wichtige Hinweise: Backtests sind keine Gewinnprognose. Historische Ergebnisse können sich nicht wiederholen. Gebühren, Slippage und Ausführungsabweichungen können reale Ergebnisse verschlechtern. Echtgeldhandel ist in dieser Version technisch deaktiviert.")
