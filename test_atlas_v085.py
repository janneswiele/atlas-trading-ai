"""Atlas v0.8.5 fee-audit research-only protection and scenario tests."""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import atlas_v085 as v


def fake_candles(n=1100):
    r=np.random.default_rng(85)
    close=100*np.exp(np.cumsum(r.normal(0,.003,n)))
    opened=np.r_[close[0],close[:-1]]
    return pd.DataFrame({'timestamp':np.arange(n,dtype=np.int64)*v.v08.STEP*1000,
       'open':opened,'high':np.maximum(opened,close)*1.004,
       'low':np.minimum(opened,close)*.996,'close':close,'volume':np.ones(n)})


def test_fixed_scenarios_no_optimization():
    assert [x[0] for x in v.COST_SCENARIOS]==[
        'fee_free_idealization','illustrative_0p5pct','original_0p6pct',
        'kraken_pro_tier1_taker_0p8pct','cost_stress_1p2pct']
    assert [x[1] for x in v.COST_SCENARIOS]==[0,.005,.006,.008,.012]
    assert v.MODELS==(*v.v08.MODELS,*v.v084.CANDIDATES)


@pytest.mark.parametrize('fee',[0,.005,.006,.008,.012])
def test_stop_take_math_exactly_consistent_with_fee_model(fee):
    m=v.stop_take_round_trip(fee)
    # For an entry with slippage-adjusted fill=1, cash spent=1 and qty=1/(1+fee).
    # At a stop/take threshold based on the entry fill (not the market mid),
    # the sell execution is threshold*(1-slip)*(1-fee).
    factor=(1-v.SLIPPAGE)*(1-fee)/(1+fee)
    assert math.isclose(m['take_profit_net_pct_at_exact_threshold']/100,(1+.04)*factor-1,abs_tol=1e-12)
    assert math.isclose(m['stop_loss_net_pct_at_exact_threshold']/100,(1-.02)*factor-1,abs_tol=1e-12)
    assert m['break_even_win_rate_pct_at_exact_threshold'] is None or 0<m['break_even_win_rate_pct_at_exact_threshold']<100


def test_transaction_cost_degrades_exact_threshold_payoff():
    arr=[v.stop_take_round_trip(fee) for _,fee in v.COST_SCENARIOS]
    assert all(arr[i+1]['take_profit_net_pct_at_exact_threshold']<arr[i]['take_profit_net_pct_at_exact_threshold'] for i in range(len(arr)-1))
    assert all(arr[i+1]['stop_loss_net_pct_at_exact_threshold']<arr[i]['stop_loss_net_pct_at_exact_threshold'] for i in range(len(arr)-1))
    assert all(arr[i+1]['break_even_win_rate_pct_at_exact_threshold']>arr[i]['break_even_win_rate_pct_at_exact_threshold'] for i in range(len(arr)-1))


def test_source_strategy_and_risk_remain_unmodified():
    cfg=json.loads((v.PROJECT/'paper_config.json').read_text())
    before=v.v05.protected_hashes(v.PROJECT)
    frame=fake_candles()
    for name,fee in v.COST_SCENARIOS:
        for model in v.MODELS:
            m, curve, trades=v.v084.simulation(frame,541,1061,model,cfg,fee,v.SLIPPAGE)
            assert 0 <= m['exposure'] <= .21
            assert not curve.empty
            assert isinstance(trades,list)
    assert before==v.v05.protected_hashes(v.PROJECT)


def test_original_baseline_exactly_replayable():
    cfg=json.loads((v.PROJECT/'paper_config.json').read_text())
    frame=fake_candles()
    for model in v.v08.MODELS:
        a,curve,trades,_=v.v08.simulate(frame,541,1061,model,cfg,.2,.006,v.SLIPPAGE)
        b,curve2,trades2=v.v084.simulation(frame,541,1061,model,cfg,.006,v.SLIPPAGE)
        assert a==b and trades==trades2
        pd.testing.assert_frame_equal(curve,curve2)


def test_no_holdout_or_trading_approval():
    assert 'pre-holdout' in v.historical_cost_audit.__doc__.lower()
    assert len(v.MODELS)==4
    assert 'research' in v.__doc__.lower()


def test_never_overwrite_existing_output(tmp_path):
    out=tmp_path/'exists';out.mkdir()
    with pytest.raises(ValueError,match='independent'):
        v.run(tmp_path/'source',out)


def test_reject_nonsensical_fees():
    for fee in [-1,.04,float('nan')]:
        with pytest.raises(ValueError):
            v.stop_take_round_trip(fee)
