import os
import sqlite3
import time
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd

DB_PATH = Path(os.getenv("ATLAS_DB_PATH", "atlas_trading.db"))
SYMBOLS = ["BTC/EUR", "ETH/EUR", "SOL/EUR"]
STRATEGIES = ["EMA Trend", "RSI Reversal", "Breakout"]

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    with _connect() as con:
        for table in ("account", "positions", "trades", "processed"):
            con.execute(f"DELETE FROM {table}")
    _init_db(initial_cash)

def fetch_ohlcv(symbol, timeframe="1h", limit=500):
    exchange = ccxt.binance({"enableRateLimit": True, "timeout": 20000})
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw or len(raw) < 120:
        raise RuntimeError("Zu wenige Kursdaten erhalten.")
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Die letzte Kerze kann noch offen sein: für Signale nur abgeschlossene Kerzen verwenden.
    return df.iloc[:-1].dropna().reset_index(drop=True)

def _indicators(df):
    x = df.copy()
    x["ema_fast"] = x["close"].ewm(span=12, adjust=False).mean()
    x["ema_slow"] = x["close"].ewm(span=26, adjust=False).mean()
    delta = x["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = 100 - (100 / (1 + rs))
    x["prior_high"] = x["high"].rolling(20).max().shift(1)
    x["prior_low"] = x["low"].rolling(20).min().shift(1)
    return x

def _signals(df, strategy):
    x = _indicators(df)
    if strategy == "EMA Trend":
        entry = (x["ema_fast"] > x["ema_slow"]) & (x["ema_fast"].shift(1) <= x["ema_slow"].shift(1))
        exit_ = (x["ema_fast"] < x["ema_slow"])
    elif strategy == "RSI Reversal":
        entry = (x["rsi"] < 30) & (x["rsi"].shift(1) >= 30)
        exit_ = (x["rsi"] > 55)
    elif strategy == "Breakout":
        entry = x["close"] > x["prior_high"]
        exit_ = x["close"] < x["prior_low"]
    else:
        raise ValueError(f"Unbekannte Strategie: {strategy}")
    return entry.fillna(False).to_numpy(dtype=bool), exit_.fillna(False).to_numpy(dtype=bool)

def backtest(df, strategy, fee_rate=0.001):
    """Long-only, all-in/all-out Modell; Signal auf Schlusskurs, Ausführung nächste Kerze."""
    if len(df) < 150:
        return None
    entry_sig, exit_sig = _signals(df, strategy)
    start = max(100, int(len(df) * 0.70))
    cash = 1000.0
    qty = 0.0
    entry_cost = 0.0
    trades = []
    equity_curve = []
    for i in range(start, len(df) - 1):
        row = df.iloc[i]
        next_open = float(df.iloc[i + 1]["open"])
        if qty == 0 and entry_sig[i]:
            qty = cash / (next_open * (1 + fee_rate))
            fee = qty * next_open * fee_rate
            entry_cost = qty * next_open + fee
            cash = 0.0
            entry_price = next_open
        elif qty > 0:
            # Konservative Bar-Prüfung: Stop-Loss hat Vorrang, falls SL und TP in derselben Kerze berührt werden.
            stop = entry_price * 0.98
            take = entry_price * 1.04
            low = float(row["low"])
            high = float(row["high"])
            exit_price = None
            if low <= stop:
                exit_price = stop
            elif high >= take:
                exit_price = take
            elif exit_sig[i]:
                exit_price = next_open
            if exit_price is not None:
                gross = qty * exit_price
                fee = gross * fee_rate
                cash = gross - fee
                pnl = cash - entry_cost
                trades.append(pnl)
                qty = 0.0
                entry_cost = 0.0
        mark = cash if qty == 0 else qty * float(row["close"])
        equity_curve.append(mark)
    final_equity = cash if qty == 0 else qty * float(df.iloc[-1]["close"])
    if qty > 0:
        # Offene Position am Testende zum letzten Schlusskurs bewerten, nicht künstlich schließen.
        trades.append(final_equity - entry_cost)
    if not equity_curve:
        return None
    curve = pd.Series(equity_curve, dtype=float)
    peak = curve.cummax()
    drawdown = ((curve / peak) - 1.0).min() * 100
    wins = sum(1 for t in trades if t > 0)
    return {
        "strategy": strategy,
        "test_return_pct": (final_equity / 1000.0 - 1.0) * 100,
        "test_drawdown_pct": float(drawdown),
        "test_trades": len(trades),
        "win_rate_pct": (wins / len(trades) * 100) if trades else 0.0,
        "profit_factor": (
            sum(t for t in trades if t > 0) / abs(sum(t for t in trades if t < 0))
            if any(t < 0 for t in trades) else (99.0 if any(t > 0 for t in trades) else 0.0)
        ),
    }

def evaluate_strategies(df, fee_rate=0.001):
    results = []
    for strategy in STRATEGIES:
        result = backtest(df, strategy, fee_rate)
        if result:
            results.append(result)
    # Keine Auswahl bei zu wenigen Trades oder negativem Out-of-sample-Ergebnis.
    eligible = [r for r in results if r["test_trades"] >= 3 and r["test_return_pct"] > 0
                and r["test_drawdown_pct"] > -15 and r["profit_factor"] > 1.05]
    eligible.sort(key=lambda r: (r["test_return_pct"], r["profit_factor"]), reverse=True)
    return results, (eligible[0] if eligible else None)

def get_portfolio(initial_cash=100.0):
    _init_db(initial_cash)
    with _connect() as con:
        account = con.execute("SELECT * FROM account WHERE id=1").fetchone()
        rows = con.execute("SELECT * FROM positions").fetchall()
    positions = []
    market_value = 0.0
    for row in rows:
        positions.append({
            "Markt": row["symbol"], "Menge": row["qty"], "Einstieg": row["entry_price"],
            "Investiert": row["invested"], "Strategie": row["strategy"],
            "Status": "Offen"
        })
        # Ohne aktuellen Preis wird konservativ der investierte Betrag als Näherung angezeigt.
        market_value += row["invested"]
    return {
        "cash": float(account["cash"]),
        "realized_pnl": float(account["realized_pnl"]),
        "open_positions": len(positions),
        "positions": positions,
        "equity": float(account["cash"]) + market_value,
    }

def run_paper_cycle(symbol, df, strategy_name, fee_rate=0.001, initial_cash=100.0):
    _init_db(initial_cash)
    if len(df) < 2:
        return None
    last = df.iloc[-1]
    candle_ts = int(pd.Timestamp(last["timestamp"]).timestamp() * 1000)
    entry_sig, exit_sig = _signals(df, strategy_name)
    should_enter = bool(entry_sig[-1])
    should_exit = bool(exit_sig[-1])
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
            entry_price = float(pos["entry_price"])
            stop_hit = price <= entry_price * 0.98
            take_hit = price >= entry_price * 1.04
            if should_exit or stop_hit or take_hit:
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
        elif should_enter and cash >= 10:
            # Maximal 20 % des verfügbaren Cash pro Position; keine Kreditaufnahme/kein Hebel.
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
