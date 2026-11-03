"""Fixed, bounded strategy selection. Holdout never participates in ranking."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import pandas as pd
from backtest import metrics
from strategies import STRATEGIES, generate_signals
from paper import STEP, atomic_json, strategy_fingerprint, validate_candles


def rejection_reasons(m):
    reasons = []
    if m["trades"] < 10: reasons.append("Weniger als 10 abgeschlossene Trades")
    if m["return_pct"] <= 0: reasons.append("Keine positive Nettorendite")
    if m["max_drawdown_pct"] < -10: reasons.append("Drawdown über 10%")
    if m["profit_factor"] < 1.10: reasons.append("Profit-Faktor unter 1,10")
    if m["return_pct"] < m["buy_hold_return_pct"]: reasons.append("Buy & Hold nicht erreicht")
    return reasons


def evaluate_period(df, strategy, lo, hi, fee=.001, slip=.0005):
    """4h sampled stops at next open; max 20% cash; no intrabar fill fantasy.

    Open positions contribute liquidation value, but never count as closed trades.
    First signal must originate inside the segment (warm-up may precede it).
    """
    entries, exits, _, _ = generate_signals(df.iloc[:hi], strategy)
    cash = 100.; qty = cost = entry = 0.; curve = []; trades = []
    peak = 100.; halted = False; risk_day = None; day_equity = 100.
    for i in range(lo, hi):
        bar = df.iloc[i]; price = float(bar.open)
        equity = cash + qty*price
        peak = max(peak, equity)
        day = int(bar.timestamp)//86_400_000
        if day != risk_day: risk_day, day_equity = day, equity
        daily_stop = equity <= day_equity*.97
        halted = halted or equity <= peak*.90
        if qty:
            if bool(exits.iloc[i-1]) or price <= entry*.98 or price >= entry*1.04 or halted or daily_stop:
                proceeds = qty*price*(1-slip)*(1-fee)
                trades.append({"net_pnl":proceeds-cost})
                cash += proceeds; qty = 0.
        elif i > lo and bool(entries.iloc[i-1]) and not halted and not daily_stop and cash >= 10:
            cost = cash*.20; entry = price*(1+slip); qty = cost/(entry*(1+fee)); cash -= cost
        curve.append({"timestamp":bar.timestamp,"equity":cash+qty*float(bar.close)*(1-slip)*(1-fee)})
    m = metrics(pd.DataFrame(curve),pd.DataFrame(trades),100.,"4h",df.iloc[lo:hi],fee,slip)
    m["open_at_end"] = bool(qty)
    return m


def build_report(df, now=None, fee=.001, slip=.0005):
    now = time.time() if now is None else now
    validate_candles(df, now)
    if len(df) < 1000: raise ValueError("Research requires >=1000 consecutive closed 4h candles; Kraken's 720-bar window is insufficient")
    n = len(df); a, b = int(n*.60), int(n*.80)
    results = []
    # Fixed parameters only. Selection happens before any holdout evaluation.
    for strategy in STRATEGIES:
        train = evaluate_period(df, strategy, 200, a, fee, slip)
        val = evaluate_period(df, strategy, a, b, fee, slip)
        reasons = ["Training: "+r for r in rejection_reasons(train)] + ["Validierung: "+r for r in rejection_reasons(val)]
        results.append({"strategy":strategy,"training":train,"validation":val,"reasons":reasons})
    eligible = [r for r in results if not r["reasons"]]
    winner = max(eligible, key=lambda r:r["validation"]["return_pct"]) if eligible else None
    holdout = evaluate_period(df, winner["strategy"], b, n, fee, slip) if winner else None
    return {"protocol":"atlas-fixed-v1","market":"BTC/EUR","timeframe":"4h",
            "created_at":now,"expires_at":now+30*86400,"data_end":int(df.timestamp.iloc[-1]/1000),
            "data_hash":hashlib.sha256(df.to_csv(index=False).encode()).hexdigest(),
            "strategy_hash":strategy_fingerprint(),"costs":[fee,slip],
            "risk":{"max_allocation":.20,"max_drawdown":.10,"daily_loss_limit":.03,"stop_loss":.02,"take_profit":.04},
            "boundaries":{"training_end":int(df.timestamp.iloc[a-1]),"validation_end":int(df.timestamp.iloc[b-1]),"holdout_end":int(df.timestamp.iloc[-1])},
            "candidates":results,"selected":winner["strategy"] if winner else None,"holdout":holdout,
            "note":"Holdout descriptive only. Never rerank on it. Refitting consumes a new preregistered dataset; not automatic rolling optimization."}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frozen BTC/EUR 4h study; no automatic re-optimization")
    parser.add_argument("csv", help="timestamp (UTC epoch ms),open,high,low,close,volume; BTC/EUR 4h only")
    args = parser.parse_args()
    if Path("strategy_report.json").exists(): raise SystemExit("Existing frozen report: archive and review a new research protocol before replacing")
    cfg = json.loads(Path("paper_config.json").read_text())
    atomic_json("strategy_report.json", build_report(pd.read_csv(args.csv),fee=cfg["fee_rate"],slip=cfg["slippage"]))
