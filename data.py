"""Historical candle acquisition, pagination, validation, and local SQLite cache."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable

import ccxt
import pandas as pd

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
TIMEFRAME_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _db(path: str | Path):
    con = sqlite3.connect(path, timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS candles (exchange TEXT, symbol TEXT, timeframe TEXT, timestamp INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL, PRIMARY KEY(exchange,symbol,timeframe,timestamp))")
    return con


def cache_read(path, exchange, symbol, timeframe, since_ms=None, until_ms=None):
    con = _db(path)
    try:
        q = "SELECT timestamp,open,high,low,close,volume FROM candles WHERE exchange=? AND symbol=? AND timeframe=?"
        args = [exchange, symbol, timeframe]
        if since_ms is not None:
            q += " AND timestamp>=?"; args.append(int(since_ms))
        if until_ms is not None:
            q += " AND timestamp<?"; args.append(int(until_ms))
        q += " ORDER BY timestamp"
        rows = con.execute(q, args).fetchall()
    finally:
        con.close()
    return pd.DataFrame(rows, columns=COLUMNS)


def cache_write(path, exchange, symbol, timeframe, frame):
    if frame.empty:
        return
    rows = [(exchange, symbol, timeframe, int(r.timestamp), float(r.open), float(r.high), float(r.low), float(r.close), float(r.volume)) for r in frame.itertuples(index=False)]
    con = _db(path)
    try:
        con.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()


def normalize(raw):
    if not raw:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(raw, columns=COLUMNS)
    df["timestamp"] = pd.to_numeric(df.timestamp, errors="coerce").astype("Int64")
    for c in COLUMNS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    valid = (df.low > 0) & (df.high >= df[["open", "close", "low"]].max(axis=1)) & (df.low <= df[["open", "close"]].min(axis=1)) & (df.volume >= 0)
    return df.loc[valid].astype({"timestamp": "int64"}).reset_index(drop=True)


def fetch_history(exchange_id: str, symbol: str, timeframe: str, start_ms: int, end_ms: int,
                  cache_path="atlas_market.sqlite3", page_limit=1000, retries=5,
                  exchange_factory: Callable | None = None, on_page: Callable | None = None):
    """Fetch [start,end) with since-based pagination; safe with capped OHLCV endpoints.

    Stops on empty pages, no forward progress, or a short page. Some exchanges
    (notably Kraken OHLC) expose only a rolling recent window and ignore `since`;
    that limitation is detected and reported in the returned diagnostics.
    """
    if timeframe not in TIMEFRAME_MS or end_ms <= start_ms:
        raise ValueError("Ungültiger Zeitraum oder Zeitintervall")
    cached = cache_read(cache_path, exchange_id, symbol, timeframe, start_ms, end_ms)
    ex = (exchange_factory or getattr(ccxt, exchange_id))({"enableRateLimit": True, "timeout": 30000})
    if not ex.has.get("fetchOHLCV"):
        raise RuntimeError(f"{exchange_id} unterstützt keine OHLCV-Daten.")
    if hasattr(ex, "load_markets"):
        try:
            markets = ex.load_markets()
        except ccxt.BaseError as exc:
            raise RuntimeError(f"Marktverfügbarkeit bei {exchange_id} konnte nicht geprüft werden: {exc}") from exc
        if symbol not in markets:
            available = [s for s in markets if s.endswith("/USDT") and s.split("/")[0] in {"BTC", "ETH", "SOL"}]
            raise RuntimeError(f"{symbol} ist bei {exchange_id} nicht verfügbar. Verfügbare Startmärkte: {', '.join(available) or 'keine der ausgewählten USDT-Paare'}")
    step = TIMEFRAME_MS[timeframe]
    cursor = start_ms
    if not cached.empty:
        ts = cached.timestamp.to_numpy(dtype="int64")
        if int(ts[0]) > start_ms:
            cursor = start_ms
        else:
            breaks = [int(ts[i-1] + step) for i in range(1, len(ts)) if int(ts[i] - ts[i-1]) > step]
            cursor = min(breaks) if breaks else int(ts[-1] + step)
    fetched = 0
    raw_pages = []
    page_size = min(max(int(page_limit), 1), 1000)
    errors = []
    max_pages = min(10_000, max(1, (end_ms - start_ms) // TIMEFRAME_MS[timeframe] // page_size + 100))
    for _ in range(max_pages):
        if cursor >= end_ms:
            break
        for attempt in range(retries):
            try:
                page = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=page_size)
                break
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RateLimitExceeded) as exc:
                errors.append(str(exc))
                if attempt + 1 == retries:
                    raise RuntimeError(f"Datenabruf nach {retries} Versuchen fehlgeschlagen: {exc}") from exc
                time.sleep(min(2 ** attempt, 12))
            except ccxt.BaseError as exc:
                raise RuntimeError(f"{exchange_id} meldet: {exc}") from exc
        rows = [r for r in (page or []) if start_ms <= int(r[0]) < end_ms]
        if not rows:
            if page and not any(start_ms <= int(r[0]) < end_ms for r in page):
                errors.append("Datenquelle lieferte keine Kerzen im angefragten Zeitraum; sie könnte ältere since-Werte ignorieren oder nur ein begrenztes Historienfenster bereitstellen.")
            break
        raw_pages.extend(rows); fetched += len(rows)
        newest = max(int(r[0]) for r in rows)
        next_cursor = newest + step
        if on_page:
            on_page(cursor, newest, fetched)
        if next_cursor <= cursor:
            errors.append("Pagination stoppte: Zeitstempel machte keinen Fortschritt; API ignoriert möglicherweise since.")
            break
        cursor = next_cursor
    fresh = normalize(raw_pages)
    if not fresh.empty:
        cache_write(cache_path, exchange_id, symbol, timeframe, fresh)
    parts = [part for part in (cached, fresh) if not part.empty]
    merged = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLUMNS)
    merged = normalize(merged[COLUMNS].values.tolist()) if not merged.empty else merged
    # Closed candles only. The current candle can be incomplete.
    now_ms = ex.milliseconds()
    merged = merged.loc[merged.timestamp + TIMEFRAME_MS[timeframe] <= now_ms].reset_index(drop=True)
    gaps = int(max(0, (merged.timestamp.diff().dropna() // step - 1).clip(lower=0).sum())) if len(merged) > 1 else 0
    info = {"exchange": exchange_id, "symbol": symbol, "timeframe": timeframe,
            "first": int(merged.timestamp.min()) if len(merged) else None,
            "last": int(merged.timestamp.max()) if len(merged) else None,
            "candles": len(merged), "valid_candles": len(merged), "missing_intervals": gaps,
            "api_rows_fetched": fetched, "cache_rows_reused": len(cached), "warnings": errors}
    return merged, info


def validate_frame(df, timeframe):
    if df.empty:
        raise ValueError("Keine historischen Kerzen verfügbar.")
    if df.timestamp.duplicated().any() or not df.timestamp.is_monotonic_increasing:
        raise ValueError("Zeitstempel sind doppelt oder nicht chronologisch sortiert.")
    step = TIMEFRAME_MS[timeframe]
    gaps = int(max(0, (df.timestamp.diff().dropna() // step - 1).clip(lower=0).sum())) if len(df) > 1 else 0
    return {"first": int(df.timestamp.iloc[0]), "last": int(df.timestamp.iloc[-1]), "candles": len(df), "missing_intervals": gaps}
