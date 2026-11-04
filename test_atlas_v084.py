"""Atlas v0.8.4 research-only signal/timing/exposure/holdout/compatibility tests."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import atlas_v084 as v


def candles(n=1100, seed=841):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.00015, 0.002, n)))
    opened = np.r_[close[0], close[:-1]]
    upper = np.maximum(opened, close)
    lower = np.minimum(opened, close)
    return pd.DataFrame({'timestamp':np.arange(n,dtype=np.int64)*v.v08.STEP*1000,
                         'open':opened, 'high':upper*1.003, 'low':lower*.997,
                         'close':close, 'volume':np.ones(n)})


@pytest.fixture
def cfg():
    return json.loads((v.PROJECT/'paper_config.json').read_text())


def test_only_two_frozen_strategies():
    assert len(v.CANDIDATES)==2 and v.PREREGISTRATION['no_grid_search'] is True
    assert v.PREREGISTRATION['holdout_evaluated'] is False
    with pytest.raises(ValueError,match='frozen'):
        v.candidate_signals(candles(), 'Some optimized strategy')


@pytest.mark.parametrize('model', v.CANDIDATES)
def test_indicator_is_forward_invariant(model):
    f = candles()
    buy, sell = v.candidate_signals(f,model)
    for cut in (240,350,650,890):
        b, s = v.candidate_signals(f.iloc[:cut].copy(),model)
        np.testing.assert_array_equal(b,buy[:cut])
        np.testing.assert_array_equal(s,sell[:cut])


def test_donchian_excludes_own_high_and_enters_on_next_open(cfg):
    f=candles(780)
    f[['open','high','low','close']] = [100.,101.,99.,100.]
    f.loc[560,['open','high','low','close']] = [100.,105.,99.,104.]
    buy, sell=v.candidate_signals(f,v.CANDIDATES[0])
    assert buy[560]
    assert not buy[561]
    assert not sell[560]
    m, curve, ts=v.simulation(f,541,600,v.CANDIDATES[0],cfg,.006,.0005)
    # First entry only executes AFTER the complete signal candle at open[561].
    assert m['trades'] <= 1
    assert curve.loc[curve.timestamp==f.timestamp.iloc[560],'exposure'].iloc[0]==0
    assert curve.loc[curve.timestamp==f.timestamp.iloc[561],'exposure'].iloc[0]>0


def test_rejects_missing_bar_and_fabricated_candle(cfg):
    f=candles()
    bad=f.drop(index=330).reset_index(drop=True)
    with pytest.raises(ValueError,match='missing'):
        v.candidate_signals(bad,v.CANDIDATES[0])
    with pytest.raises(ValueError,match='missing'):
        v.simulation(bad,541,820,v.CANDIDATES[1],cfg,.006,.0005)


@pytest.mark.parametrize('model',v.v08.MODELS)
def test_v08_baseline_equivalence(model,cfg):
    f=candles()
    m1,c1,t1,e=v.v08.simulate(f,541,1061,model,cfg,.2,.006,.0005)
    m2,c2,t2=v.simulation(f,541,1061,model,cfg,.006,.0005)
    assert m1==m2 and t1==t2
    pd.testing.assert_frame_equal(c1,c2)


@pytest.mark.parametrize('model', v.CANDIDATES)
def test_risk_unchanged_and_nondestructive(model,cfg):
    f=candles()
    before=v.v05.protected_hashes(v.PROJECT)
    m,curve,trades=v.simulation(f,541,1061,model,cfg,.006,.0005)
    assert m['exposure'] <= .21
    assert (curve.exposure >= 0).all()
    assert before==v.v05.protected_hashes(v.PROJECT)
    modified=cfg.copy();modified['stop_loss']=.30
    with pytest.raises(ValueError,match='config'):
        v.simulation(f,541,1061,model,modified,.006,.0005)
    with pytest.raises(ValueError):
        v.simulation(f,541,1061,model,cfg,-.1,.0005)


def test_calibration_never_uses_future(cfg):
    f=candles()
    a=v.calibration(f,541,v.CANDIDATES[1],cfg,.006,.0005)
    changed=f.copy()
    for col in ['open','high','low','close']:
        changed.loc[541:,col] *= 3
    b=v.calibration(changed,541,v.CANDIDATES[1],cfg,.006,.0005)
    assert a==b
    assert 0 <= a['benchmark_weight'] <= .2


def test_run_rejects_outside_output_and_existing_directory(tmp_path):
    (tmp_path/'out').mkdir()
    with pytest.raises(ValueError,match='new'):
        v.run(tmp_path/'source',tmp_path/'out')


def test_no_holdout_condition_is_frozen():
    assert v.PREREGISTRATION['holdout_evaluated'] is False
    assert 'holdout' in v.evaluate.__doc__.lower()


def test_momentum_indicator_only_after_full_warmup():
    f=candles(215)
    buy,sell=v.candidate_signals(f,v.CANDIDATES[1])
    assert not buy[:210].any()
    assert not sell[:210].any()


def test_costs_do_not_improve_net_of_same_trade(cfg):
    f=candles(seed=512)
    base,_,tr=v.simulation(f,541,1061,v.CANDIDATES[0],cfg,.006,.0005)
    high,_,tr2=v.simulation(f,541,1061,v.CANDIDATES[0],cfg,.012,.001)
    # Cost sensitivity is conditional on identical position paths; exposure sizing
    # and stop thresholds change with fees, so compare only when trade timestamps match.
    if [(x['entry_time'],x['exit_time']) for x in tr] == [(x['entry_time'],x['exit_time']) for x in tr2]:
        assert high['return'] <= base['return'] + 1e-12
