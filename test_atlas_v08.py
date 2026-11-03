"""Synthetic correctness fixtures, never evidence of trading performance."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import atlas_v08 as v


def candles(n=1200):
    rng = np.random.default_rng(7)
    prices = 100*np.exp(np.cumsum(rng.normal(0,.002,n)))
    return pd.DataFrame({'timestamp':np.arange(n)*v.STEP*1000, 'open':prices,
                         'high':prices*1.01,'low':prices*.99,'close':prices,'volume':1.})

@pytest.fixture
def cfg():
    return json.loads((v.PROJECT/'paper_config.json').read_text())


def test_endpoint():
    assert v.endpoint('2026-01-01T04:00:00Z') % v.STEP == 0

@pytest.mark.parametrize('end',['2026-01-01','2026-01-01T01:00:00Z','2999-01-01T00:00:00Z'])
def test_bad_endpoint(end):
    with pytest.raises(ValueError): v.endpoint(end)


def test_exact_sources():
    f=candles()
    report, _, anomalies=v.crosscheck(f,f,0,len(f)*v.STEP)
    assert report['passed'] and anomalies.empty


def test_recent_subset_is_not_full_history():
    f=candles()
    report, _, anomalies=v.crosscheck(f,f.iloc[-200:],0,len(f)*v.STEP)
    assert not report['passed'] and len(anomalies)==1000


def test_price_divergence():
    f=candles(); k=f.copy(); k[['open','high','low','close']]*=1.02
    report,_,a=v.crosscheck(f,k,0,len(f)*v.STEP)
    assert not report['passed'] and len(a)==len(f)

@pytest.mark.parametrize('kind',['duplicate','nan','unaligned','future'])
def test_reject_bad_data(kind):
    f=candles()
    if kind=='duplicate': f.loc[1,'timestamp']=0
    if kind=='nan': f.loc[1,'close']=np.nan
    if kind=='unaligned': f.loc[1,'timestamp']+=1
    if kind=='future': f.loc[len(f)-1,'timestamp']+=v.STEP*1000
    with pytest.raises(ValueError): v.crosscheck(f,candles(),0,len(f)*v.STEP)


def test_complete_hours_only(tmp_path,monkeypatch):
    monkeypatch.setattr(v.time,'sleep',lambda _:None)
    def fetch(url,path):
        return [[i*3600,99,101,100,100,1] for i in range(8) if i!=2]
    f,gaps=v.coinbase_history(0,8*3600,tmp_path,fetch)
    assert len(f)==1 and gaps==[0] and f.volume.iloc[0]==4


def test_bootstrap_reproducible():
    values=np.random.default_rng(4).normal(0,.01,50)
    assert v.stationary_bootstrap(values,100)==v.stationary_bootstrap(values,100)
    b=v.stationary_bootstrap(np.zeros(50),100)
    assert b['p_one_sided']==1 and b['ci_low']==0


def test_holm():
    assert v.holm([.01,.04,.03])==pytest.approx([.03,.06,.06])


def test_simulation_gap_rejected(cfg):
    f=candles().drop(index=500)
    with pytest.raises(ValueError): v.simulate(f,541,1000,v.MODELS[0],cfg)


def test_no_future_signal_leak(cfg):
    f=candles(); a=v.simulate(f,541,900,v.MODELS[1],cfg)
    f.loc[900:,'close']*=3
    b=v.simulate(f,541,900,v.MODELS[1],cfg)
    assert a[0]==b[0]
    pd.testing.assert_frame_equal(a[1],b[1])


def test_risk_change_rejected(cfg):
    cfg['max_allocation']=.5
    with pytest.raises(ValueError): v.simulate(candles(),541,900,v.MODELS[0],cfg)


def test_next_open_buy_sell_and_open_trade(cfg,monkeypatch):
    f=candles(600); f[['open','close']]=100.; f.high=101.; f.low=99.
    enter=np.zeros(600,dtype=bool); leave=enter.copy(); enter[541]=True; leave[544]=True
    monkeypatch.setattr(v,'signals',lambda *args:(enter,leave))
    m,curve,trades,_=v.simulate(f,541,550,v.MODELS[0],cfg)
    assert len(trades)==1 and trades[0]['entry_time']==f.timestamp.iloc[542]
    assert trades[0]['exit_time']==f.timestamp.iloc[545] and m['return']<0
    leave[:]=False
    m,_,trades,_=v.simulate(f,541,550,v.MODELS[0],cfg)
    assert not trades and m['open_at_end'] and m['return']<0


def test_benchmark_allocation_and_cost(cfg,monkeypatch):
    f=candles(600); enter=np.zeros(600,dtype=bool)
    monkeypatch.setattr(v,'signals',lambda *args:(enter,enter))
    for a in (.1,.2,.5):
        m,_,_,_=v.simulate(f,541,550,v.MODELS[0],cfg,a)
        expected=1-a+a*f.close.iloc[549]*(1-.0005)*(1-.006)/(f.open.iloc[541]*(1+.0005)*(1+.006))
        assert m['benchmark_return']==pytest.approx(expected-1)
        assert m['return']==0 and m['trades']==0


def test_no_holdout_evaluation(cfg,monkeypatch):
    f=candles(2000); f.attrs['holdout_start']=int(f.timestamp.iloc[1600])
    seen=[]
    original=v.simulate
    def tracked(frame,lo,hi,*args,**kw):
        seen.append(int(frame.timestamp.iloc[hi-1])); return original(frame,lo,hi,*args,**kw)
    monkeypatch.setattr(v,'simulate',tracked)
    monkeypatch.setattr(v,'stationary_bootstrap',lambda *a:{'p_one_sided':1.})
    results,_,_,_=v.research(f,cfg,.006,.0005,100)
    assert not results.empty and max(seen)<f.attrs['holdout_start']


def test_failed_api_preserves_account_and_report(tmp_path,monkeypatch):
    before=v.v05.protected_hashes(v.PROJECT)
    def failure(*a): raise TimeoutError('test timeout')
    monkeypatch.setattr(v,'coinbase_history',failure)
    out=tmp_path/'out'
    result=v.run(out,days=730,end='2026-01-01T00:00:00Z',repetitions=100)
    assert result['status']=='BLOCKED' and not result['passed']
    assert before==v.v05.protected_hashes(v.PROJECT)
    assert (out/'manifest.json').exists()
    with pytest.raises(FileExistsError): v.run(out,days=730,end='2026-01-01T00:00:00Z')


def test_invalid_costs_no_output(tmp_path):
    with pytest.raises(ValueError): v.run(tmp_path/'out',fee=float('nan'))
    assert not (tmp_path/'out').exists()


def test_archive_import(tmp_path):
    f=candles(10); f.timestamp//=1000; f['trades']=1
    p=tmp_path/'XBTEUR_240.csv';f.to_csv(p,header=False,index=False)
    restored=v.kraken_archive(p,0,10*v.STEP)
    pd.testing.assert_frame_equal(restored,candles(10))
