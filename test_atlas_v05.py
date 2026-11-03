"""Regression and safety tests for the read-only v0.5 research overlay."""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import atlas_v05 as v5
from paper import STEP
from research import build_report


def synthetic(n=1020):
    end = (int(time.time()) // STEP) * STEP
    start = end - n * STEP
    idx = np.arange(n)
    close = 64000 + 2000 * np.sin(idx / 20) + 12 * idx
    op = close * (1 + .001 * np.cos(idx / 5))
    hi = np.maximum(op, close) * 1.003
    lo = np.minimum(op, close) * .997
    return pd.DataFrame({"timestamp": (start + idx * STEP) * 1000,
                         "open": op, "high": hi, "low": lo,
                         "close": close, "volume": np.full(n, 25.0)})


def asof(df):
    return int(df.timestamp.iloc[-1] / 1000) + STEP + 1


def report_for(df):
    return build_report(df, now=asof(df))


def test_allocation_20pct_only_limits_full_account_return():
    df = pd.DataFrame([{"open": 100., "close": 100.}, {"open": 200., "close": 200.}])
    r = v5.passive_allocation_benchmark(df, .20, 0, 0)
    assert r == pytest.approx(20)
    assert r != 100


def test_allocation_benchmark_fees_reduce_result():
    df = pd.DataFrame([{"open": 100., "close": 100.}, {"open": 100., "close": 100.}])
    assert v5.passive_allocation_benchmark(df, .20, .001, .0005) < 0
    assert v5.passive_allocation_benchmark(df, .20, 0, 0) == 0


@pytest.mark.parametrize("allocation", [-1, .21, 1.0])
def test_invalid_allocation_refused(allocation):
    df = pd.DataFrame([{"open": 100., "close": 100.}] * 2)
    with pytest.raises(ValueError):
        v5.passive_allocation_benchmark(df, allocation, 0, 0)


def test_block_boundaries_never_touch_holdout():
    holdout, blocks = v5.predefined_blocks(1050)
    assert holdout == 840
    assert blocks == [(200, 360), (360, 520), (520, 680), (680, 840)]
    assert all(blocks[i][1] == blocks[i+1][0] for i in range(3))


@pytest.mark.parametrize("n", [0, 999])
def test_too_short_data_fails_closed(n):
    with pytest.raises(ValueError):
        v5.predefined_blocks(n)


def test_history_gaps_refused():
    df = synthetic()
    df.loc[500, "timestamp"] += STEP * 1000
    with pytest.raises(ValueError):
        v5.validate_history(df, asof(synthetic()))


def test_future_incomplete_candle_refused():
    df = synthetic()
    with pytest.raises(ValueError):
        v5.validate_history(df, int(df.timestamp.iloc[-1] // 1000) + STEP // 2)


def test_invalid_ohlc_refused():
    df = synthetic()
    df.loc[30, "high"] = 1.0
    with pytest.raises(ValueError):
        v5.validate_history(df, asof(df))


def test_output_cannot_be_root_or_ancestor():
    with pytest.raises(ValueError):
        v5.safe_output_dir(v5.PROJECT)
    with pytest.raises(ValueError):
        v5.safe_output_dir(v5.PROJECT.parent)


def test_output_refuses_protected_account_file(tmp_path):
    (tmp_path / "paper_state.json").write_text("do not touch")
    with pytest.raises(ValueError):
        v5.safe_output_dir(tmp_path)


def test_protected_hashes_stable_with_data_changes(tmp_path):
    (tmp_path / "paper_state.json").write_text('{"cash_eur":100}')
    a = v5.protected_hashes(tmp_path)
    (tmp_path / "paper_state.json").write_text('{"cash_eur":99}')
    b = v5.protected_hashes(tmp_path)
    assert a != b
    assert a["strategy_report.json"] is None


def test_diagnostics_consistency_and_cost_stress():
    df = synthetic()
    v = v5.build_diagnostics(df, report_for(df), .001, .0005, asof(df), "synthetic test only")
    assert v["holdout_used_for_diagnostics"] is False
    assert v["holdout_candles"] == len(df) - int(len(df) * .8)
    assert v["paper_trading_authorized"] is False
    assert v["live_trading_authorized"] is False
    assert v["candle_count"] == 1020
    assert len(v["strategies"]) == 4
    for s in v["strategies"]:
        assert len(s["pre_holdout_sensitivity_blocks"]) == 4
        stress = s["validation_cost_stress"]
        assert stress["base_cost"]["closed_trades"] == stress["double_cost"]["closed_trades"]
        assert stress["base_cost"]["closed_trades"] == stress["triple_cost"]["closed_trades"]
        assert stress["triple_cost"]["net_return_pct"] <= stress["base_cost"]["net_return_pct"] + 1e-7


def test_after_holdout_prices_do_not_affect_pre_holdout_diagnostics():
    df = synthetic()
    base_report = report_for(df)
    first = v5.build_diagnostics(df, base_report, .001, .0005, asof(df), "test")
    modified = df.copy(deep=True)
    start = int(len(df) * .8)
    for col in ("open", "high", "low", "close"):
        modified.loc[start:, col] *= 1.5
    second = v5.build_diagnostics(modified, base_report, .001, .0005, asof(df), "test")
    assert first["strategies"] == second["strategies"]
    assert first["data_sha256"] != second["data_sha256"]


def test_mismatched_costs_refused():
    df = synthetic()
    with pytest.raises(ValueError):
        v5.build_diagnostics(df, report_for(df), .002, .0005, asof(df), "test")


def test_archive_run_never_changes_account_or_creates_authorization(tmp_path, monkeypatch):
    df = synthetic()
    root = tmp_path / "test_project"
    root.mkdir()
    (root / "paper_state.json").write_text('{"cash_eur":100,"btc":0}')
    source_cfg = v5.PROJECT / "paper_config.json"
    (root / "paper_config.json").write_bytes(source_cfg.read_bytes())
    monkeypatch.setattr(v5, "PROJECT", root)
    p = tmp_path / "btc.csv"
    df.to_csv(p, index=False)
    before = v5.protected_hashes(root)
    out = root / "research-output"
    result = v5.run(out, csv=p)
    assert v5.protected_hashes(root) == before
    assert result["paper_trading_authorized"] is False
    assert not (root / "strategy_report.json").exists()
    assert set(x.name for x in out.iterdir()) == {
        "coinbase_btc_eur_4h.csv", "strategy_report_CANDIDATE.json",
        "v05_diagnostics.json", "SUMMARY_DE.txt"
    }


def test_synthetic_data_never_claims_real_authorization(tmp_path, monkeypatch):
    df = synthetic()
    root = tmp_path / "project"
    root.mkdir()
    (root / "paper_config.json").write_bytes((v5.PROJECT / "paper_config.json").read_bytes())
    monkeypatch.setattr(v5, "PROJECT", root)
    p = tmp_path / "data.csv"
    df.to_csv(p, index=False)
    report = v5.run(root / "output", csv=p)
    assert report["blocked_until_independent_validation"]
    assert report["all_existing_rejection_rules_unchanged"]
    assert not any(n.name == "strategy_report.json" for n in root.rglob("*"))
