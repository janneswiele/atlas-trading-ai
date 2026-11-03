"""Atlas v0.5: auditable, read-only BTC/EUR strategy diagnostics.

All diagnostics stop BEFORE the fixed final 20% holdout. This module never
writes a production strategy report, a paper ledger, or an exchange order.
It does not alter v0.4 admission thresholds or select a strategy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import atlas_research as historical
import atlas_research_recovery as recovery
from paper import STEP, validate_candles
from research import build_report, evaluate_period
from strategies import STRATEGIES

PROJECT = Path(__file__).resolve().parent
PROTECTED = (
    "paper_state.json", "paper_status.json", "paper_state.pre-v04.json",
    "strategy_report.json", "paper_config.json", "paper.py",
    ".github/workflows/atlas-paper.yml",
)
REPORT_NAME = "v05_diagnostics.json"


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def protected_hashes(root: Path = PROJECT) -> dict[str, str | None]:
    """Account fingerprints are checked before and after research (including absence)."""
    result = {}
    for filename in PROTECTED:
        p = root / filename
        result[filename] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    return result


def safe_output_dir(directory: Path, project: Path = PROJECT) -> Path:
    target = directory.resolve()
    project = project.resolve()
    if target == project or target in project.parents or target == project.parent:
        raise ValueError("Output directory cannot be the project root or its ancestor")
    for name in PROTECTED:
        if (target / name).exists():
            raise ValueError(f"Output directory contains protected file: {name}")
    return target


def validate_history(df: pd.DataFrame, asof: int) -> None:
    if len(df) < 1000:
        raise ValueError("At least 1000 consecutive real 4h candles required")
    validate_candles(df, asof)
    if not df.timestamp.is_monotonic_increasing or df.timestamp.duplicated().any():
        raise ValueError("Historical timestamps must be unique and sorted")


def passive_allocation_benchmark(segment: pd.DataFrame, allocation: float, fee: float, slip: float) -> float:
    """Buy at first open, sell at last close; fixed initial allocation, idle remainder.

    Returns NET percentage points on the full 100-EUR account. This is a
    comparable allocation baseline, not an equal-risk or identical-timing proof.
    """
    if len(segment) < 2 or not (0 <= allocation <= .20):
        raise ValueError("Bad passive benchmark segment/allocation")
    if not (0 <= fee < .01 and 0 <= slip < .01):
        raise ValueError("Bad cost settings")
    first, last = float(segment.open.iloc[0]), float(segment.close.iloc[-1])
    if not math.isfinite(first) or not math.isfinite(last) or min(first, last) <= 0:
        raise ValueError("Bad benchmark prices")
    investment = 100.0 * allocation
    units = investment / (first * (1 + slip) * (1 + fee))
    proceeds = units * last * (1 - slip) * (1 - fee)
    return (proceeds - investment)  # percentage points because cash starts at EUR 100


def predefined_blocks(n: int, warmup: int = 200, count: int = 4) -> tuple[int, list[tuple[int, int]]]:
    """Nonoverlapping sensitivity windows inside the first 80%; last 20% sealed."""
    if n < 1000 or count < 2 or warmup < 200:
        raise ValueError("Not enough data or invalid block configuration")
    holdout = int(n * .80)
    usable = holdout - warmup
    if usable < count * 40:
        raise ValueError("Insufficient pre-holdout coverage")
    points = [warmup + usable * i // count for i in range(count + 1)]
    result = list(zip(points[:-1], points[1:]))
    if result[0][0] != warmup or result[-1][1] != holdout or any(hi <= lo for lo, hi in result):
        raise AssertionError("Invalid block boundaries")
    return holdout, result


def build_diagnostics(df: pd.DataFrame, report: dict, fee: float, slip: float,
                      asof: int, source: str) -> dict:
    """No strategy ranking and NO holdout metrics. No refitting and no parameters."""
    validate_history(df, asof)
    if report.get("market") != "BTC/EUR" or report.get("timeframe") != "4h":
        raise ValueError("Incompatible base research report")
    n = len(df)
    holdout, blocks = predefined_blocks(n)
    train_end = int(n * .60)
    assert blocks[-1][1] == holdout and train_end < holdout
    cfg = json.loads((PROJECT / "paper_config.json").read_text())
    if fee != float(cfg["fee_rate"]) or slip != float(cfg["slippage"]):
        raise ValueError("Research costs must match paper configuration")
    selected = report.get("selected")
    results = []
    for strategy in STRATEGIES:
        candidate = next((x for x in report["candidates"] if x["strategy"] == strategy), None)
        if candidate is None:
            raise ValueError("Base report missing fixed strategy")
        folds = []
        for i, (lo, hi) in enumerate(blocks, 1):
            metric = evaluate_period(df, strategy, lo, hi, fee, slip)
            benchmark = passive_allocation_benchmark(df.iloc[lo:hi], .20, fee, slip)
            folds.append({
                "block": i, "start_utc": _iso(int(df.timestamp.iloc[lo] // 1000)),
                "end_utc": _iso(int(df.timestamp.iloc[hi-1] // 1000)),
                "candles": hi - lo, "closed_trades": metric["trades"],
                "strategy_return_pct": metric["return_pct"],
                "strategy_max_drawdown_pct": metric["max_drawdown_pct"],
                "passive_20pct_return_pct": benchmark,
                "difference_vs_passive_pct_points": metric["return_pct"] - benchmark,
            })
        sensitivity = {}
        for label, factor in (("base_cost", 1), ("double_cost", 2), ("triple_cost", 3)):
            if fee * factor >= .01 or slip * factor >= .01:
                raise ValueError("Cost stress exceeds supported limits")
            val = evaluate_period(df, strategy, train_end, holdout, fee * factor, slip * factor)
            sensitivity[label] = {"net_return_pct": val["return_pct"], "closed_trades": val["trades"],
                                  "max_drawdown_pct": val["max_drawdown_pct"]}
        training = candidate["training"]
        validation = candidate["validation"]
        results.append({
            "strategy": strategy,
            "qualified_in_original_training_validation": bool(selected == strategy),
            "original_rejection_reasons": candidate["reasons"],
            "training_closed_trades": training["trades"],
            "validation_closed_trades": validation["trades"],
            "training_20pct_passive_return_pct": passive_allocation_benchmark(df.iloc[200:train_end], .20, fee, slip),
            "validation_20pct_passive_return_pct": passive_allocation_benchmark(df.iloc[train_end:holdout], .20, fee, slip),
            "training_strategy_return_pct": training["return_pct"],
            "validation_strategy_return_pct": validation["return_pct"],
            "train_trade_deficit_to_10": max(0, 10 - training["trades"]),
            "validation_trade_deficit_to_10": max(0, 10 - validation["trades"]),
            "pre_holdout_sensitivity_blocks": folds,
            "validation_cost_stress": sensitivity,
            "blocks_profitable": sum(b["strategy_return_pct"] > 0 for b in folds),
        })
    return {
        "version": "0.5.0", "report_type": "READ_ONLY_DIAGNOSTICS",
        "paper_trading_authorized": False, "live_trading_authorized": False,
        "market": "BTC/EUR", "timeframe": "4h", "data_source": source,
        "last_closed_candle_start_utc": _iso(int(df.timestamp.iloc[-1] // 1000)),
        "candle_count": n, "history_days": n * 4 / 24,
        "data_sha256": hashlib.sha256(df.to_csv(index=False).encode()).hexdigest(),
        "existing_selected_strategy": selected,
        "all_existing_rejection_rules_unchanged": True,
        "holdout_start_index": holdout,
        "holdout_candles": n - holdout,
        "holdout_used_for_diagnostics": False,
        "blocked_until_independent_validation": True,
        "benchmark_details": "20% initial cash passive BTC, 80% idle, both-side fee and slippage, no rebalancing. Illustrative comparison, not identical market risk.",
        "stress_details": "Same strategy and candle boundaries with base, 2x, 3x fee and slippage; sensitivity only, not new entry rules.",
        "fold_details": "Four fixed nonoverlapping blocks in first 80% of observations. These blocks overlap the original train/validation periods and are not independent out-of-sample holdout.",
        "strategies": results,
        "warnings": [
            "Research uses Coinbase public BTC/EUR candles; paper engine uses Kraken quotes.",
            "175 days of data is insufficient for a strong profitability claim across market regimes.",
            "No automated authorization, real orders, parameter search or holdout-based selection.",
            "The existing >=10 closed trades, net-profit, drawdown, profit-factor and buy/hold admission gates stay unchanged.",
        ],
    }


def _atomic_text(path: Path, content: str) -> None:
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _summary(diag: dict) -> str:
    lines = [
        "ATLAS TRADING AI v0.5 — DIAGNOSTISCHER FORSCHUNGSBERICHT",
        "KEINE HANDELSFREIGABE / KEINE ECHTEN TRADES / KEINE KONTOAENDERUNG",
        "",
        f"Daten: {diag['candle_count']} echte aufeinanderfolgende 4h-Kerzen BTC/EUR (Coinbase)",
        f"Letzte Kerze (UTC): {diag['last_closed_candle_start_utc']}",
        f"Historischer Forschungskandidat: {diag['existing_selected_strategy'] or 'KEINER'}",
        f"Letzte {diag['holdout_candles']} Kerzen (20%): nicht fuer v0.5-Sensitivitaet genutzt",
        "",
        "Strategie                 Training  Validierung  Bloecke im Plus  Validierung mit 3x Kosten",
    ]
    for s in diag["strategies"]:
        lines.append(f"{s['strategy']:<25} {s['training_closed_trades']:>3} Trades   "
                     f"{s['validation_closed_trades']:>3} Trades      "
                     f"{s['blocks_profitable']}/4          "
                     f"{s['validation_cost_stress']['triple_cost']['net_return_pct']:>+7.3f}%")
    lines += ["", "WICHTIG: 20%-Buy-and-Hold ist nur ein fairerer Kapitaleinsatz-Vergleich,",
              "KEIN Beweis fuer gleiche Risikoexposition oder Profitabilitaet.",
              "Die vier Bloecke testen nur Sensitivitaet vor dem letzten Holdout.",
              "Alle Freigabe- und Risikoregeln bleiben unveraendert.",
              "Niemals CANDIDATE nach strategy_report.json umbenennen.", ""]
    return "\n".join(lines)


def run(output: Path, csv: Path | None = None, days: int = 175, now: int | None = None) -> dict:
    """Run snapshot or network research; write only to a dedicated output directory."""
    output = safe_output_dir(output)
    before = protected_hashes()
    output.mkdir(parents=True, exist_ok=True)
    if csv is None:
        now = int(time.time() if now is None else now)
        candidate, _ = historical.research_to_directory(output, now=now, days=days,
                                                        fetch_fn=recovery.recover_window)
        df = pd.read_csv(output / "coinbase_btc_eur_4h.csv")
        source = "Coinbase 1h OHLCV, missing 1h repaired only with 4 genuine Coinbase 15m bars"
        asof = now
    else:
        df = pd.read_csv(csv)
        # Archived offline runs validate against the first instant after final 4h close;
        # they must never be treated as current trading approvals.
        asof = int(df.timestamp.iloc[-1] // 1000) + STEP + 1
        if asof > time.time() + 300:
            raise ValueError("Offline dataset includes unfinished future candles")
        validate_history(df, asof)
        cfg = json.loads((PROJECT / "paper_config.json").read_text())
        candidate = build_report(df, now=asof, fee=cfg["fee_rate"], slip=cfg["slippage"])
        candidate.update(source="Archived BTC-EUR CSV (provenance must be independently verified)",
                         source_timeframe="1h aggregated to 4h", manual_review_required=True,
                         live_trading_approved=False,
                         warning="ARCHIVED RESEARCH ONLY. Never use as strategy_report.json.")
        source = "Archived CSV BTC/EUR (provenance must be checked independently)"
        destination = output / "coinbase_btc_eur_4h.csv"
        if csv.resolve() != destination.resolve():
            shutil.copyfile(csv, destination)  # preserve raw historical bytes and audit provenance
        _atomic_text(output / "strategy_report_CANDIDATE.json", json.dumps(candidate, indent=2, allow_nan=False) + "\n")
    cfg = json.loads((PROJECT / "paper_config.json").read_text())
    diag = build_diagnostics(df, candidate, float(cfg["fee_rate"]), float(cfg["slippage"]), asof, source)
    diag["saved_csv_sha256"] = hashlib.sha256((output / "coinbase_btc_eur_4h.csv").read_bytes()).hexdigest()
    _atomic_text(output / REPORT_NAME, json.dumps(diag, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    _atomic_text(output / "SUMMARY_DE.txt", _summary(diag))
    after = protected_hashes()
    if before != after:
        raise RuntimeError("Protected account or production file changed; inspect repository")
    return diag


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Atlas v0.5 strategy diagnostics; no trading or approval")
    parser.add_argument("--csv", type=Path, default=None, help="Use existing REAL verified 4h history offline")
    parser.add_argument("--days", type=int, default=175, help="Fetch this many days from Coinbase (>=168)")
    parser.add_argument("--output", type=Path, default=Path("atlas-v05-results"))
    args = parser.parse_args()
    result = run(args.output, csv=args.csv, days=args.days)
    print(f"Atlas v0.5: {result['candle_count']} real 4h bars; {len(result['strategies'])} fixed strategies tested.")
    print(f"Existing admission result: {result['existing_selected_strategy'] or 'NONE'}. No approval or account change.")
    print(f"Diagnostics written to {args.output}/{REPORT_NAME}")


if __name__ == "__main__":
    main()
