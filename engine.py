"""Atlas Trading AI 0.3 — Kraken OHLCV, chronological research, paper orders only.

Research only; no live-order API, no claim of statistical edge.  Kraken returns
at most 720 most-recent OHLC candles.  Intervals reset flat at their boundaries.
"""

import os
import sqlite3
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd

DB_PATH = Path(os.getenv("ATLAS_DB_PATH", "atlas_trading.db"))
SYMBOLS = ["BTC/EUR", "ETH/EUR", "SOL/EUR"]
STRATEGIES = ["EMA Trend", "RSI Reversal", "Breakout"]
HISTORY_LIMIT = 720
MIN_TRADES = 3
MIN_RETURN_PCT = 0.0
MAX_DRAWDOWN_PCT = -15.0
MIN_PROFIT_FACTOR = 1.05


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(initial_cash=100.0):
    with _connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id=1), cash REAL NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0, initial_cash REAL NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY, qty REAL NOT NULL, entry_price REAL NOT NULL,
            invested REAL NOT NULL, opened_at TEXT NOT NULL, strategy TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL,
            qty REAL NOT NULL, fee REAL NOT NULL, pnl REAL, strategy TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS processed (
            symbol TEXT PRIMARY KEY, candle_ts INTEGER NOT NULL)""")
        row = con.execute("SELECT id FROM account WHERE id=1").fetchone()
        if row is None:
            con.execute("INSERT INTO account(id,cash,realized_pnl,initial_cash) VALUES(1,?,?,?)",
                        (float(initial_cash), 0.0, float(initial_cash)))


def reset_paper_account(initial_cash=100.0):
    _init_db(initial_cash)
    with _connect() as con:
        for table in ("account", "positions", "trades", "processed"):
            con.execute(f"DELETE FROM {table}")
    _init_db(initial_cash)


def fetch_ohlcv(symbol, timeframe="1h", limit=HISTORY_LIMIT):
    """Latest *closed* candles. Kraken REST does not offer >720 historical OHLC bars."""
    exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 20000})
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(int(limit), HISTORY_LIMIT))
    if not raw or len(raw) < 250:
        raise RuntimeError("Zu wenige Kursdaten: mindestens 250 Kerzen benötigt.")
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    # Kraken includes an unfinished current candle; omit it unconditionally.
    df = df.iloc[:-1].dropna().reset_index(drop=True)
    if len(df) < 240:
        raise RuntimeError("Zu wenige abgeschlossene Kurskerzen.")
    return df


def _indicators(df):
    x = df.copy()
    x["ema_fast"] = x["close"].ewm(span=12, adjust=False).mean()
    x["ema_slow"] = x["close"].ewm(span=26, adjust=False).mean()
    delta = x["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = (100 - (100 / (1 + rs))).where(loss != 0, 100.0)
    x.loc[(loss == 0) & (gain == 0), "rsi"] = 50.0
    x["prior_high"] = x["high"].rolling(20).max().shift(1)
    x["prior_low"] = x["low"].rolling(20).min().shift(1)
    return x


def _signals(df, strategy):
    x = _indicators(df)
    if strategy == "EMA Trend":
        entry = (x["ema_fast"] > x["ema_slow"]) & (x["ema_fast"].shift(1) <= x["ema_slow"].shift(1))
        exit_ = x["ema_fast"] < x["ema_slow"]
    elif strategy == "RSI Reversal":
        entry = (x["rsi"] < 30) & (x["rsi"].shift(1) >= 30)
        exit_ = x["rsi"] > 55
    elif strategy == "Breakout":
        entry = x["close"] > x["prior_high"]
        exit_ = x["close"] < x["prior_low"]
    else:
        raise ValueError(f"Unbekannte Strategie: {strategy}")
    return entry.fillna(False).to_numpy(dtype=bool), exit_.fillna(False).to_numpy(dtype=bool)


def _period_backtest(df, entry_sig, exit_sig, start, end, fee_rate=0.001,
                     slippage_rate=0.0005):
    """Backtest with previous-close signals and next-bar-open fills.

    We reset flat at the start of each period; an open position at the end
    contributes to equity (net of hypothetical closing costs) but NOT to
    the number of closed trades or profit factor. Intrabar stop is checked
    before take-profit when both are touched; gaps use the worse open price.
    """
    if not (0 <= start < end <= len(df)):
        raise ValueError("Ungültige Testgrenzen")
    if not (0 <= fee_rate < 1 and 0 <= slippage_rate < 1):
        raise ValueError("Ungültige Gebühren oder Slippage")
    initial = 1000.0
    cash = initial
    qty = 0.0
    entry_cost = 0.0
    entry_price = 0.0
    closed_pnls = []
    equity_values = [initial]
    for i in range(start, end):
        bar = df.iloc[i]
        bar_open = float(bar["open"])
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])
        bar_close = float(bar["close"])
        if min(bar_open, bar_low, bar_high, bar_close) <= 0:
            raise ValueError("Ungültige OHLC-Preise")
        # Signal was known only *after* bar i-1 closed.
        if i > 0 and qty > 0 and exit_sig[i - 1]:
            sale_price = bar_open * (1 - slippage_rate)
            proceeds = qty * sale_price * (1 - fee_rate)
            cash = proceeds
            closed_pnls.append(proceeds - entry_cost)
            qty = 0.0
            entry_cost = 0.0
        elif i > start and qty == 0 and entry_sig[i - 1]:
            buy_price = bar_open * (1 + slippage_rate)
            qty = cash / (buy_price * (1 + fee_rate))
            entry_price = buy_price
            entry_cost = cash
            cash = 0.0

        if qty > 0:
            stop, take = entry_price * 0.98, entry_price * 1.04
            sale_price = None
            if bar_open <= stop:
                sale_price = bar_open * (1 - slippage_rate)
            elif bar_low <= stop:
                sale_price = stop * (1 - slippage_rate)
            elif bar_open >= take:
                sale_price = take * (1 - slippage_rate)  # conservative on gaps up
            elif bar_high >= take:
                sale_price = take * (1 - slippage_rate)
            if sale_price is not None:
                proceeds = qty * sale_price * (1 - fee_rate)
                cash = proceeds
                closed_pnls.append(proceeds - entry_cost)
                qty = 0.0
                entry_cost = 0.0
        # Liquidation fee assumed for open positions to prevent optimistic equity.
        equity_values.append(cash if qty == 0 else qty * bar_close * (1 - fee_rate - slippage_rate))

    final_equity = equity_values[-1]
    equity_curve = pd.Series(equity_values, dtype="float64")
    max_dd = float((equity_curve / equity_curve.cummax() - 1).min() * 100)
    gains = sum(max(p, 0.0) for p in closed_pnls)
    losses = abs(sum(min(p, 0.0) for p in closed_pnls))
    profit_factor = min(gains / losses, 99.0) if losses > 0 else (99.0 if gains > 0 else 0.0)
    return {
        "return_pct": (final_equity / initial - 1) * 100,
        "drawdown_pct": max_dd,
        "closed_trades": len(closed_pnls),
        "win_rate_pct": (100 * sum(p > 0 for p in closed_pnls) / len(closed_pnls)) if closed_pnls else 0.0,
        "profit_factor": float(profit_factor),
        "open_at_end": bool(qty > 0),
    }


def rejection_reasons(metrics):
    reasons = []
    if metrics["closed_trades"] < MIN_TRADES:
        reasons.append(f"Zu wenige abgeschlossene Trades ({metrics['closed_trades']}/{MIN_TRADES})")
    if metrics["return_pct"] <= MIN_RETURN_PCT:
        reasons.append(f"Rendite nicht positiv ({metrics['return_pct']:+.2f} %)")
    if metrics["drawdown_pct"] <= MAX_DRAWDOWN_PCT:
        reasons.append(f"Drawdown zu hoch ({metrics['drawdown_pct']:.2f} %)")
    if metrics["profit_factor"] <= MIN_PROFIT_FACTOR:
        reasons.append(f"Profit-Faktor zu niedrig ({metrics['profit_factor']:.2f})")
    return reasons


def evaluate_strategies(df, fee_rate=0.001):
    """Chronological 40/40/20 training/validation/holdout split.

    Strategies have fixed parameters (no fitting yet). Selection uses validation
    only. Holdout is for an independent descriptive report, never selection.
    Repeated rolling reviews eventually reuse the holdout, so this is not a
    permanent truly-blind test or a guarantee of prospective performance.
    """
    n = len(df)
    if n < 240:
        raise ValueError("Zu kurze Historie für drei getrennte Testzeiträume")
    train_end = int(n * 0.40)
    validation_end = int(n * 0.80)
    segments = {
        "training": (0, train_end),
        "validation": (train_end, validation_end),
        "holdout": (validation_end, n),
    }
    results = []
    for strategy in STRATEGIES:
        entry_sig, exit_sig = _signals(df, strategy)
        result = {"strategy": strategy}
        for name, (start, end) in segments.items():
            result[name] = _period_backtest(df, entry_sig, exit_sig, start, end, fee_rate)
        result["reasons"] = rejection_reasons(result["validation"])
        results.append(result)
    eligible = [r for r in results if not r["reasons"]]
    eligible.sort(key=lambda r: (r["validation"]["return_pct"], r["validation"]["profit_factor"]), reverse=True)
    return results, (eligible[0] if eligible else None)


def get_portfolio(initial_cash=100.0, prices=None):
    _init_db(initial_cash)
    prices = prices or {}
    with _connect() as con:
        account = con.execute("SELECT * FROM account WHERE id=1").fetchone()
        rows = con.execute("SELECT * FROM positions").fetchall()
    positions = []
    market_value = 0.0
    incomplete = False
    for row in rows:
        price = prices.get(row["symbol"])
        if price is None:
            incomplete = True
            marked = float(row["invested"])
        else:
            marked = float(row["qty"]) * float(price)
        positions.append({
            "Markt": row["symbol"], "Menge": row["qty"], "Einstieg": row["entry_price"],
            "Investiert": row["invested"], "Marktwert (geschätzt)": round(marked, 2),
            "Strategie": row["strategy"], "Status": "Offen",
        })
        market_value += marked
    return {
        "cash": float(account["cash"]),
        "realized_pnl": float(account["realized_pnl"]),
        "open_positions": len(positions),
        "positions": positions,
        "equity": float(account["cash"]) + market_value,
        "incomplete_pricing": incomplete,
    }


def run_paper_cycle(symbol, df, strategy_name=None, fee_rate=0.001, initial_cash=100.0):
    """One simulated action per new closed candle; *never* a real exchange order.

    Existing positions are risk-checked even if current research has no winner.
    Uses last closed price as an indicative fill; NOT a realistic live execution.
    """
    _init_db(initial_cash)
    if len(df) < 2:
        return None
    last = df.iloc[-1]
    candle_ts = int(pd.Timestamp(last["timestamp"]).timestamp() * 1000)
    price = float(last["close"])
    now = pd.Timestamp.now(tz="UTC").isoformat()

    with _connect() as con:
        processed = con.execute("SELECT candle_ts FROM processed WHERE symbol=?", (symbol,)).fetchone()
        if processed and int(processed["candle_ts"]) >= candle_ts:
            return None
        pos = con.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
        account = con.execute("SELECT * FROM account WHERE id=1").fetchone()
        cash = float(account["cash"])
        if pos:
            # Do not replace exit strategy for an existing position mid-trade.
            _, exit_sig = _signals(df, pos["strategy"])
            entry_price = float(pos["entry_price"])
            if bool(exit_sig[-1]) or price <= entry_price * 0.98 or price >= entry_price * 1.04:
                qty = float(pos["qty"])
                gross = qty * price
                fee = gross * fee_rate
                proceeds = gross - fee
                pnl = proceeds - float(pos["invested"])
                con.execute("UPDATE account SET cash=cash+?, realized_pnl=realized_pnl+? WHERE id=1",
                            (proceeds, pnl))
                con.execute("INSERT INTO trades(timestamp,symbol,side,price,qty,fee,pnl,strategy) VALUES(?,?,?,?,?,?,?,?)",
                            (now, symbol, "SELL", price, qty, fee, pnl, pos["strategy"]))
                con.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                con.execute("INSERT OR REPLACE INTO processed(symbol,candle_ts) VALUES(?,?)", (symbol, candle_ts))
                return f"VERKAUFT bei {price:.4f} · Ergebnis {pnl:+.2f} €"
        elif strategy_name and cash >= 10:
            entry_sig, _ = _signals(df, strategy_name)
            if bool(entry_sig[-1]):
                # Max 20% of available cash, and never more than €20 per entry.
                allocation = min(cash * 0.20, 20.0)
                qty = allocation / (price * (1 + fee_rate))
                cost = qty * price
                fee = cost * fee_rate
                total = cost + fee
                if total <= cash:
                    con.execute("UPDATE account SET cash=cash-? WHERE id=1", (total,))
                    con.execute("INSERT OR REPLACE INTO positions(symbol,qty,entry_price,invested,opened_at,strategy) VALUES(?,?,?,?,?,?)",
                                (symbol, qty, price, total, now, strategy_name))
                    con.execute("INSERT INTO trades(timestamp,symbol,side,price,qty,fee,pnl,strategy) VALUES(?,?,?,?,?,?,?,?)",
                                (now, symbol, "BUY", price, qty, fee, None, strategy_name))
                    con.execute("INSERT OR REPLACE INTO processed(symbol,candle_ts) VALUES(?,?)", (symbol, candle_ts))
                    return f"GEKAUFT bei {price:.4f} · Einsatz {total:.2f} €"
        con.execute("INSERT OR REPLACE INTO processed(symbol,candle_ts) VALUES(?,?)", (symbol, candle_ts))
    return None


def get_trade_history(limit=100):
    _init_db()
    with _connect() as con:
        rows = con.execute("SELECT timestamp,symbol,side,price,qty,fee,pnl,strategy FROM trades ORDER BY id DESC LIMIT ?",
                           (int(limit),)).fetchall()
    return [dict(r) for r in rows]
