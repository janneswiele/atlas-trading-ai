"""v0.8.2 synthetic unit/contract tests; not strategy-performance evidence."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

import atlas_v082 as v
import atlas_v08 as v08


def candles(n=1500, begin=1740009600000):
    rng = np.random.default_rng(820)
    close = 100 * np.exp(np.cumsum(rng.normal(.0001, .012, n)))
    return pd.DataFrame({'timestamp': begin + np.arange(n) * v08.STEP * 1000,
                         'open':close, 'high':close * 1.015,
                         'low':close * .985, 'close':close, 'volume':np.ones(n)})


@pytest.fixture
def cfg():
    return json.loads((v.PROJECT/'paper_config.json').read_text())


@pytest.fixture
def synthetic_report(tmp_path, cfg):
    source = tmp_path/'source'; source.mkdir()
    data = candles()
    end = int(data.timestamp.iloc[-1]) + v08.STEP * 1000
    holdout = int(data.timestamp.iloc[1200])
    start = int(data.timestamp.iloc[0]); lo, hi = 541, 1081
    windows=[]; curves=[]
    for model in v08.MODELS:
        m, curve, _, _ = v08.simulate(data, lo, hi, model, cfg, .2, .006, .0005)
        windows.append(dict(strategy=model, segment=1, days=90, start=int(data.timestamp.iloc[lo]),
                            end_exclusive=int(data.timestamp.iloc[hi-1])+v08.STEP*1000,
                            allocation=.2, cost_factor=1, parameters='baseline', regime='bull', **m))
        curves.append(curve.assign(strategy=model, window_start=int(data.timestamp.iloc[lo])))
    data.to_csv(source/'coinbase_btc_eur_4h.csv',index=False)
    pd.DataFrame(windows).to_csv(source/'per_window_results.csv',index=False)
    pd.concat(curves).to_csv(source/'equity_windows.csv',index=False)
    (source/'release_gate.json').write_text(json.dumps({'passed':False,'paper_trading_authorized':False,'status':'RESEARCH_COMPLETE_HOLDOUT_SEALED'}))
    (source/'data_quality_report.json').write_text(json.dumps({'passed':True,'checks':{'coverage':True,'correlation':True}}))
    from datetime import datetime, timezone
    to_utc = lambda x:datetime.fromtimestamp(x/1000,timezone.utc).isoformat().replace('+00:00','Z')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.name!='manifest.json'}
    (source/'manifest.json').write_text(json.dumps({
        'git_commit':'synthetic-fixture','start':to_utc(start),'end_exclusive':to_utc(end),
        'holdout_start':to_utc(holdout),'holdout_evaluated':False,
        'paper_trading_authorized':False,'fee_rate_assumption':.006,
        'slippage_assumption':.0005,'protocol':{'primary_days':90},
        'artifacts_sha256':hashes}))
    return source


def test_static_zero_allocation_unchanged():
    assert np.array_equal(v.static_passive(100,[99,110],0,.006,.0005), np.array([100.,100.]))


def test_static_passive_matches_v08_cost_convention():
    prices=np.array([100.,105.,120.]); w=.14;fee=.006;slip=.0005
    expected=100*(1-w) + (100*w/(100*(1+slip)*(1+fee)))*prices*(1-slip)*(1-fee)
    assert np.allclose(v.static_passive(100,prices,w,fee,slip),expected)


@pytest.mark.parametrize('weight',[-.1,.201,float('nan')])
def test_reject_invalid_weight(weight):
    with pytest.raises(ValueError):v.static_passive(100,np.array([100.,101.]),weight,.006,.0005)


def test_annual_volatility_zero_for_flat_equity():
    assert v.annual_volatility([100,100,100,100])==0


def test_vol_calibration_only_uses_past(cfg):
    f=candles()
    a=v.volatility_calibration(f,541,v08.MODELS[0],cfg,.006,.0005)
    g=f.copy()
    g.loc[541:,'close']*=3
    g.loc[541:,'open']*=3
    g.loc[541:,'high']*=3
    g.loc[541:,'low']*=3
    b=v.volatility_calibration(g,541,v08.MODELS[0],cfg,.006,.0005)
    assert a==b
    assert a['calibration_end_exclusive_ms']==int(f.timestamp.iloc[541])


def test_inadequate_calibration_rejected(cfg):
    with pytest.raises(ValueError):v.volatility_calibration(candles(),540,v08.MODELS[0],cfg,.006,.0005)


def test_zero_btc_variance_is_not_forced(cfg):
    f=candles();f[['open','close']]=100.;f.high=101;f.low=99
    with pytest.raises(ValueError,match='zero or invalid'):v.volatility_calibration(f,541,v08.MODELS[0],cfg,.006,.0005)


def test_complete_synthetic_analysis_no_release(synthetic_report):
    rows, report=v.investigate(synthetic_report)
    assert len(rows)==2
    assert set(rows.strategy)==set(v08.MODELS)
    assert not rows.holdout_evaluated.any() and not rows.strategy_approval.any()
    assert report['release_gate']['passed'] is False
    assert report['source_crosscheck_passed']
    assert rows.window_end_exclusive_ms.max()<v.require_utc_ms(report['source_holdout_start'])


def test_20pct_benchmark_reconstructed_exactly(synthetic_report):
    data=pd.read_csv(synthetic_report/'coinbase_btc_eur_4h.csv')
    old=pd.read_csv(synthetic_report/'equity_windows.csv')
    lo=541;hi=1081
    w=v.static_passive(data.open.iloc[lo], data.close.iloc[lo:hi].to_numpy(),.2,.006,.0005)
    obs=old[old.strategy==v08.MODELS[0]].sort_values('timestamp').benchmark.to_numpy()
    assert np.allclose(w,obs,atol=1e-10,rtol=0)


def test_modified_holdout_prices_never_affect_diagnostics(synthetic_report):
    a,_=v.investigate(synthetic_report)
    f=pd.read_csv(synthetic_report/'coinbase_btc_eur_4h.csv')
    f.loc[1200:,['open','high','low','close']]*=1.1
    path=synthetic_report/'coinbase_btc_eur_4h.csv';f.to_csv(path,index=False)
    manifest_path=synthetic_report/'manifest.json';manifest=json.loads(manifest_path.read_text())
    manifest['artifacts_sha256']['coinbase_btc_eur_4h.csv']=v.sha256(path)
    manifest_path.write_text(json.dumps(manifest))
    b,_=v.investigate(synthetic_report)
    pd.testing.assert_frame_equal(a,b)


def test_tampered_research_result_rejected(synthetic_report):
    path=synthetic_report/'per_window_results.csv'
    path.write_text(path.read_text().replace('SMA 20/50','SMA 20/49'))
    with pytest.raises(ValueError,match='Hash mismatch'):v.investigate(synthetic_report)


def test_unsealed_holdout_rejected(synthetic_report):
    path=synthetic_report/'manifest.json';data=json.loads(path.read_text())
    data['holdout_evaluated']=True;path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='not sealed'):v.investigate(synthetic_report)


def test_failed_quality_gate_rejected(synthetic_report):
    path=synthetic_report/'data_quality_report.json';path.write_text(json.dumps({'passed':False,'checks':{'coverage':False}}))
    with pytest.raises(ValueError):v.investigate(synthetic_report)


def test_missing_input_rejected(synthetic_report):
    (synthetic_report/'equity_windows.csv').unlink()
    with pytest.raises(FileNotFoundError):v.investigate(synthetic_report)


def test_report_contains_strong_caveats(synthetic_report):
    d,r=v.investigate(synthetic_report)
    md=v.create_report(d,r)
    assert 'No strategy admitted' in md
    assert 'ex-post' in md
    assert 'not equal realized risk' in md


def test_creates_separate_files_and_never_overwrites(synthetic_report,tmp_path):
    before=v.v05.protected_hashes(v.PROJECT)
    out=tmp_path/'results';r=v.run(synthetic_report,out)
    assert r['release_gate']['passed'] is False
    assert (out/'prewindow_benchmark_windows.csv').exists()
    assert (out/'diagnostics.json').exists()
    assert (out/'SHA256SUMS.json').exists()
    assert before==v.v05.protected_hashes(v.PROJECT)
    with pytest.raises(ValueError,match='nonexistent'):v.run(synthetic_report,out)


def test_output_cannot_be_source_or_parent(synthetic_report):
    with pytest.raises(ValueError):v.run(synthetic_report,synthetic_report)
    with pytest.raises(ValueError):v.run(synthetic_report,synthetic_report.parent)
