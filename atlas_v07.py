"""Atlas Trading AI v0.7: read-only historical strategy VALIDATION.

Extends v0.6's real Coinbase BTC/EUR 4h research. Checks the recent subset
against independent Kraken BTC/EUR 4h closes (public REST, up to 720 candles).
Uses fixed, disjoint, approximately 60-day validation blocks strictly before
v0.6's sealed final 20% of EACH continuous verified historical segment.

Never modifies trading, risk, paper account, production strategy report or the
paper workflow. Its output is NOT a strategy authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

import atlas_v05 as v05
import atlas_v06 as v06
from paper import STEP
from research import evaluate_period, rejection_reasons
from strategies import STRATEGIES

PROJECT = Path(__file__).resolve().parent
REPORT = "v07_validation.json"
SUMMARY = "SUMMARY_V07_DE.txt"
KRAKEN_CSV = "kraken_btc_eur_recent_4h.csv"
COMPARISON_CSV = "coinbase_kraken_comparison_4h.csv"
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC?pair=XBTEUR&interval=240"
KRAKEN_SOURCE = "Kraken public REST OHLC BTC/EUR 240m; recent <=720 candles only"
VALIDATION_BARS = 360         # 60 days of 4h candles: fixed before outcomes are known
FIRST_VALIDATION = 400       # first 200 bars warmup + 200 bars initial training
REGIME_LOOKBACK = 200        # prior data only; no validation/holdout lookahead
MAX_CLOSE_DIFFERENCE_PCT = 1.5
MIN_OVERLAP = 200
MIN_COVERAGE = 0.95
MAX_KRAKEN_GAP_FRACTION = .02
MAX_FRESHNESS_SECONDS = STEP * 3


def _json_atomic(path: Path, value: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _text_atomic(path: Path, value: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def kraken_rows(payload: dict, now: int) -> pd.DataFrame:
    """Parse independently fetched Kraken candles. Exclude current unclosed 4h bar.

    Kraken OHLC fields: [UTC epoch seconds, open, high, low, close, vwap,
    volume, count]. Validation is strict; it does NOT reconcile mismatches.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise ValueError("Malformed Kraken OHLC response")
    if payload.get("error") != []:
        raise ValueError("Kraken OHLC API signalled an error")
    series = [v for k, v in payload["result"].items() if k != "last"]
    if len(series) != 1 or not isinstance(series[0], list):
        raise ValueError("Expected exactly one Kraken BTC/EUR OHLC series")
    found = {}
    for item in series[0]:
        if not isinstance(item, (tuple, list)) or len(item) < 8:
            raise ValueError("Malformed Kraken candle")
        try:
            raw_ts = float(item[0])
        except (ValueError, TypeError, OverflowError) as e:
            raise ValueError("Invalid Kraken timestamp") from e
        if not math.isfinite(raw_ts) or int(raw_ts) != raw_ts:
            raise ValueError("Invalid Kraken timestamp")
        ts = int(raw_ts)
        if ts % STEP:
            raise ValueError("Unaligned Kraken four-hour candle")
        if ts + STEP > now:
            continue  # unclosed final candle is explicitly excluded
        try:
            op, high, low, close, volume = [float(item[i]) for i in (1, 2, 3, 4, 6)]
        except (ValueError, TypeError, OverflowError) as e:
            raise ValueError("Invalid Kraken OHLC values") from e
        if any(not math.isfinite(x) for x in (op, high, low, close, volume)):
            raise ValueError("Non-finite Kraken OHLC values")
        if min(op, high, low, close) <= 0 or high < max(op, close) or low > min(op, close) or volume < 0:
            raise ValueError("Impossible Kraken OHLC values")
        if ts in found:
            raise ValueError("Duplicated Kraken candle timestamp")
        found[ts] = (ts * 1000, op, high, low, close, volume)
    frame = pd.DataFrame([found[ts] for ts in sorted(found)], columns=v06.COLUMNS)
    if frame.empty:
        raise ValueError("Kraken returned no closed four-hour candles")
    v06.validate_4h_rows(frame, now)
    return frame


def fetch_kraken_recent(now: int, *, request_fn=urlopen, sleep_fn=time.sleep) -> pd.DataFrame:
    """Unauthenticated Kraken market-data fetch, bounded retries on transient errors."""
    req = Request(KRAKEN_URL, headers={"User-Agent": "AtlasV07Research/0.7", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with request_fn(req, timeout=25) as response:
                return kraken_rows(json.load(response), now)
        except HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"Kraken HTTP {e.code}") from e
        except (TimeoutError, URLError) as e:
            if attempt == 2:
                raise RuntimeError("Kraken network error") from e
        sleep_fn(1.5 * (attempt + 1))
    raise RuntimeError("Kraken retry state exhausted")


def compare_recent_sources(coinbase: pd.DataFrame, kraken: pd.DataFrame, now: int) -> tuple[dict, pd.DataFrame]:
    """Independent RECENT price cross-check only. No implied 2-year verification."""
    v06.validate_4h_rows(coinbase, now)
    v06.validate_4h_rows(kraken, now)
    k = kraken.copy()
    c = coinbase.copy()
    if k.timestamp.duplicated().any() or c.timestamp.duplicated().any():
        raise ValueError("Duplicate candle in source comparison")
    left, right = int(k.timestamp.iloc[0]), int(k.timestamp.iloc[-1])
    expected_kraken = (right - left) // (STEP * 1000) + 1
    kraken_gap_fraction = 1 - len(k) / expected_kraken
    coincident = k[["timestamp", "close"]].merge(
        c[["timestamp", "close"]], on="timestamp", how="left", suffixes=("_kraken", "_coinbase"),
        validate="one_to_one", sort=True)
    matched = coincident.dropna(subset=["close_coinbase"]).copy()
    matched["absolute_difference_pct"] = (
        (matched.close_coinbase - matched.close_kraken).abs() / matched.close_kraken * 100
    )
    differences = matched.absolute_difference_pct.tolist()
    failures = []
    if len(matched) < MIN_OVERLAP:
        failures.append(f"Only {len(matched)} aligned candles (need {MIN_OVERLAP})")
    coverage = len(matched) / len(k)
    if coverage < MIN_COVERAGE:
        failures.append(f"Coinbase/Kraken aligned coverage {coverage:.2%} below {MIN_COVERAGE:.0%}")
    if kraken_gap_fraction > MAX_KRAKEN_GAP_FRACTION:
        failures.append("Kraken recent OHLC has too many gaps")
    fresh_closed_kraken = int(k.timestamp.iloc[-1] // 1000) + STEP
    fresh_closed_coinbase = int(c.timestamp.iloc[-1] // 1000) + STEP
    if now - fresh_closed_kraken > MAX_FRESHNESS_SECONDS or now - fresh_closed_coinbase > MAX_FRESHNESS_SECONDS:
        failures.append("A source is stale")
    mismatches = matched[matched.absolute_difference_pct > MAX_CLOSE_DIFFERENCE_PCT]
    if len(mismatches):
        failures.append(f"{len(mismatches)} closes differ by more than {MAX_CLOSE_DIFFERENCE_PCT:.1f}%")
    result = {
        "status": "PASS_RECENT_SUBSET" if not failures else "FAIL",
        "source": KRAKEN_SOURCE,
        "scope": "Only recent Kraken available 4h candles; NOT independent verification of the earlier Coinbase history",
        "last_complete_kraken_utc": v06.iso(int(k.timestamp.iloc[-1] // 1000)),
        "kraken_closed_candles": len(k),
        "kraken_expected_buckets_within_sample": expected_kraken,
        "kraken_gap_fraction": kraken_gap_fraction,
        "overlap_candles": len(matched),
        "overlap_fraction_of_kraken": coverage,
        "unmatched_kraken_candles": len(k) - len(matched),
        "close_difference_median_pct": float(statistics.median(differences)) if differences else None,
        "close_difference_p95_pct": float(pd.Series(differences).quantile(.95)) if differences else None,
        "close_difference_max_pct": max(differences) if differences else None,
        "mismatch_count_above_tolerance": len(mismatches),
        "mismatch_tolerance_pct": MAX_CLOSE_DIFFERENCE_PCT,
        "minimum_overlap": MIN_OVERLAP,
        "minimum_coverage": MIN_COVERAGE,
        "failures": failures,
    }
    return result, matched


def validation_blocks(candles: int) -> tuple[int, list[tuple[int, int]]]:
    """Fixed, nonoverlapping 60-day blocks strictly before the sealed final 20%."""
    if candles < v06.MIN_SEGMENT_4H:
        raise ValueError("Fewer than 1000 contiguous 4h candles")
    sealed_start = int(candles * .8)
    blocks = [(lo, lo + VALIDATION_BARS) for lo in range(
        FIRST_VALIDATION, sealed_start - VALIDATION_BARS + 1, VALIDATION_BARS)]
    if not blocks:
        raise ValueError("Segment has no complete 60-day validation block")
    if blocks[0][0] < 200 + REGIME_LOOKBACK or any(
        hi > sealed_start or hi - lo != VALIDATION_BARS for lo, hi in blocks):
        raise AssertionError("Validation or holdout boundary violation")
    return sealed_start, blocks


def preceding_regime(frame: pd.DataFrame, start: int) -> dict:
    """Predeclare regime using ONLY 200 candles strictly before window start."""
    if start < REGIME_LOOKBACK or start > len(frame):
        raise ValueError("Not enough pre-window history for regime")
    prior = frame.iloc[start - REGIME_LOOKBACK:start].close.astype(float)
    growth = float((prior.iloc[-1] / prior.iloc[0] - 1) * 100)
    vol = float(prior.pct_change().dropna().std() * 100)
    if not math.isfinite(growth) or not math.isfinite(vol):
        raise ValueError("Invalid pre-window market regime")
    trend = "rising" if growth > 5 else "falling" if growth < -5 else "sideways"
    volatility = "high" if vol > 1.5 else "normal"
    return {"regime_asof_utc": v06.iso(int(frame.timestamp.iloc[start-1] // 1000)),
            "trailing_200_candle_return_pct": growth,
            "trailing_4h_return_volatility_pct": vol,
            "trend": trend, "volatility": volatility,
            "classification_based_on_validation_or_holdout": False}


def validate_v06_saved_archive(csv: Path, audit_json: Path) -> dict:
    """Hash-check a previously saved GitHub research artifact, not certify provenance."""
    audit = json.loads(audit_json.read_text())
    expected = audit.get("saved_4h_file_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("v0.6 report lacks saved 4h SHA-256")
    actual = hashlib.sha256(csv.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("Archived CSV hash does NOT match v0.6 report")
    if audit.get("version") != "0.6.0" or audit.get("market") != "BTC/EUR":
        raise ValueError("Unexpected v0.6 report/version/market")
    return {"hash_match": True, "archive_sha256": actual,
            "report_file_sha256": hashlib.sha256(audit_json.read_bytes()).hexdigest(),
            "archive_origin_still_not_independently_authenticated": True}


def long_validation(frame: pd.DataFrame, fee: float, slip: float, crosscheck: dict,
                    offline: bool) -> dict:
    """Never selects/authorizes a strategy and NEVER evaluates sealed holdout."""
    v06.validate_4h_rows(frame)
    segments = v06.contiguous_segments(frame)
    outcomes = {name: [] for name in STRATEGIES}
    segment_meta = []
    windows_total = 0
    for index, seg in enumerate(segments, 1):
        seginfo = {
            "segment": index, "bars": len(seg),
            "start_utc": v06.iso(int(seg.timestamp.iloc[0] // 1000)),
            "end_utc": v06.iso(int(seg.timestamp.iloc[-1] // 1000)),
            "eligible": len(seg) >= v06.MIN_SEGMENT_4H,
        }
        if not seginfo["eligible"]:
            seginfo["reason"] = "Less than 1000 consecutive 4h candles"
            segment_meta.append(seginfo)
            continue
        sealed, windows = validation_blocks(len(seg))
        seginfo.update(sealed_final_20pct_starts_utc=v06.iso(int(seg.timestamp.iloc[sealed] // 1000)),
                       sealed_final_20pct_count=len(seg)-sealed,
                       sealed_final_20pct_evaluated=False,
                       nonoverlapping_60day_windows=len(windows))
        windows_total += len(windows)
        segment_meta.append(seginfo)
        for idx, (lo, hi) in enumerate(windows, 1):
            regime = preceding_regime(seg, lo)
            # Immutable, pre-registered strategy parameters. At evaluation,
            # inputs stop at the END of the validation window, not the holdout.
            passive = v05.passive_allocation_benchmark(seg.iloc[lo:hi], .20, fee, slip)
            for strategy in STRATEGIES:
                training = evaluate_period(seg, strategy, 200, lo, fee, slip)
                metrics_by_cost = {
                    f"{factor}x": evaluate_period(seg, strategy, lo, hi, fee*factor, slip*factor)
                    for factor in (1, 2, 3)
                }
                val = metrics_by_cost["1x"]
                tr_reasons = rejection_reasons(training)
                val_reasons = rejection_reasons(val)
                outcomes[strategy].append({
                    "segment": index, "window": idx,
                    "training_start_utc": v06.iso(int(seg.timestamp.iloc[200]//1000)),
                    "validation_start_utc": v06.iso(int(seg.timestamp.iloc[lo]//1000)),
                    "validation_end_utc": v06.iso(int(seg.timestamp.iloc[hi-1]//1000)),
                    "validation_bars": hi-lo,
                    "regime_before_validation": regime,
                    "training_trades": training["trades"],
                    "validation_trades": val["trades"],
                    "training_return_pct": training["return_pct"],
                    "validation_net_return_pct": val["return_pct"],
                    "validation_max_drawdown_pct": val["max_drawdown_pct"],
                    "validation_profit_factor": val["profit_factor"],
                    "validation_passive_20pct_pct": passive,
                    "validation_vs_passive_20pct_points": val["return_pct"] - passive,
                    "training_rejection_reasons_unchanged": tr_reasons,
                    "validation_rejection_reasons_unchanged": val_reasons,
                    "passes_unchanged_rules": not tr_reasons and not val_reasons,
                    "cost_stress": {
                        k: {"trades": v["trades"], "net_return_pct": v["return_pct"],
                            "max_drawdown_pct": v["max_drawdown_pct"]}
                        for k, v in metrics_by_cost.items()
                    },
                })
    strategy_rows = []
    for name in STRATEGIES:
        folds = outcomes[name]
        regimes = {}
        for fold in folds:
            key = fold["regime_before_validation"]["trend"]
            regimes.setdefault(key, {"windows":0, "profitable_windows":0, "trades":0})
            regimes[key]["windows"] += 1
            regimes[key]["profitable_windows"] += int(fold["validation_net_return_pct"] > 0)
            regimes[key]["trades"] += fold["validation_trades"]
        min_source = crosscheck.get("status") == "PASS_RECENT_SUBSET"
        manual_review = (not offline and min_source and
                         sum(x["eligible"] for x in segment_meta) >= 2 and
                         len(folds) >= 3 and all(x["passes_unchanged_rules"] for x in folds) and
                         all(x["cost_stress"]["3x"]["net_return_pct"] > 0 for x in folds))
        strategy_rows.append({
            "strategy": name, "validation_windows": len(folds),
            "total_validation_trades": sum(x["validation_trades"] for x in folds),
            "profitable_windows": sum(x["validation_net_return_pct"] > 0 for x in folds),
            "passed_unchanged_rules_windows": sum(x["passes_unchanged_rules"] for x in folds),
            "markets_before_windows": regimes,
            "manual_research_review_candidate_only": bool(manual_review),
            "windows": folds,
        })
    return {
        "version": "0.7.0", "kind": "READ_ONLY_DIAGNOSTIC_RESEARCH",
        "market": "BTC/EUR", "timeframe": "4h",
        "primary_source": v06.SOURCE,
        "secondary_source_scope": "recent Kraken data only, not complete two-year verification",
        "cross_exchange_recent": crosscheck,
        "offline_archive": offline,
        "strategy_fixed": True, "parameter_optimization_performed": False,
        "strategy_report_json_written": False,
        "auto_strategy_admission": False,
        "paper_trading_authorized": False, "real_trading_authorized": False,
        "account_changed": False, "risk_limits_changed": False,
        "sealed_final_20pct_ever_evaluated": False,
        "minimum_window_bars": VALIDATION_BARS,
        "window_length_days": VALIDATION_BARS / 6,
        "data_candles": len(frame),
        "data_sha256": hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest(),
        "total_eligible_segments": sum(x["eligible"] for x in segment_meta),
        "long_validation_windows_per_strategy": windows_total,
        "segments": segment_meta,
        "strategies": strategy_rows,
        "warnings": [
            "All Coinbase historical prices are NOT independently verified over two years; Kraken cross-check covers only recent available candles.",
            "Validation blocks are chronologically disjoint but not statistically independent; repeated research may overfit.",
            "Market regime labels use only the 200 candles strictly before each validation window.",
            "All four existing strategies and production risk/admission rules are unchanged.",
            "No candidate, research score or artifact can authorize trading; manual review is mandatory.",
            "Offline CSV/report hash matching is NOT live provenance authentication.",
        ],
    }


def summary_de(report: dict) -> str:
    cross = report["cross_exchange_recent"]
    lines = [
        "ATLAS TRADING AI v0.7 — UNABHAENGIGE FORSCHUNG / KEINE HANDELSFREIGABE",
        "NUR SIMULATION | KEINE ECHTEN ORDERS | PAPIERKONTO UNVERAENDERT",
        "",
        f"Historische Coinbase-4h-Kerzen: {report['data_candles']}",
        f"Mindestens 60 Tage lange, zeitlich getrennte Validierungsfenster: {report['long_validation_windows_per_strategy']}",
        f"Kraken-Teilpruefung: {cross['status']}",
        f"Kraken-Coinbase gemeinsame 4h-Kerzen: {cross.get('overlap_candles', 'nicht vorhanden')}",
        "",
        "Strategie | Val.-Trades | Positive Fenster | Fenster nach alten Regeln bestanden",
    ]
    for s in report["strategies"]:
        lines.append(f"{s['strategy']:<16} | {s['total_validation_trades']:>4} | "
                     f"{s['profitable_windows']}/{s['validation_windows']} | "
                     f"{s['passed_unchanged_rules_windows']}/{s['validation_windows']}")
    lines += ["", "ALTE FREIGABEGRENZEN UNVERAENDERT.",
              "Kein Bericht autorisiert paper.py. Holdouts bleiben unberuehrt.",
              "Eine Kraken-Teilpruefung belegt NICHT die gesamte historische Datenserie.",
              "Schaetzungen und Backtests sind keine Renditeprognosen.", ""]
    return "\n".join(lines)


def run(output: Path, *, days: int = v06.DEFAULT_DAYS, csv: Path | None = None,
        audit_json: Path | None = None, now: int | None = None,
        hour_fn=None, quarter_fn=None, kraken_fetch_fn=None,
        sleep_fn=time.sleep) -> dict:
    """Run historical research; write only into an isolated research output folder.

    Offline/test mode can check archived artifact hashes but NEVER claim live
    secondary-source verification or candidate approval.
    """
    output = v05.safe_output_dir(output, project=PROJECT)
    before = v05.protected_hashes(PROJECT)
    if audit_json is not None and csv is None:
        raise ValueError("--audit needs --csv")
    archived_audit = validate_v06_saved_archive(csv, audit_json) if csv is not None and audit_json is not None else None
    v06_report = v06.run(output, days=days, csv=csv, now=now,
                         hour_fn=hour_fn, quarter_fn=quarter_fn, sleep_fn=sleep_fn)
    saved = output / "btc_eur_4h_research.csv"
    raw_csv = saved.read_bytes()
    if hashlib.sha256(raw_csv).hexdigest() != v06_report["saved_4h_file_sha256"]:
        raise RuntimeError("v0.6 research 4h CSV hash mismatch")
    frame = pd.read_csv(saved)
    v06.validate_4h_rows(frame)
    cfg = json.loads((PROJECT / "paper_config.json").read_text())
    v06.verify_unchanged_config(cfg)
    now = int(time.time() if now is None else now)
    cross_csv = None
    if csv is not None:
        check = {"status": "NOT_CHECKED_OFFLINE", "reason": "Imported archive cannot prove independent live source",
                 "overlap_candles": None}
    else:
        try:
            kraken = (kraken_fetch_fn or fetch_kraken_recent)(now)
            check, comparison = compare_recent_sources(frame, kraken, now)
            cross_csv = (kraken, comparison)
        except (RuntimeError, ValueError, URLError, TimeoutError, OSError) as e:
            # Fail *closed* to no approval while retaining the primary research.
            check = {"status": "UNAVAILABLE_OR_INVALID", "reason": f"{type(e).__name__}: {str(e)[:220]}",
                     "overlap_candles": None}
    diag = long_validation(frame, float(cfg["fee_rate"]), float(cfg["slippage"]), check, csv is not None)
    diag["v06_primary_research_hash"] = hashlib.sha256((output / "v06_research.json").read_bytes()).hexdigest()
    diag["archived_v06_input_audit"] = archived_audit
    if cross_csv:
        _text_atomic(output / KRAKEN_CSV, cross_csv[0].to_csv(index=False))
        _text_atomic(output / COMPARISON_CSV, cross_csv[1].to_csv(index=False))
    else:
        # A retry without Kraken verification must not expose stale CSVs from
        # an earlier run as though they belonged to this failed/new audit.
        for filename in (KRAKEN_CSV, COMPARISON_CSV):
            stale = output / filename
            if stale.is_file():
                stale.unlink()
    _json_atomic(output / REPORT, diag)
    _text_atomic(output / SUMMARY, summary_de(diag))
    after = v05.protected_hashes(PROJECT)
    if before != after:
        raise RuntimeError("Production paper account, configuration, strategy or workflow modified")
    return diag


def main() -> None:
    p = argparse.ArgumentParser(description="Atlas v0.7 read-only external price audit and long fixed-window strategy validation")
    p.add_argument("--days", type=int, default=v06.DEFAULT_DAYS,
                   help="Coinbase historical BTC/EUR days, default 730; bounded 365..1095")
    p.add_argument("--output", type=Path, default=Path("atlas-research-output"))
    p.add_argument("--csv", type=Path, default=None,
                   help="OFFLINE research from archived 4h CSV; no live source verification")
    p.add_argument("--audit", type=Path, default=None,
                   help="Optional archived v06 JSON to verify matching CSV hash; requires --csv")
    args = p.parse_args()
    report = run(args.output, days=args.days, csv=args.csv, audit_json=args.audit)
    print(f"Atlas v0.7: {report['data_candles']} Coinbase 4h candles; "
          f"{report['long_validation_windows_per_strategy']} separate 60-day validation windows; "
          f"Kraken recent cross-check: {report['cross_exchange_recent']['status']}.")
    print("No real orders, no paper strategy admission, no account/strategy/risk changes.")
    print(f"Result: {args.output / REPORT}")


if __name__ == "__main__":
    main()
