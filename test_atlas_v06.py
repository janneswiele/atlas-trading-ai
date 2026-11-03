"""v0.6 offline data-integrity, sealed-holdout and ledger-safety regression suite."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import atlas_v06 as v6
from paper import STEP


def make_hour(ts, close=100., volume=1.):
    return (ts, close, close + 3, close - 3, close, volume)


def make_quarters(ts, complete=True):
    # Realistic-looking synthetic candles for TESTS ONLY. Production cannot
    # replace the public Coinbase API with these fixtures.
    n = 4 if complete else 3
    return {ts+900*i: (ts+900*i, 100., 103., 97., 101., 1.) for i in range(n)}


def data_four_hour(n=1050, start=None):
    end = (int(time.time()) // STEP) * STEP
    if start is None:
        start = end - n * STEP
    i = np.arange(n)
    close = 62000 + 2500 * np.sin(i/21) + 8 * i
    op = close * (1 + .001 * np.cos(i/6))
    return pd.DataFrame({
        "timestamp": (start + i * STEP) * 1000,
        "open": op, "high": np.maximum(op, close)*1.004,
        "low": np.minimum(op, close)*.996, "close": close,
        "volume": np.full(n, 2.0),
    })


def test_production_protocol_is_paper_independent():
    assert v6.REPORT != "strategy_report.json"
    assert v6.SOURCE.startswith("Coinbase")
    assert v6.MIN_DAYS == 365
    assert v6.DEFAULT_DAYS == 730
    assert v6.PROTECTED == v6.v05.PROTECTED
    assert v6.MAX_MISSING_FRACTION <= .005


def test_check_hour_rejects_bad_timestamp_and_prices():
    for row in [(0, 100, 99, 80, 100, 1),
                (0, 100, 105, 101, 103, 1),
                (0, 100, 103, 90, 100, -1),
                (1, 100, 103, 90, 100, 1),
                (0, 100, float('nan'), 90, 100, 1),
                (0, -1, 104, 0, 101, 1)]:
        with pytest.raises(ValueError):
            v6.check_hour(row, 0, 3600)


def test_check_hour_accepts_valid_candle():
    row = (0, 100, 104, 96, 102, 3)
    assert v6.check_hour(row, 0, 3600) == row


def test_hour_parsing_rejects_conflicting_duplicates():
    with pytest.raises(ValueError, match="Conflicting"):
        v6.parse_window([make_hour(0), make_hour(0, 101)], 0, 3600)


def test_hour_parsing_rejects_out_of_window():
    with pytest.raises(ValueError):
        v6.parse_window([make_hour(3600)], 0, 3600)


def test_recovery_uses_exactly_four_verified_quarters():
    left, right = 0, 240*3600
    lost = 34 * 3600
    def hour_fn(a, b):
        return [make_hour(t) for t in range(a,b,3600) if t != lost]
    def quarter_fn(a,b):
        assert a == lost and b == lost + 3600
        return make_quarters(a)
    df, audit = v6.collect_hourly(left,right,hour_fn=hour_fn,quarter_fn=quarter_fn,sleep_fn=lambda _:None)
    assert len(df) == 240
    assert audit["missing_hourly_buckets"] == 0
    assert audit["verified_15m_reconstructions"] == 1
    assert df[df.timestamp == lost].iloc[0]["source"] == "four_verified_coinbase_15m"
    assert float(df[df.timestamp == lost].iloc[0]["volume"]) == 4


def test_recovery_retries_hour_before_requesting_quarters():
    left, right = 0, 240*3600
    lost = 11 * 3600
    called = []
    def hour_fn(a, b):
        if b-a == 240*3600: return [make_hour(t) for t in range(a,b,3600) if t != lost]
        called.append("retry")
        return [make_hour(lost)]
    def quarter_fn(a,b):
        pytest.fail("15m should not run if 1h retry succeeds")
    _,audit = v6.collect_hourly(left,right,hour_fn=hour_fn,quarter_fn=quarter_fn,sleep_fn=lambda _:None)
    assert called == ["retry"]
    assert audit["verified_1h_retries"] == 1


def test_unresolvable_hour_remains_missing_not_interpolated():
    left, right = 0, 240*3600*2
    missing = 200*3600
    def hour_fn(a,b): return [make_hour(t) for t in range(a,b,3600) if t != missing]
    def quarters(a,b): return make_quarters(a,complete=False)
    df,audit = v6.collect_hourly(left,right,hour_fn=hour_fn,
                                  quarter_fn=quarters,sleep_fn=lambda _:None)
    assert missing not in df.timestamp.to_list()
    assert audit["missing_hourly_buckets"] == 1
    assert audit["missing_hour_starts_utc"] == [v6.iso(missing)]
    four, omitted = v6.aggregate_verified_4h(df, left, right)
    assert omitted == [200*3600]
    assert len(four) == (right-left)//STEP-1
    pieces = v6.contiguous_segments(four)
    assert len(pieces)==2
    assert int(pieces[1].timestamp.iloc[0] - pieces[0].timestamp.iloc[-1]) == 2 * STEP * 1000


def test_too_many_missing_hours_fail_closed():
    left, right = 0, 240*3600
    lost = {4*3600, 5*3600}
    def hour_fn(a,b): return [make_hour(t) for t in range(a,b,3600) if t not in lost]
    with pytest.raises(ValueError, match="audit cap"):
        v6.collect_hourly(left,right,hour_fn=hour_fn,
                          quarter_fn=lambda a,b:make_quarters(a,False),
                          sleep_fn=lambda _:None)


def test_missing_fraction_cannot_be_weakened():
    with pytest.raises(ValueError, match="Cannot weaken"):
        v6.collect_hourly(0,3600,hour_fn=lambda a,b:[],max_missing_fraction=.05)


def test_bad_provider_data_fails_closed():
    with pytest.raises(ValueError):
        v6.collect_hourly(0,3600,hour_fn=lambda a,b:[(0,101,90,100,101,2)],
                          sleep_fn=lambda _:None)


def test_four_hour_aggregation_uses_only_real_hourly_inputs():
    df=pd.DataFrame([(*make_hour(t, close=100+t/3600),"coinbase_1h") for t in range(0, 8*3600,3600)],
                    columns=v6.COLUMNS+["source"])
    result, omitted=v6.aggregate_verified_4h(df,0,8*3600)
    assert omitted == []
    assert len(result)==2
    assert result.iloc[0].open == 100
    assert result.iloc[0].close == 103
    assert result.iloc[0].volume == 4
    assert result.iloc[0].high == 106


def test_four_hour_aggregation_refuses_duplicate_hour():
    df=pd.DataFrame([make_hour(0),make_hour(0)],columns=v6.COLUMNS)
    with pytest.raises(ValueError, match="Duplicate"):
        v6.aggregate_verified_4h(df,0,4*3600)


def test_four_hour_rejects_future_or_disorder():
    df=data_four_hour()
    with pytest.raises(ValueError,match="unfinished"):
        v6.validate_4h_rows(df,now=int(df.timestamp.iloc[-1]//1000)+STEP-1)
    broken=df.copy()
    broken.loc[10,"timestamp"] = broken.loc[9,"timestamp"]
    with pytest.raises(ValueError,match="Duplicate"):
        v6.validate_4h_rows(broken)


def test_contiguous_segment_never_bridges_gap():
    df=data_four_hour(n=2200)
    broken=pd.concat([df.iloc[:1050],df.iloc[1051:]],ignore_index=True)
    pieces=v6.contiguous_segments(broken)
    assert len(pieces)==2
    assert len(pieces[0])==1050
    assert len(pieces[1])==1149
    assert (pieces[1].timestamp.iloc[0]-pieces[0].timestamp.iloc[-1]) == 2*STEP*1000


@pytest.mark.parametrize("n",[1000,1050,1350,3000,4600])
def test_walkforward_guards_holdout(n):
    sealed, windows = v6.walkforward_windows(n)
    assert sealed==int(n*.8)
    assert windows[0][0]>=400
    assert windows[-1][1]==sealed
    assert all(hi-lo>=180 for lo,hi in windows)
    assert all(windows[i][1] == windows[i+1][0] for i in range(len(windows)-1))
    assert all(hi<=sealed for _,hi in windows)


def test_short_segment_disallowed():
    with pytest.raises(ValueError):
        v6.walkforward_windows(999)


def test_offline_diagnostics_seal_holdout_for_all_strategy_calls(monkeypatch):
    df=data_four_hour(1050)
    called=[]
    def spy(frame,strategy,lo,hi,fee,slip):
        assert hi <= int(len(frame)*.8)
        assert lo >= 200
        called.append((strategy,lo,hi,fee,slip))
        return {"trades":0,"return_pct":0.,"max_drawdown_pct":0.,"profit_factor":0.,"buy_hold_return_pct":0.}
    monkeypatch.setattr(v6,"evaluate_period",spy)
    cfg=json.loads((v6.PROJECT / "paper_config.json").read_text())
    report=v6.independent_diagnostics(df,cfg["fee_rate"],cfg["slippage"],
                                      source="synthetic test data",data_audit={})
    assert len(called)>0
    assert report["sealed_holdouts_all_untouched"] is True
    assert report["candidates_for_manual_review_only"] == []
    assert report["disjoint_pre_holdout_validation_windows"]>=1
    assert all(not x["qualifies_for_manual_review_only"] for x in report["strategies"])


def test_diagnostic_refuses_fee_risk_change(monkeypatch):
    df=data_four_hour(1050)
    cfg=json.loads((v6.PROJECT/"paper_config.json").read_text())
    with pytest.raises(ValueError,match="costs"):
        v6.independent_diagnostics(df,cfg["fee_rate"]*2,cfg["slippage"],source="test",data_audit={})


def test_archived_csv_cannot_authorize_and_preserves_account(tmp_path):
    # Offline sample is not valid evidence of authentic market provenance.
    df=data_four_hour(1050)
    csv=tmp_path/"sample.csv"
    df.to_csv(csv,index=False)
    output=tmp_path/"out"
    before=v6.v05.protected_hashes(v6.PROJECT)
    report=v6.run(output,csv=csv)
    after=v6.v05.protected_hashes(v6.PROJECT)
    assert before == after
    assert report["data_audit"]["origin_verified"] is False
    assert report["trading_or_paper_authorized"] is False
    assert not (output/"strategy_report.json").exists()
    assert (output/v6.REPORT).exists()
    assert (output/"btc_eur_4h_research.csv").exists()
    assert (output/"SUMMARY_DE.txt").exists()
    assert report["candidates_for_manual_review_only"] == []
    assert report["sealed_holdouts_all_untouched"] is True


def test_protected_account_path_cannot_be_output(tmp_path):
    (tmp_path/"paper_state.json").write_text("KEEP")
    with pytest.raises(ValueError):
        v6.run(tmp_path,csv=tmp_path/"missing.csv")
    assert (tmp_path/"paper_state.json").read_text()=="KEEP"


def test_cli_rejects_out_of_bounds_before_network(tmp_path):
    for n in (0,175,1096):
        with pytest.raises(ValueError,match="Long history requires"):
            v6.run(tmp_path/"out",days=n)


def test_production_sources_not_fabricated():
    source=Path(v6.__file__).read_text()
    assert "strategy_report.json" in source
    assert "paper_state.json" not in [p.name for p in Path(v6.PROJECT).glob("v06*.json")]
    assert "coinbase_1h" in source
    assert "four_verified_coinbase_15m" in source


def test_15m_provider_refuses_fabricated_ohlc():
    data=make_quarters(0)
    assert v6.verified_quarters(0,data)
    data[0]=(0,100.,90.,80.,100.,1.)
    with pytest.raises(ValueError):
        v6.verified_quarters(0,data)


def test_frozen_risk_contract_rejects_changes():
    cfg=dict(v6.EXPECTED_RISK)
    v6.verify_unchanged_config(cfg)
    for key, proposed in (("max_allocation", .25),("max_drawdown",.20),
                          ("stop_loss",.03),("fee_rate",.002),
                          ("trading_enabled",False)):
        tampered=dict(cfg);tampered[key]=proposed
        with pytest.raises(ValueError,match="risk config"):
            v6.verify_unchanged_config(tampered)


def test_two_disjoint_market_segments_have_multiple_validation_windows_and_no_holdout_access(monkeypatch):
    df = data_four_hour(4400)
    df = pd.concat([df.iloc[:3300], df.iloc[3301:]], ignore_index=True)
    called = []
    def optimistic_test_metrics(frame, strategy, lo, hi, fee, slip):
        assert hi <= int(len(frame)*.8), "Sealed holdout was accessed"
        called.append((len(frame), strategy, lo, hi))
        return {"trades":15,"return_pct":1.,"max_drawdown_pct":-1.,
                "profit_factor":2.,"buy_hold_return_pct":0.}
    monkeypatch.setattr(v6, "evaluate_period", optimistic_test_metrics)
    cfg = json.loads((v6.PROJECT/"paper_config.json").read_text())
    report = v6.independent_diagnostics(df,cfg["fee_rate"],cfg["slippage"],
                                        source="SYNTHETIC TEST",data_audit={"synthetic":True})
    assert report["eligible_segments"] == 2
    assert report["disjoint_pre_holdout_validation_windows"] == 6
    assert len(called)>0
    assert report["candidates_for_manual_review_only"] == []
    assert report["source_sufficient_for_manual_research_review"] is False
    assert report["trading_or_paper_authorized"] is False
    assert report["strategy_report_json_written"] is False
    assert report["sealed_holdouts_all_untouched"] is True


def test_even_optimistic_offline_data_cannot_become_research_candidate(monkeypatch):
    df=data_four_hour(4400)
    df=pd.concat([df.iloc[:3300],df.iloc[3301:]],ignore_index=True)
    monkeypatch.setattr(v6,"evaluate_period",lambda frame,strategy,lo,hi,fee,slip: {
        "trades":30,"return_pct":9.,"max_drawdown_pct":-1.,
        "profit_factor":4.,"buy_hold_return_pct":0.})
    cfg=json.loads((v6.PROJECT/"paper_config.json").read_text())
    report=v6.independent_diagnostics(df,cfg["fee_rate"],cfg["slippage"],
                                      source="ARCHIVED CSV",data_audit={"origin_verified":False})
    assert report["candidates_for_manual_review_only"]==[]
    assert not report["source_sufficient_for_manual_research_review"]
