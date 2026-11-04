"""Sealed-holdout, replay and anti-tampering tests for v0.8.3."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import atlas_v083 as v


def candles(n=1600, drift=.002):
    rng = np.random.default_rng(843)
    prices = 100*np.exp(np.cumsum(rng.normal(drift/20,.003,n)))
    return pd.DataFrame({'timestamp':np.arange(n,dtype=np.int64)*v.v08.STEP*1000,
                         'open':prices,'high':prices*1.01,'low':prices*.99,
                         'close':prices,'volume':1.})


@pytest.fixture
def cfg():
    return json.loads((v.PROJECT/'paper_config.json').read_text())


def set_signal(monkeypatch, n, buys=(), sells=()):
    a=np.zeros(n,dtype=bool);b=a.copy()
    for i in buys:a[i]=True
    for i in sells:b[i]=True
    monkeypatch.setattr(v.v08,'signals',lambda frame,model,pair=None:(a[:len(frame)],b[:len(frame)]))


def stable_candles(n=800):
    f=candles(n)
    f[['open','high','low','close']]=[100.,101.,99.,100.]
    return f


def test_replay_no_trades(cfg,monkeypatch):
    f=stable_candles();set_signal(monkeypatch,len(f))
    d,e,b,_=v.replay_attribution(f,541,700,'SMA 20/50',cfg,.006,.0005)
    assert d['closed_trades']==0 and d['entries']==0 and d['flat_no_entry_signal_bars']==159
    assert d['bars_in_position']==0 and e==[] and len(b)==159


def test_next_open_entry_and_signal_exit(cfg,monkeypatch):
    f=stable_candles();set_signal(monkeypatch,len(f),buys=[543],sells=[548])
    d,e,_,tr=v.replay_attribution(f,541,556,'SMA 20/50',cfg,.006,.0005)
    assert d['entries']==1 and d['closed_trades']==1
    assert len(e)==len(tr)==1
    assert e[0]['entry_time']==int(f.timestamp.iloc[544])
    assert e[0]['exit_time']==int(f.timestamp.iloc[549])
    assert e[0]['exit_reason_primary']=='signal_exit'
    assert e[0]['hold_bars']==5
    assert d['exit_signal_exit']==1


def test_stop_loss_assessed_at_open(cfg,monkeypatch):
    f=stable_candles();set_signal(monkeypatch,len(f),buys=[543])
    f.loc[547,['open','close','low','high']]=[94.,94.,93.,101.]
    d,e,_,_=v.replay_attribution(f,541,556,'EMA Trend',cfg,.006,.0005)
    assert e[0]['exit_reason_primary']=='stop_loss'
    assert e[0]['exit_time']==int(f.timestamp.iloc[547])
    assert e[0]['exit_open_eur']==94


def test_take_profit_trigger(cfg,monkeypatch):
    f=stable_candles();set_signal(monkeypatch,len(f),buys=[543])
    f.loc[547,['open','close','low','high']]=[106.,106.,99.,107.]
    d,e,_,_=v.replay_attribution(f,541,556,'EMA Trend',cfg,.006,.0005)
    assert len(e)==1 and e[0]['exit_reason_primary']=='take_profit'


def test_multitrigger_priority_and_audit(cfg,monkeypatch):
    f=stable_candles();set_signal(monkeypatch,len(f),buys=[543],sells=[546])
    f.loc[547,['open','close','low','high']]=[94.,94.,93.,101.]
    _,e,_,_=v.replay_attribution(f,541,556,'SMA 20/50',cfg,.006,.0005)
    assert e[0]['exit_reason_primary']=='stop_loss'
    assert 'signal_exit' in e[0]['all_triggers'] and 'stop_loss' in e[0]['all_triggers']


def test_open_trade_excluded_from_completed(cfg,monkeypatch):
    f=stable_candles();set_signal(monkeypatch,len(f),buys=[543])
    m,trades,_,_=v.replay_attribution(f,541,556,'EMA Trend',cfg,.006,.0005)
    assert m['entries']==1 and m['closed_trades']==0 and m['open_position_at_window_end']
    assert trades==[]


def test_replay_rejects_gap(cfg):
    f=candles().drop(index=400).reset_index(drop=True)
    with pytest.raises(ValueError,match='gap'):
        v.replay_attribution(f,541,1100,'SMA 20/50',cfg,.006,.0005)


def test_replay_rejects_risk_change(cfg):
    f=candles();cfg['stop_loss']=.8
    with pytest.raises(ValueError):
        v.replay_attribution(f,541,1100,'SMA 20/50',cfg,.006,.0005)


def test_replay_requires_complete_warmup(cfg):
    with pytest.raises(ValueError):
        v.replay_attribution(candles(),190,700,'SMA 20/50',cfg,.006,.0005)


def test_future_candle_change_cannot_change_past(cfg):
    f=candles()
    a=v.replay_attribution(f,541,900,'SMA 20/50',cfg,.006,.0005)
    changed=f.copy();changed.loc[900:,'close']*=3;changed.loc[900:,'high']*=3
    changed.loc[900:,'open']*=3;changed.loc[900:,'low']*=3
    b=v.replay_attribution(changed,541,900,'SMA 20/50',cfg,.006,.0005)
    assert a[0]==b[0] and a[1]==b[1]
    pd.testing.assert_frame_equal(a[2],b[2])


@pytest.fixture
def fake_source(tmp_path,monkeypatch,cfg):
    source=tmp_path/'source';source.mkdir()
    frame=candles(1600)
    lo,hi=541,1081
    m,curve,_,_=v.v08.simulate(frame,lo,hi,'SMA 20/50',cfg,.2,.006,.0005)
    start=int(frame.timestamp.iloc[lo]);end=int(frame.timestamp.iloc[hi-1])+v.v08.STEP*1000
    window=pd.DataFrame([{'strategy':'SMA 20/50','segment':1,'start':start,'end_exclusive':end,
                          'days':90,'allocation':.2,'cost_factor':1,'parameters':'baseline',
                          'trades':m['trades'],'return':m['return']}])
    curve=curve.assign(strategy='SMA 20/50',window_start=start)
    manifest={'fee_rate_assumption':.006,'slippage_assumption':.0005,
              'protocol':{'primary_days':90},'git_commit':'fake-synthetic',
              'risk_sha256':v.sha256(v.PROJECT/'paper_config.json'),
              'source_hashes':{'atlas_v08.py':v.sha256(v.PROJECT/'atlas_v08.py')},
              'end_exclusive':'2026-10-01T00:00:00Z','holdout_start':'1972-01-01T00:00:00Z'}
    holdout=int(frame.timestamp.iloc[1400]);manifest['holdout_start']=pd.Timestamp(holdout,unit='ms',tz='UTC').isoformat()
    fake=[manifest,{'passed':False},{'passed':True},frame,window,curve,holdout]
    monkeypatch.setattr(v.v082,'load_verified',lambda _:tuple(fake))
    return source,fake


def test_analyze_synthetic_source(fake_source):
    src,_=fake_source
    windows,trades,bars,summary=v.analyze(src)
    assert len(windows)==1 and len(bars)==540
    assert summary['release_gate']['passed'] is False
    assert summary['release_gate']['holdout_evaluated'] is False
    assert summary['primary_90d_windows']==1
    assert all(bars.timestamp < 1400*v.v08.STEP*1000)


def test_archive_equity_tampering_rejected(fake_source):
    src,fake=fake_source
    fake[5].loc[0,'equity']+=.05
    with pytest.raises(ValueError,match='Archived equity curves'):
        v.analyze(src)


def test_wrong_code_hash_rejected(fake_source):
    src,fake=fake_source
    fake[0]['source_hashes']['atlas_v08.py']='invalid'
    with pytest.raises(ValueError,match='source version'):
        v.analyze(src)


def test_holdout_guard_rejects_window_inside_holdout(fake_source):
    src,fake=fake_source
    fake[6]=int(fake[4].iloc[0]['end_exclusive'])-v.v08.STEP*1000
    with pytest.raises(ValueError,match='sealed holdout'):
        v.analyze(src)


def test_duplicate_window_rejected(fake_source):
    src,fake=fake_source
    fake[4]=pd.concat([fake[4],fake[4]],ignore_index=True)
    with pytest.raises(ValueError,match='duplicated'):
        v.analyze(src)


def test_run_creates_outputs_and_never_overwrites(fake_source,tmp_path):
    src,_=fake_source
    before=v.v05.protected_hashes(v.PROJECT)
    out=tmp_path/'diagnostics'
    summary=v.run(src,out)
    assert (out/'SUMMARY_V083_DE.md').is_file() and (out/'attributed_trades.csv').is_file()
    assert summary['release_gate']['paper_trading_authorized'] is False
    assert before==v.v05.protected_hashes(v.PROJECT)
    with pytest.raises(ValueError,match='nonexistent'):
        v.run(src,out)


def test_failed_analysis_leaves_no_output(fake_source,tmp_path):
    src,fake=fake_source
    fake[0]['source_hashes']={}
    out=tmp_path/'notcreated'
    with pytest.raises(ValueError):v.run(src,out)
    assert not out.exists()


def test_empty_signal_and_invalid_cost(cfg):
    f=candles()
    with pytest.raises(ValueError):v.replay_attribution(f,541,900,'UNREGISTERED',cfg,.006,.0005)
    with pytest.raises(ValueError):v.replay_attribution(f,541,900,'SMA 20/50',cfg,-.1,.0005)


def test_report_never_claims_approval():
    txt=v.report_text({'source_end_exclusive':'2026-10-01','holdout_start':'2026-02-24',
                       'primary_90d_windows':0,'models':{},'limits':['No OOS']})
    assert 'keine Handelsfreigabe' in txt
