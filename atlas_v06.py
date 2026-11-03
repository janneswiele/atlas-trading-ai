"""Atlas v0.6: long-history BTC/EUR research; NEVER authorizes any trading.

Collects public Coinbase Exchange BTC-EUR hourly OHLCV using paged requests,
retries missing hours, and reconstructs an hour only from four GENUINE 15m
Coinbase candles. Hours not verifiable stay MISSING. Incomplete 4h candles are
omitted and all gaps split independent contiguous research segments.

Evaluates only the four existing fixed strategies. Chronological, nonoverlapping
validation windows are preceded by training windows; the latest 20% of EACH
qualifying contiguous segment are sealed. Results are diagnostic ONLY; even
perfect results do not write strategy_report.json or change paper trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

import atlas_research as cb
import atlas_research_recovery as repair
import atlas_v05 as v05
from paper import STEP
from research import evaluate_period, rejection_reasons
from strategies import STRATEGIES

HOUR = 3600
QUARTER = 900
PER_REQUEST_HOURS = 240  # Coinbase Exchange hard cap is 300 candles/request
DEFAULT_DAYS = 730
MIN_DAYS = 365
MAX_DAYS = 1095
MIN_SEGMENT_4H = 1000
MAX_MISSING_FRACTION = 0.005  # Data quality check; never a trading risk setting.
REPORT = "v06_research.json"
PROJECT = Path(__file__).resolve().parent
PROTECTED = v05.PROTECTED
EXPECTED_RISK = {
    "trading_enabled": True,
    "max_allocation": .20,
    "max_positions": 1,
    "fee_rate": .001,
    "slippage": .0005,
    "max_drawdown": .10,
    "daily_loss_limit": .03,
    "stop_loss": .02,
    "take_profit": .04,
}
SOURCE = "Coinbase Exchange public BTC-EUR OHLCV, UTC hourly, 15m verified recovery"
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def iso(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finite(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid {label} type")
    f = float(value)
    if not math.isfinite(f):
        raise ValueError(f"Non-finite {label}")
    return f


def check_hour(row: tuple | list, left: int, right: int) -> tuple:
    if len(row) != 6:
        raise ValueError("Hour must have six OHLCV fields")
    ts, op, high, low, close, volume = row
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or int(ts) != ts:
        raise ValueError("Invalid hourly timestamp")
    ts = int(ts)
    if ts % HOUR or not left <= ts < right:
        raise ValueError("Hourly candle is unaligned or out of requested range")
    op, high, low, close, volume = [_finite(x, name) for x, name in zip(
        (op, high, low, close, volume), ("open", "high", "low", "close", "volume"))]
    if min(op, low, close) <= 0 or high < max(op, close, low) or low > min(op, close) or volume < 0:
        raise ValueError("Impossible genuine hourly OHLCV")
    return (ts, op, high, low, close, volume)


def verified_quarters(ts: int, values: dict) -> bool:
    """Refuse malformed 15m providers; False means genuine quarter(s) absent."""
    if not isinstance(values, dict):
        raise ValueError("Invalid quarter-hour response")
    if sorted(values) != [ts + i * QUARTER for i in range(4)]:
        return False
    for start, row in values.items():
        if not isinstance(row, (tuple, list)) or len(row) != 6 or row[0] != start:
            raise ValueError("Conflicting quarter-hour timestamp")
        # Convert 15m bucket onto standard OHLC validation without claiming 1h alignment.
        _, op, high, low, close, volume = row
        op, high, low, close, volume = [_finite(x, n) for x, n in zip(
            (op, high, low, close, volume), ("open", "high", "low", "close", "volume"))]
        if min(op, low, close) <= 0 or high < max(op, low, close) or low > min(op, close) or volume < 0:
            raise ValueError("Impossible genuine 15-minute candle")
    return True


def verify_unchanged_config(cfg: dict) -> None:
    """A reported 'unchanged' risk policy must match the frozen v0.4 values."""
    if set(cfg) != set(EXPECTED_RISK) or any(type(cfg[k]) is not type(value) or cfg[k] != value
                                            for k, value in EXPECTED_RISK.items()):
        raise ValueError("Paper risk config differs from the frozen v0.4 settings; abort research")


def parse_window(rows: list, left: int, right: int) -> dict[int, tuple]:
    """Validate even injected test/alternate fetchers; refuse conflicts."""
    found = {}
    for raw in rows:
        row = check_hour(raw, left, right)
        if row[0] in found and found[row[0]] != row:
            raise ValueError("Conflicting genuine candles in provider response")
        found[row[0]] = row
    return found


def collect_hourly(left: int, right: int, *,
                   hour_fn: Callable | None = None,
                   quarter_fn: Callable | None = None,
                   sleep_fn: Callable[[float], None] = time.sleep,
                   max_missing_fraction: float = MAX_MISSING_FRACTION) -> tuple[pd.DataFrame, dict]:
    """Fetch an aligned period. Unrecoverable gaps remain gaps (never interpolated)."""
    if left % HOUR or right % HOUR or right <= left:
        raise ValueError("Historical UTC bounds must be aligned hours")
    required = (right - left) // HOUR
    if required > MAX_DAYS * 24:
        raise ValueError("Requested history exceeds bounded maximum")
    if not 0 <= max_missing_fraction <= MAX_MISSING_FRACTION:
        raise ValueError("Cannot weaken data-quality missing fraction")
    hour_fn = hour_fn or cb._fetch_window
    quarter_fn = quarter_fn or repair.fetch_quarters
    found: dict[int, tuple] = {}
    origins: dict[int, str] = {}
    retry_count = 0
    reconstruction_count = 0
    unresolved: list[int] = []
    windows = 0
    for start in range(left, right, PER_REQUEST_HOURS * HOUR):
        stop = min(start + PER_REQUEST_HOURS * HOUR, right)
        raw = parse_window(hour_fn(start, stop), start, stop)
        windows += 1
        for ts, row in raw.items():
            if ts in found and found[ts] != row:
                raise ValueError("Overlapping provider windows conflict")
            found[ts] = row
            origins[ts] = "coinbase_1h"
        for ts in range(start, stop, HOUR):
            if ts in found:
                continue
            retried = parse_window(hour_fn(ts, ts + HOUR), ts, ts + HOUR)
            if ts in retried:
                found[ts] = retried[ts]
                origins[ts] = "coinbase_1h_retry"
                retry_count += 1
                continue
            # The recovery implementation refuses bad/partial OHLCV. A missing
            # 15m quarter is an unrepairable market-data gap, not an excuse to
            # synthesize prices. Transport errors and malformed rows propagate.
            quarters = quarter_fn(ts, ts + HOUR)
            if not verified_quarters(ts, quarters):
                unresolved.append(ts)
                continue
            recovered = repair.aggregate_hour(ts, quarters)
            found[ts] = check_hour(recovered, ts, ts + HOUR)
            origins[ts] = "four_verified_coinbase_15m"
            reconstruction_count += 1
        if stop < right:
            sleep_fn(.35)
    actual_unresolved = [ts for ts in range(left, right, HOUR) if ts not in found]
    if actual_unresolved != unresolved:
        raise RuntimeError("Missing-hour audit mismatch")
    if len(actual_unresolved) / required > max_missing_fraction:
        raise ValueError(f"Unresolved data gaps exceed {max_missing_fraction:.2%} audit cap: "
                         f"{len(actual_unresolved)}/{required} hours; first {iso(actual_unresolved[0])}")
    values = [(*found[ts], origins[ts]) for ts in sorted(found)]
    result = pd.DataFrame(values, columns=COLUMNS + ["source"])
    audit = {
        "provider": SOURCE,
        "product": "BTC-EUR",
        "start_utc": iso(left), "end_exclusive_utc": iso(right),
        "hourly_buckets_expected": required,
        "hourly_buckets_verified": len(result),
        "missing_hourly_buckets": len(actual_unresolved),
        "missing_hour_starts_utc": [iso(t) for t in actual_unresolved],
        "verified_1h_retries": retry_count,
        "verified_15m_reconstructions": reconstruction_count,
        "paged_requests": windows,
        "unresolved_fraction": len(actual_unresolved) / required,
        "missing_fraction_cap": max_missing_fraction,
        "never_interpolated": True,
        "primary_data_provenance": "Coinbase public REST; not independently cross-checked against another exchange",
    }
    return result, audit


def aggregate_verified_4h(hourly: pd.DataFrame, left: int, right: int) -> tuple[pd.DataFrame, list[int]]:
    """Drop every incomplete four-hour candle, preserving exact real-data gaps."""
    if left % STEP or right % STEP or left >= right:
        raise ValueError("4h aggregations require 4h UTC bounds")
    if any(c not in hourly.columns for c in COLUMNS):
        raise ValueError("Missing hourly columns")
    seen = {}
    for raw in hourly[COLUMNS].itertuples(index=False, name=None):
        row = check_hour(raw, left, right)
        if row[0] in seen:
            raise ValueError("Duplicate hourly candle")
        seen[row[0]] = row
    output = []
    skipped = []
    for start in range(left, right, STEP):
        required = [start + i * HOUR for i in range(4)]
        if not all(t in seen for t in required):
            skipped.append(start)
            continue
        rows = [seen[t] for t in required]
        output.append((start * 1000, rows[0][1], max(x[2] for x in rows),
                       min(x[3] for x in rows), rows[-1][4], sum(x[5] for x in rows)))
    return pd.DataFrame(output, columns=COLUMNS), skipped


def validate_4h_rows(df: pd.DataFrame, now: int | None = None) -> None:
    if df.empty or any(c not in df.columns for c in COLUMNS):
        raise ValueError("Missing actual verified 4h candles")
    last = None
    for row in df[COLUMNS].itertuples(index=False, name=None):
        ts, op, high, low, close, vol = row
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or int(ts) != ts:
            raise ValueError("Invalid 4h timestamp")
        ts = int(ts)
        if ts % (STEP * 1000) or (last is not None and ts <= last):
            raise ValueError("Duplicate, unordered or unaligned 4h timestamp")
        if now is not None and ts // 1000 + STEP > now:
            raise ValueError("Historical dataset contains unfinished/future candles")
        op, high, low, close, vol = (_finite(x, name) for x, name in zip(
            (op, high, low, close, vol), ("open", "high", "low", "close", "volume")))
        if min(op, low, close) <= 0 or high < max(op, low, close) or low > min(op, close) or vol < 0:
            raise ValueError("Impossible 4h OHLCV")
        last = ts


def contiguous_segments(df: pd.DataFrame) -> list[pd.DataFrame]:
    """NEVER pass a gap-spanning frame to any backtest or strategy signal."""
    validate_4h_rows(df)
    boundary = (df.timestamp.diff().fillna(STEP * 1000) != STEP * 1000).cumsum()
    return [grp.reset_index(drop=True) for _, grp in df.groupby(boundary, sort=True)]


def walkforward_windows(n: int, warmup: int = 200) -> tuple[int, list[tuple[int, int]]]:
    """Anchored walk-forward; validation windows disjoint, final 20% sealed."""
    if n < MIN_SEGMENT_4H or warmup < 200:
        raise ValueError("Insufficient contiguous data for walk-forward research")
    sealed_start = int(n * .80)
    first_validation = max(400, int(n * .25))
    available = sealed_start - first_validation
    if first_validation <= warmup or available < 180:
        raise ValueError("No sufficient independent validation history")
    folds = min(5, max(1, available // 250))
    boundaries = [first_validation + available * i // folds for i in range(folds + 1)]
    windows = list(zip(boundaries[:-1], boundaries[1:]))
    if any(lo < first_validation or hi > sealed_start or hi-lo < 180 for lo,hi in windows):
        raise AssertionError("Overlapping or undersized validation windows")
    return sealed_start, windows


def independent_diagnostics(df: pd.DataFrame, fee: float, slip: float,
                            *, source: str, data_audit: dict) -> dict:
    """Fixed-strategy research, no ranking with sealed holdouts and no approval.

    `research.rejection_reasons` is reused unchanged, including its strict
    100%-Buy/Hold gate. The 20%-passive comparison is additional diagnostics.
    """
    validate_4h_rows(df)
    cfg = json.loads((PROJECT / "paper_config.json").read_text())
    verify_unchanged_config(cfg)
    if fee != cfg["fee_rate"] or slip != cfg["slippage"]:
        raise ValueError("Research costs differ from immutable paper configuration")
    pieces = contiguous_segments(df)
    eligible = []
    excluded = []
    segments = []
    for i, frame in enumerate(pieces, 1):
        meta = {"index": i, "candles": len(frame),
                "start_utc": iso(int(frame.timestamp.iloc[0] // 1000)),
                "end_utc": iso(int(frame.timestamp.iloc[-1] // 1000))}
        if len(frame) < MIN_SEGMENT_4H:
            excluded.append({**meta, "reason": "Fewer than 1000 consecutive verified 4h candles"})
        else:
            eligible.append((meta, frame))
        segments.append(meta)
    # Archived/offline/synthetic candles cannot become a positive research
    # candidate merely because they pass numerical checks.
    provenance_sufficient = (
        data_audit.get("provider") == SOURCE and
        data_audit.get("never_interpolated") is True and
        isinstance(data_audit.get("hourly_buckets_verified"), int) and
        data_audit.get("unresolved_fraction", 1.0) <= MAX_MISSING_FRACTION and
        not data_audit.get("offline_data_cannot_authorize_trading", False)
    )
    strategy_records = []
    all_validation_count = 0
    for strategy in STRATEGIES:
        series = []
        for meta, frame in eligible:
            sealed, windows = walkforward_windows(len(frame))
            folds = []
            all_validation_count += len(windows) if strategy == STRATEGIES[0] else 0
            for fold_id, (lo, hi) in enumerate(windows, 1):
                # Prior-close signals are filled no earlier than following open.
                training = evaluate_period(frame, strategy, 200, lo, fee, slip)
                validation = evaluate_period(frame, strategy, lo, hi, fee, slip)
                training_reasons = rejection_reasons(training)
                validation_reasons = rejection_reasons(validation)
                passive = v05.passive_allocation_benchmark(frame.iloc[lo:hi], .20, fee, slip)
                folds.append({
                    "fold": fold_id, "training_candles": lo - 200,
                    "validation_candles": hi - lo,
                    "training_start_utc": iso(int(frame.timestamp.iloc[200] // 1000)),
                    "validation_start_utc": iso(int(frame.timestamp.iloc[lo] // 1000)),
                    "validation_end_utc": iso(int(frame.timestamp.iloc[hi-1] // 1000)),
                    "training_trades": training["trades"],
                    "validation_trades": validation["trades"],
                    "training_return_pct": training["return_pct"],
                    "validation_return_pct": validation["return_pct"],
                    "validation_drawdown_pct": validation["max_drawdown_pct"],
                    "validation_profit_factor": validation["profit_factor"],
                    "validation_buy_hold_100pct_return_pct": validation["buy_hold_return_pct"],
                    "validation_passive_20pct_return_pct": passive,
                    "validation_vs_passive_20pct_points": validation["return_pct"]-passive,
                    "training_rejection_reasons": training_reasons,
                    "validation_rejection_reasons": validation_reasons,
                    "passes_unchanged_rules": not (training_reasons or validation_reasons),
                })
            lo, hi = windows[-1]
            stress = {}
            for multiplier in (1, 2, 3):
                val = evaluate_period(frame, strategy, lo, hi, fee * multiplier, slip * multiplier)
                stress[f"{multiplier}x_costs"] = {
                    "return_pct": val["return_pct"], "trades": val["trades"],
                    "max_drawdown_pct": val["max_drawdown_pct"]}
            series.append({
                "segment": meta,
                "sealed_holdout_start_utc": iso(int(frame.timestamp.iloc[sealed] // 1000)),
                "sealed_holdout_candles": len(frame)-sealed,
                "sealed_holdout_evaluated": False,
                "validation_windows": folds,
                "last_validation_window_cost_stress": stress,
            })
        record_folds = [fold for seg in series for fold in seg["validation_windows"]]
        sufficiency = len(eligible)>=2 and len(record_folds)>=3
        qualified = provenance_sufficient and sufficiency and all(
            x["passes_unchanged_rules"] for x in record_folds)
        strategy_records.append({
            "strategy": strategy,
            "segments_evaluated": len(series),
            "validation_windows": len(record_folds),
            "total_validation_trades": sum(f["validation_trades"] for f in record_folds),
            "passing_windows": sum(f["passes_unchanged_rules"] for f in record_folds),
            "qualifies_for_manual_review_only": qualified,
            "meets_minimum_independent_windows": sufficiency,
            "segment_results": series,
        })
    candidates = [x["strategy"] for x in strategy_records if x["qualifies_for_manual_review_only"]]
    return {
        "version": "0.6.0", "type": "READ_ONLY_LONG_HISTORY_RESEARCH",
        "market": "BTC/EUR", "bar_interval": "4h", "source": source,
        "research_candles": len(df),
        "research_start_utc": iso(int(df.timestamp.iloc[0] // 1000)),
        "research_end_utc": iso(int(df.timestamp.iloc[-1] // 1000)),
        "data_sha256": hashlib.sha256(df.to_csv(index=False).encode()).hexdigest(),
        "data_audit": data_audit,
        "source_sufficient_for_manual_research_review": provenance_sufficient,
        "all_contiguous_segments": segments,
        "excluded_short_segments": excluded,
        "eligible_segments": len(eligible),
        "disjoint_pre_holdout_validation_windows": all_validation_count,
        "sealed_holdouts_all_untouched": True,
        "strategy_fixed_parameter_search": False,
        "automatic_strategy_selection": False,
        "strategy_report_json_written": False,
        "trading_or_paper_authorized": False,
        "actual_trades_executed": 0,
        "risk_rules_unchanged": True,
        "fixed_unchanged_risk_parameters": {k: cfg[k] for k in (
            "max_allocation", "max_positions", "max_drawdown", "daily_loss_limit",
            "stop_loss", "take_profit", "fee_rate", "slippage")},
        "candidates_for_manual_review_only": candidates,
        "strategies": strategy_records,
        "warnings": [
            "Coinbase candles are internally validated but NOT independently confirmed by Kraken or another exchange.",
            "Missing candles were never fabricated. Incomplete 4h buckets were omitted; backtests never span missing 4h buckets.",
            "Validation windows are disjoint chronologically, but not statistically independent; all are historical simulations.",
            "The final 20% of each sufficiently long uninterrupted segment remain sealed; no holdout metrics reported.",
            "All four strategies were predetermined; no parameters were optimized. Repeated research may still overfit.",
            "Original training/validation rejection thresholds have NOT been modified; 20%-passive benchmark is diagnostic only.",
            "No production strategy authorization: even passing research windows require manual review and separate forward paper testing.",
            "Kraken paper quote execution can differ from historical Coinbase prices and assumed fills.",
        ],
    }


def _atomic_text(path: Path, data: str) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def summary_de(report: dict) -> str:
    s = ["ATLAS v0.6 — MEHRJAEHRIGE BTC/EUR-FORSCHUNG (NUR SIMULATION)",
         "KEINE HANDELSFREIGABE, KEINE KONTOVERAENDERUNG, KEINE ECHTEN ORDERS", "",
         f"Datenquelle: {report['source']}",
         f"Verifizierte 4h-Kerzen: {report['research_candles']}",
         f"Zeitraum: {report['research_start_utc']} bis {report['research_end_utc']}",
         f"Zusammenhaengende Abschnitte >=1000 Kerzen: {report['eligible_segments']}",
         f"Getrennte Vorab-Validierungsfenster: {report['disjoint_pre_holdout_validation_windows']}",
         "", "Strategie | Val.-Trades | Erfolgreiche Fenster/Gesamt | Manuelle Pruefung",]
    for row in report["strategies"]:
        s.append(f"{row['strategy']:<16} | {row['total_validation_trades']:>3} | "
                 f"{row['passing_windows']}/{row['validation_windows']} | "
                 f"{'NUR KANDIDAT' if row['qualifies_for_manual_review_only'] else 'NEIN'}")
    s += ["", "Alle Testabschnitte, Kursluecken, Quellen und Kosten im JSON-Bericht.",
          "Ungepruefte Zeitraeume oder fehlende Kerzen werden nicht aufgefuellt.",
          "Nicht als strategy_report.json speichern oder umbenennen.",
          "Keine Echtgeldfreigabe. Ohne bestehende Freigabe kauft paper.py weiterhin nicht.", ""]
    return "\n".join(s)


def run(output: Path, *, days: int = DEFAULT_DAYS, csv: Path | None = None,
        now: int | None = None, hour_fn: Callable | None = None,
        quarter_fn: Callable | None = None,
        sleep_fn: Callable[[float], None] = time.sleep) -> dict:
    """Only output directory files may change; assert fingerprints of account files."""
    root = PROJECT
    output = v05.safe_output_dir(output, project=root)
    before = v05.protected_hashes(root)
    if csv is not None:
        # CSV mode allows OFFLINE algorithm regression tests only. The file
        # provenance is NOT independently verifiable by simply reading it.
        frame = pd.read_csv(csv)
        validate_4h_rows(frame, now=int(time.time()) if now is None else int(now))
        audit = {"provider": "Supplied archived 4h CSV", "origin_verified": False,
                 "original_file_sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
                 "missing_hours_unknown": True, "offline_data_cannot_authorize_trading": True}
        source = "USER-SUPPLIED ARCHIVE / PROVENANCE UNCONFIRMED"
        hourly = None
    else:
        if isinstance(days, bool) or not isinstance(days, int) or not MIN_DAYS <= days <= MAX_DAYS:
            raise ValueError(f"Long history requires {MIN_DAYS}-{MAX_DAYS} full days")
        actual_now = int(time.time() if now is None else now)
        right = (actual_now // STEP) * STEP
        left = right - days * 86400
        hourly, audit = collect_hourly(left, right, hour_fn=hour_fn,
                                       quarter_fn=quarter_fn, sleep_fn=sleep_fn)
        frame, skipped = aggregate_verified_4h(hourly, left, right)
        audit["omitted_incomplete_4h_buckets"] = len(skipped)
        audit["omitted_4h_starts_utc"] = [iso(t) for t in skipped]
        audit["complete_4h_buckets"] = len(frame)
        audit["expected_4h_buckets"] = (right-left) // STEP
        validate_4h_rows(frame, now=actual_now)
        source = SOURCE
    cfg = json.loads((root / "paper_config.json").read_text())
    verify_unchanged_config(cfg)
    report = independent_diagnostics(frame, float(cfg["fee_rate"]),
                                     float(cfg["slippage"]), source=source,
                                     data_audit=audit)
    # Guarantee research is a self-contained non-production folder.
    output.mkdir(parents=True, exist_ok=True)
    _atomic_text(output / "btc_eur_4h_research.csv", frame.to_csv(index=False))
    if hourly is not None:
        _atomic_text(output / "btc_eur_1h_audited.csv", hourly.to_csv(index=False))
    report["saved_4h_file_sha256"] = hashlib.sha256((output / "btc_eur_4h_research.csv").read_bytes()).hexdigest()
    _atomic_text(output / REPORT, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    _atomic_text(output / "SUMMARY_DE.txt", summary_de(report))
    after = v05.protected_hashes(root)
    if before != after:
        raise RuntimeError("Protected account/strategy/config/workflow changed during research")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Atlas 0.6 long-history read-only BTC/EUR research")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS,
                   help="Coinbase history length, 365..1095 days; default: 730")
    p.add_argument("--output", type=Path, default=Path("atlas-research-output"))
    p.add_argument("--csv", type=Path, default=None,
                   help="Offline diagnostics from CSV only; provenance unverified, NEVER authorizes trading")
    args = p.parse_args()
    result = run(args.output, days=args.days, csv=args.csv)
    provenance = "archived 4h candles (origin UNVERIFIED)" if args.csv else "Coinbase-audited real 4h candles"
    print(f"Atlas v0.6 finished: {result['research_candles']} {provenance}, "
          f"{result['eligible_segments']} contiguous segments, "
          f"{result['disjoint_pre_holdout_validation_windows']} temporal validation windows.")
    print(f"Manual-review-only candidates: {result['candidates_for_manual_review_only'] or 'NONE'}. "
          "No trading authorization or account change.")
    print(f"Research results: {args.output / REPORT}")


if __name__ == "__main__":
    main()
