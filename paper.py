"""Restart-safe BTC/EUR paper ledger. No exchange-order methods exist here."""
from __future__ import annotations
import copy
import fcntl
import hashlib
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import pandas as pd
from strategies import generate_signals, STRATEGIES

STEP = 14400

def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")

def number(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError("Invalid finite numeric value")
    return float(value)

def atomic_json(path, value):
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as out:
            out.write(payload); out.flush(); os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

@contextmanager
def locked(path):
    with open(str(path) + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def validate_config(c):
    if set(c) != {"trading_enabled", "max_allocation", "max_positions", "fee_rate", "slippage", "max_drawdown", "daily_loss_limit", "stop_loss", "take_profit"}:
        raise ValueError("Unknown or missing config field")
    if type(c["trading_enabled"]) is not bool or type(c["max_positions"]) is not int or c["max_positions"] != 1:
        raise ValueError("Only one position supported")
    for key in ("fee_rate", "slippage", "max_drawdown", "daily_loss_limit", "stop_loss", "take_profit", "max_allocation"):
        number(c[key])
    if not 0 < c["max_allocation"] <= .20 or not 0 <= c["fee_rate"] < .01 or not 0 <= c["slippage"] < .01:
        raise ValueError("Unsafe allocation or costs")
    if not all(0 < c[k] <= .20 for k in ("max_drawdown", "daily_loss_limit", "stop_loss", "take_profit")):
        raise ValueError("Invalid loss limits")
    return c


def migrate(raw):
    s = copy.deepcopy(raw)
    for k in ("cash_eur", "btc", "last_ts"):
        number(s[k])
    if int(s["last_ts"]) != s["last_ts"]: raise ValueError("Invalid candle timestamp")
    if s["btc"] > 0: number(s["entry_eur"], 1e-12)
    if s.get("schema_version", 1) not in (1, 4): raise ValueError("Unknown ledger schema")
    if s.get("schema_version") != 4:
        s["legacy_snapshot"] = copy.deepcopy(raw)
        s.update(schema_version=4, trades=[], equity_history=[], decisions=[], realized_pnl_eur=0.0,
                 fees_eur=0.0, cost_basis_eur=None if s["btc"] else 0.0,
                 position_strategy="SMA 20/50" if s["btc"] else None,
                 peak_equity_eur=number(s.get("equity_eur", s["cash_eur"])), halted=False)
        s["accounting_note"] = "v0.4 metrics start at migration; legacy cost basis unknown for existing position. Original CSV retained."
    for k in ("realized_pnl_eur", "fees_eur", "peak_equity_eur"):
        number(s[k], -1e100 if k == "realized_pnl_eur" else 0)
    if s["cost_basis_eur"] is not None: number(s["cost_basis_eur"])
    if type(s["halted"]) is not bool: raise ValueError("Invalid halt state")
    if s["btc"] == 0 and s["cost_basis_eur"] not in (0, None): raise ValueError("Cost basis without position")
    if s["btc"] and s["position_strategy"] not in STRATEGIES: raise ValueError("Unknown position strategy")
    for k in ("trades", "equity_history", "decisions"):
        if not isinstance(s[k], list): raise ValueError("Invalid ledger collection")
    ids = [t["id"] for t in s["trades"]]
    if len(ids) != len(set(ids)): raise ValueError("Duplicate persisted trade IDs")
    return s


def validate_candles(df, now):
    if len(df) < 201: raise ValueError("At least 201 closed candles required")
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    if not all(k in df for k in cols): raise ValueError("Missing OHLCV columns")
    for row in df[cols].itertuples(index=False, name=None):
        ts, o, h, l, c, v = [number(x) for x in row]
        if min(o, h, l, c) <= 0 or h < max(o, l, c) or l > min(o, c) or ts % (STEP*1000):
            raise ValueError("Invalid OHLCV candle")
    if not df.timestamp.diff().dropna().eq(STEP*1000).all(): raise ValueError("Duplicate, unordered or missing candles")
    closed = int(df.timestamp.iloc[-1] / 1000) + STEP
    if not 0 <= now - closed < STEP: raise ValueError("Stale or unfinished candle")


def get_public(endpoint, extra=""):
    url = "https://api.kraken.com/0/public/" + endpoint + "?pair=XBTEUR" + extra
    with urlopen(Request(url, headers={"User-Agent":"Atlas-Paper/0.4"}), timeout=25) as response:
        payload = json.load(response)
    if payload.get("error"): raise RuntimeError("Kraken API returned an error")
    values = [v for k,v in payload["result"].items() if k != "last"]
    if len(values) != 1: raise ValueError("Unexpected Kraken response")
    return values[0]


def market_snapshot(now):
    rows = get_public("OHLC", "&interval=240")
    frame = pd.DataFrame([[int(r[0])*1000, *map(float, r[1:5]), float(r[6])] for r in rows],
                         columns=["timestamp","open","high","low","close","volume"])
    frame = frame[frame.timestamp/1000 + STEP <= now].reset_index(drop=True)
    validate_candles(frame, now)
    # Current bid/ask, never retroactive candle-close fills.
    ticker = get_public("Ticker")
    bid, ask = float(ticker["b"][0]), float(ticker["a"][0])
    number(bid, 1e-12); number(ask, bid)
    if ask/bid > 1.02: raise ValueError("Spread exceeds 2%")
    return frame, {"bid": bid, "ask": ask, "observed_at": time.time()}


def strategy_fingerprint():
    return hashlib.sha256(Path(__file__).with_name("strategies.py").read_bytes()).hexdigest()


def admitted(report, cfg, now, candle_ts):
    if not report or report.get("selected") not in STRATEGIES: return None
    if report.get("protocol") != "atlas-fixed-v1" or report.get("strategy_hash") != strategy_fingerprint(): return None
    if report.get("costs") != [cfg["fee_rate"], cfg["slippage"]]: return None
    if report.get("risk") != {k:cfg[k] for k in ("max_allocation","max_drawdown","daily_loss_limit","stop_loss","take_profit")}: return None
    if report.get("market") != "BTC/EUR" or report.get("timeframe") != "4h": return None
    if not report["data_end"] < candle_ts or not report["created_at"] <= now < report["expires_at"]: return None
    selected = next((r for r in report["candidates"] if r["strategy"] == report["selected"]), None)
    if not selected: return None
    from research import rejection_reasons
    if rejection_reasons(selected["training"]) or rejection_reasons(selected["validation"]): return None
    return report["selected"]


def cycle(raw, df, quote, cfg, report, now):
    """Pure transaction: callers commit the returned complete ledger atomically."""
    validate_config(cfg); validate_candles(df, now)
    s = migrate(raw)
    bid, ask = number(quote["bid"], 1e-12), number(quote["ask"], 1e-12)
    if ask < bid or ask/bid > 1.02 or not 0 <= now-number(quote["observed_at"]) <= 60:
        raise ValueError("Invalid or stale quote")
    ts = int(df.timestamp.iloc[-1]/1000)
    if s["last_ts"] > ts: raise ValueError("Candle older than persisted state")
    when = utc(now)
    s["last_checked_utc"] = when
    if s["last_ts"] == ts:
        s["last_result"] = "Halten: Kerze bereits verarbeitet"
        s["decisions"].append({"time":when,"candle":ts,"reason":s["last_result"]})
        return s
    equity = s["cash_eur"] + s["btc"]*bid
    starting_equity = equity
    s["peak_equity_eur"] = max(s["peak_equity_eur"], equity)
    day = when[:10]
    if s.get("risk_day") != day:
        s.update(risk_day=day, day_start_equity=equity)
    daily_stop = equity <= s["day_start_equity"]*(1-cfg["daily_loss_limit"])
    if equity <= s["peak_equity_eur"]*(1-cfg["max_drawdown"]): s["halted"] = True
    selected = admitted(report, cfg, now, ts)
    reason = "Halten: kein Signal" if selected else "Halten: keine zugelassene Strategie"
    trade = None
    if not cfg["trading_enabled"]:
        reason = "Handel manuell deaktiviert (auch Ausstiege)"
    elif s["btc"] > 0:
        _, exits, _, _ = generate_signals(df, s["position_strategy"])
        exit_reason = ("Verlustgrenze" if s["halted"] or daily_stop else "Strategie-Ausstieg" if bool(exits.iloc[-1]) else
                       "Simulierter Stop" if bid <= s["entry_eur"]*(1-cfg["stop_loss"]) else
                       "Gewinnziel" if bid >= s["entry_eur"]*(1+cfg["take_profit"]) else None)
        if exit_reason:
            qty = s["btc"]; fill = bid*(1-cfg["slippage"]); fee = qty*fill*cfg["fee_rate"]
            proceeds = qty*fill-fee
            pnl = proceeds-s["cost_basis_eur"] if s["cost_basis_eur"] is not None else None
            trade = dict(side="SELL", fill_eur=fill, qty_btc=qty, fee_eur=fee, net_pnl_eur=pnl,
                         slippage_eur=qty*(bid-fill), invested_eur=s["cost_basis_eur"],
                         entry_time=s.get("entry_time"), entry_price=s["entry_eur"], strategy=s["position_strategy"])
            s["cash_eur"] += proceeds
            if pnl is not None: s["realized_pnl_eur"] += pnl
            s.update(btc=0.0, entry_eur=None, cost_basis_eur=0.0, position_strategy=None)
            reason = exit_reason
    elif s["halted"] or daily_stop:
        reason = "Neue Einstiege durch Verlustgrenze gesperrt"
    elif selected and s["cash_eur"] >= 10:
        entries, _, _, why = generate_signals(df, selected)
        if bool(entries.iloc[-1]):
            budget = min(s["cash_eur"]*cfg["max_allocation"], equity*.20)
            fill = ask*(1+cfg["slippage"]); qty = budget/(fill*(1+cfg["fee_rate"])); fee = qty*fill*cfg["fee_rate"]
            s["cash_eur"] -= budget
            s.update(btc=qty, entry_eur=fill, cost_basis_eur=budget, entry_time=when, position_strategy=selected)
            reason = why
            trade = dict(side="BUY", fill_eur=fill, qty_btc=qty, fee_eur=fee, net_pnl_eur=None,
                         invested_eur=budget, slippage_eur=qty*(fill-ask), entry_time=when, entry_price=fill, strategy=selected)
    if trade:
        trade.update(id=f"BTC-EUR:{ts}:{trade['side']}", time_utc=when, candle_ts=ts, market="BTC/EUR", reason=reason)
        if any(t["id"] == trade["id"] for t in s["trades"]): raise ValueError("Duplicate trade ID")
        s["trades"].append(trade); s["fees_eur"] += trade["fee_eur"]
    equity = s["cash_eur"] + s["btc"]*bid
    if "benchmark" not in s:
        s["benchmark"] = {"time":when,"initial_equity":starting_equity,"qty":starting_equity/(ask*(1+cfg["slippage"])*(1+cfg["fee_rate"]))}
    s.update(last_ts=ts, last_price_eur=bid, equity_eur=equity, last_result=reason,
             last_success_utc=when, strategy=s["position_strategy"] or selected or "Keine zugelassen")
    s["equity_history"].append({"time":when,"equity_eur":equity,
        "buy_hold_eur":s["benchmark"]["qty"]*bid*(1-cfg["slippage"])*(1-cfg["fee_rate"])})
    s["decisions"].append({"time":when,"candle":ts,"reason":reason})
    return migrate(s)


def run(directory=".", provider=market_snapshot, now=None):
    root = Path(directory); state_path = root/"paper_state.json"
    now = time.time() if now is None else now
    with locked(state_path):
        try:
            # Missing or corrupt account is a failure, never an implicit reset.
            original = state_path.read_bytes(); raw = json.loads(original)
            migrate(raw)
            cfg = validate_config(json.loads((root/"paper_config.json").read_text()))
            report_path = root/"strategy_report.json"
            report = json.loads(report_path.read_text()) if report_path.exists() else None
            frame, quote = provider(now)
            execution_now = time.time() if provider is market_snapshot else now
            new = cycle(raw, frame, quote, cfg, report, execution_now)
            backup = root/"paper_state.pre-v04.json"
            if raw.get("schema_version") != 4 and not backup.exists():
                with backup.open("xb") as out: out.write(original)
            atomic_json(state_path, new)
            status = {"status":"success", "last_attempt_utc":utc(execution_now), "decision":new["last_result"],
                      "equity_eur":new.get("equity_eur"), "candle_ts":new["last_ts"]}
            atomic_json(root/"paper_status.json", status)
            print(json.dumps(status, ensure_ascii=False))
            return new
        except Exception as exc:
            status = {"status":"failed", "last_attempt_utc":utc(now), "error_type":type(exc).__name__,
                      "decision":"Sicher abgebrochen; Konto unverändert"}
            atomic_json(root/"paper_status.json", status)
            print(json.dumps(status, ensure_ascii=False))
            raise

if __name__ == "__main__":
    run()
