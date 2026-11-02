"""Atlas Trading AI 0.3 dashboard. Both app.py and engine.py must be updated together."""

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from engine import (
    HISTORY_LIMIT,
    SYMBOLS,
    STRATEGIES,
    evaluate_strategies,
    fetch_ohlcv,
    get_portfolio,
    get_trade_history,
    reset_paper_account,
    run_paper_cycle,
)

st.set_page_config(page_title="Atlas Trading AI 0.3", page_icon="📈", layout="wide")
st.title("📈 Atlas Trading AI")
st.caption("Version 0.3 · Kraken-Marktdaten · Historische Strategieprüfung · Nur Paper-Trading")

with st.sidebar:
    st.header("Einstellungen")
    symbols = st.multiselect("Märkte", SYMBOLS, default=SYMBOLS)
    timeframe = st.selectbox("Zeiteinheit", ["15m", "1h", "4h"], index=1)
    initial_cash = st.number_input("Startkapital (virtuell, €)", 10.0, 10000.0, 100.0, 10.0)
    fee_pct = st.number_input("Gebühr je Order (%)", 0.0, 2.0, 0.1, 0.05)
    st.caption("Marktdaten von Kraken · Keine API-Schlüssel oder echten Orders")
    if st.button("Paper-Konto zurücksetzen", type="secondary"):
        reset_paper_account(float(initial_cash))
        st.success("Paper-Konto zurückgesetzt.")
    st.caption("Hinweis: Auf Streamlit Community Cloud können Paper-Daten bei Neustarts verloren gehen.")

if not symbols:
    st.warning("Bitte mindestens einen Markt auswählen.")
    st.stop()

fee_rate = float(fee_pct) / 100.0


@st.cache_data(ttl=90, show_spinner=False)
def cached_prices(symbol, timeframe, limit):
    return fetch_ohlcv(symbol, timeframe, limit)


st.subheader("Marktdaten & Strategie-Auswahl")
st.caption(
    "Je Markt maximal 720 Kerzen von Kraken (die jüngste unvollständige Kerze wird entfernt). "
    "Zeitliche Aufteilung: 40 % Training · 40 % Validierung · 20 % Holdout. "
    "Auswahl ausschließlich nach Validierung; der Holdout wird nur berichtet."
)

market_rows, diagnostic_rows, prices, frames, winners, errors = [], [], {}, {}, {}, []
for symbol in symbols:
    try:
        df = cached_prices(symbol, timeframe, HISTORY_LIMIT)
        frames[symbol] = df
        prices[symbol] = float(df["close"].iloc[-1])
        results, winner = evaluate_strategies(df, fee_rate)
        winners[symbol] = winner
        market_rows.append({
            "Markt": symbol,
            "Letzter Schlusskurs (€)": round(prices[symbol], 4),
            "Kerzen": len(df),
            "Ausgewählt (Validierung)": winner["strategy"] if winner else "Keine",
            "Validierung (%)": round(winner["validation"]["return_pct"], 2) if winner else None,
            "Holdout (%)": round(winner["holdout"]["return_pct"], 2) if winner else None,
        })
        for res in results:
            train, val, test = res["training"], res["validation"], res["holdout"]
            diagnostic_rows.append({
                "Markt": symbol,
                "Strategie": res["strategy"],
                "Validierungsstatus": "Zugelassen" if not res["reasons"] else "Abgelehnt",
                "Training (%)": round(train["return_pct"], 2),
                "Validierung (%)": round(val["return_pct"], 2),
                "Holdout (%)": round(test["return_pct"], 2),
                "Trades Validierung": val["closed_trades"],
                "Trades Holdout": test["closed_trades"],
                "Trefferquote Val. (%)": round(val["win_rate_pct"], 1),
                "Drawdown Val. (%)": round(val["drawdown_pct"], 2),
                "Profit-Faktor Val.": round(val["profit_factor"], 2),
                "Offen am Val.-Ende": "Ja" if val["open_at_end"] else "Nein",
                "Grund für Ablehnung": "; ".join(res["reasons"]) if res["reasons"] else "—",
            })
    except Exception as exc:
        errors.append(f"{symbol}: {exc}")

for error in errors:
    st.warning(error)
if market_rows:
    st.dataframe(pd.DataFrame(market_rows), hide_index=True, use_container_width=True)
else:
    st.error("Keine Kursdaten geladen. Bitte API-Verbindung prüfen.")

st.subheader("Backtest-Diagnose 0.3")
st.write("**Alle getesteten Strategien:** Auswahl nur nach Validierungsdaten; Holdout-Spalte separat zur Einordnung.")
if diagnostic_rows:
    st.dataframe(pd.DataFrame(diagnostic_rows), hide_index=True, use_container_width=True)
    st.caption(
        "Trades zählen nur vollständig geschlossene Positionen. Offene Positionen werden für die "
        "Rendite zum letzten Schlusskurs abzüglich geschätzter Verkaufskosten bewertet, aber nicht "
        "als geschlossene Trades gezählt. Einstiege nach Signal am Vortag/Vor-Kerzenschluss, "
        "Ausführung zum nächsten Kerzen-Open; Stop-Loss/Take-Profit intrabar konservativ "
        "modelliert. 0,05 % Slippage pro simuliertem Fill zusätzlich zu den eingestellten Gebühren."
    )
    if not any(winners.values()):
        st.info("Keine Strategie erfüllt derzeit die Validierungsfilter. Das ist kein Programmfehler; neue Käufe bleiben aus.")
    else:
        st.warning(
            "Ein positives Validierungsergebnis ist kein Beweis für Profitabilität. "
            "Besonders bei wenigen Trades bleiben die Ergebnisse unsicher."
        )
else:
    st.info("Noch keine Testergebnisse verfügbar.")

with st.expander("Wie funktionieren die Tests und warum lehnt Atlas ab?"):
    st.markdown(
        "**Training (40 %):** rückblickende Referenz; Strategieparameter sind in dieser "
        "Version fest vorgegeben. **Validierung (40 %):** einzige Basis der Strategieauswahl. "
        "**Holdout (20 %):** nachgelagerter Bericht, der nicht zur Auswahl verwendet wird. "
        "Jeder Abschnitt startet ohne offene Position. Die Indikatoren verwenden nur vergangene "
        "Kursdaten. Die Zeitfenster wandern beim täglichen Einsatz weiter: Ein wiederholt "
        "eingesehener Holdout ist deshalb kein dauerhaft blinder Zukunftstest."
    )
    st.markdown(
        "Für eine Freigabe auf **Validierungsdaten** gelten weiterhin: mindestens "
        "**3 geschlossene Trades**, **positive Rendite**, Drawdown **größer als −15 %** "
        "und Profit-Faktor **über 1,05**. Bei Gleichstand gewinnt die höchste "
        "Validierungsrendite, nicht der Holdout."
    )

st.divider()
st.subheader("Paper-Trading")
st.write(
    "Die Handelssimulation verwendet die zuletzt abgeschlossene Kerze. "
    "Existierende Positionen werden auch dann auf Ausstieg geprüft, wenn gerade "
    "keine neue Strategie zugelassen wird."
)
run_now = st.button("▶ Paper-Bot jetzt ausführen", type="primary")
auto = st.toggle("Automatisch alle 60 Sekunden prüfen (nur bei geöffneter Sitzung)", value=False)
if auto:
    st_autorefresh(interval=60_000, key="atlas_auto_refresh")

if run_now or auto:
    actions = []
    for symbol, df in frames.items():
        winner = winners.get(symbol)
        try:
            action = run_paper_cycle(
                symbol=symbol, df=df,
                strategy_name=winner["strategy"] if winner else None,
                fee_rate=fee_rate, initial_cash=float(initial_cash),
            )
            if action:
                actions.append(f"{symbol}: {action}")
        except Exception as exc:
            st.error(f"Handelssimulation bei {symbol}: {exc}")
    if actions:
        for action in actions:
            st.success(action)
    elif run_now:
        st.info(
            "Keine Aktion: Entweder wurde keine Strategie freigegeben, es gibt kein neues "
            "Kauf-/Verkaufssignal oder die abgeschlossene Kerze wurde schon verarbeitet."
        )

portfolio = get_portfolio(float(initial_cash), prices=prices)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Virtuelles Guthaben", f'{portfolio["cash"]:.2f} €')
c2.metric("Offene Positionen", str(portfolio["open_positions"]))
c3.metric("Realisierter Gewinn/Verlust", f'{portfolio["realized_pnl"]:+.2f} €')
c4.metric("Geschätzter Kontowert", f'{portfolio["equity"]:.2f} €')
if portfolio["positions"]:
    st.markdown("**Offene Paper-Positionen**")
    st.dataframe(pd.DataFrame(portfolio["positions"]), hide_index=True, use_container_width=True)
if portfolio["incomplete_pricing"]:
    st.warning("Für mindestens eine offene Position fehlt ein aktueller Kurs; deren Bewertung ist nur eine Näherung.")

st.divider()
st.subheader("Trade-Verlauf")
history = get_trade_history()
if history:
    st.dataframe(pd.DataFrame(history), hide_index=True, use_container_width=True)
else:
    st.info("Noch keine simulierten Trades.")

st.caption(
    "Achtung: Backtests und Paper-Trades sind keine Gewinnprognose. "
    "Paper-Fills zum Schlusskurs sind nicht mit echten, handelbaren Ausführungen gleichzusetzen. "
    "Auf Streamlit Community Cloud keine garantierte 24/7-Ausführung, keine gesicherte "
    "dauerhafte SQLite-Speicherung. Bei öffentlicher App ist das Paper-Konto für "
    "Besucher gemeinsam nutzbar und zurücksetzbar. Echtgeld-Orders technisch nicht vorhanden."
)
