"""Offline security, causality, reproducibility and integration tests for v1.0."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import copy
import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml
from atlas10.policy import Assumptions, STEP_MS, HOLDOUT_BLOCK_START_MS, approved_csv, validate_bars
from atlas10.signals import Candidate, candidates, signals
from atlas10.backtest import simulate
from atlas10.research import evaluate, windows
from atlas10.monitor import verify_ledger, _digest
from atlas10.proposals import propose

ROOT=Path(__file__).resolve().parent
SAMPLE=ROOT/'examples/atlas10/SYNTHETIC_4h.csv'
MANIFEST=ROOT/'examples/atlas10/SYNTHETIC_4h.approval.json'

@pytest.fixture(scope='module')
def bars():
    frame,meta=approved_csv(SAMPLE,MANIFEST,min_bars=800)
    return frame


def test_approved_fixture_honest_and_pinned(bars):
    assert len(bars)==840
    assert json.loads(MANIFEST.read_text())['source_type']=='synthetic'
    assert json.loads(MANIFEST.read_text())['sha256']==hashlib.sha256(SAMPLE.read_bytes()).hexdigest()

@pytest.mark.parametrize('field,value',[('fee',-0.01),('fee',0.03),('slippage',0.02),('initial_cash',101),('allocation',0.5),('allocation',0.10)])
def test_frozen_assumptions_fail_closed(field,value):
    with pytest.raises(ValueError):replace(Assumptions(),**{field:value}).validate()

@pytest.mark.parametrize('field,value',[('timestamp',None),('open',float('nan')),('high',0),('volume',-1)])
def test_invalid_market_data_rejected(bars,field,value):
    df=bars.iloc[:300].copy()
    df.loc[df.index[1],field]=df.loc[df.index[0],field] if value is None else value
    with pytest.raises(ValueError):validate_bars(df)


def test_out_of_order_and_missing_candle_blocked(bars):
    df=bars.iloc[:300].copy().drop(index=35)
    with pytest.raises(ValueError,match='Missing/duplicate'):validate_bars(df)


def test_ohlc_shape_mismatch_blocked(bars):
    df=bars.iloc[:300].copy()
    df.loc[40,'low']=df.loc[40,'open']*1.01
    with pytest.raises(ValueError,match='OHLC'):validate_bars(df)


def test_single_timestamp_alignment_blocked(bars):
    df=bars.iloc[:300].copy()
    df.loc[40,'timestamp']+=1
    with pytest.raises(ValueError,match='aligned'):validate_bars(df)


def test_manifest_tampering_blocks_research(tmp_path):
    path=tmp_path/'changed.csv'
    path.write_bytes(SAMPLE.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='SHA256'):approved_csv(path,MANIFEST)


def test_observed_post_holdout_is_blocked(tmp_path,bars):
    data=bars.iloc[:720].copy()
    shift=HOLDOUT_BLOCK_START_MS-int(data.timestamp.iloc[0])
    data['timestamp']+=shift
    file=tmp_path/'observed.csv';data.to_csv(file,index=False)
    meta=json.loads(MANIFEST.read_text())
    meta.update(source_type='observed',sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                start_ms=int(data.timestamp.iloc[0]),end_exclusive_ms=int(data.timestamp.iloc[-1])+STEP_MS,
                approval_id='test-observed')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='post-holdout'):approved_csv(file,manifest)

@pytest.mark.parametrize('family',['sma','ema','momentum','donchian','atr_breakout'])
def test_causal_signals_unaffected_by_future_bars(bars,family):
    spec=Candidate(family,fast=20,slow=60)
    prefix=bars.iloc[:400]
    history=(signals(prefix,spec)[0][-30:],signals(prefix,spec)[1][-30:])
    changed=bars.copy()
    changed.loc[changed.index>=400,'close']*=1.5
    changed.loc[changed.index>=400,'high']*=1.6
    future=(signals(changed,spec)[0][370:400],signals(changed,spec)[1][370:400])
    assert np.array_equal(history[0],future[0])
    assert np.array_equal(history[1],future[1])


def test_unique_whitelisted_candidate_grid():
    cs=candidates();assert len(cs)==30
    assert len({s.identifier for s in cs})==len(cs)
    with pytest.raises(ValueError):Candidate('arbitrary_python_strategy')


def test_paper_trading_is_virtual_and_fee_aware(bars):
    s=simulate(bars,Candidate('sma',20,60),start=240,end=600)
    assert s.metrics['virtual_only'] is True
    assert s.metrics['closed_trades']>=0
    assert all(p['equity']>=0 for p in s.curve)
    assert all(o['fee']>=0 for o in s.orders)
    assert all(o['side'] in ('BUY','SELL') for o in s.orders)
    assert all(o['quantity']>0 for o in s.orders)
    assert 0 <= s.metrics['fees_paid']


def test_paper_simulation_is_deterministic(bars):
    a=simulate(bars,Candidate('momentum',20,60),start=300,end=720)
    b=simulate(bars,Candidate('momentum',20,60),start=300,end=720)
    assert a.metrics==b.metrics and a.orders==b.orders


def test_next_open_not_same_candle_execution(bars,monkeypatch):
    import atlas10.backtest as mod
    start=240
    def only_one_entry(df,spec):
        enter=np.zeros(len(df),bool); leave=np.zeros(len(df),bool)
        enter[start]=True
        return enter,leave
    monkeypatch.setattr(mod,'signals',only_one_entry)
    s=simulate(bars,Candidate('sma',20,60),start=start,end=start+7)
    buys=[o for o in s.orders if o['side']=='BUY']
    assert len(buys)==1
    assert buys[0]['timestamp']==int(bars.timestamp.iloc[start+1])


def test_buy_never_exceeds_twenty_percent_of_initial_cash(bars,monkeypatch):
    import atlas10.backtest as mod
    start=240
    def enter(df,spec):
        a=np.zeros(len(df),bool);b=np.zeros(len(df),bool);a[start-1]=True;return a,b
    monkeypatch.setattr(mod,'signals',enter)
    s=simulate(bars,Candidate('sma',20,60),start=start,end=start+6)
    buy=next(x for x in s.orders if x['side']=='BUY')
    assert buy['quantity']*buy['execution_price']*(1+.006)<=20+1e-9
    assert s.curve[0]['cash']==pytest.approx(80)


def test_no_intrabar_stop_fills(bars,monkeypatch):
    import atlas10.backtest as mod
    start=240
    df=bars.iloc[:start+7].copy()
    df.loc[start+1,'low']=df.loc[start+1,'open']*.70
    df.loc[start+1,'close']=df.loc[start+1,'open']
    df.loc[start+1,'high']=max(df.loc[start+1,'high'],df.loc[start+1,'open'])
    def enter(df,spec):
        a=np.zeros(len(df),bool);b=np.zeros(len(df),bool);a[start-1]=True;return a,b
    monkeypatch.setattr(mod,'signals',enter)
    s=simulate(df,Candidate('sma',20,60),start=start,end=start+5)
    assert s.orders[0]['side']=='BUY'
    assert all(o['side']!='SELL' or o['timestamp']!=int(df.timestamp.iloc[start+1]) for o in s.orders)


def test_walkforward_ranges_have_no_train_validation_overlap():
    w=windows(840)
    assert len(w)==3
    for a,b,c in w:assert a<b<c
    assert all(w[i+1][1]==w[i][2] for i in range(len(w)-1))


def test_train_only_selection_unaffected_by_validation_scores(bars,monkeypatch):
    import atlas10.research as research
    a=Candidate('sma',10,40);b=Candidate('ema',10,40)
    def stub(df,spec,start,end,cfg):
        # During training A wins, during validation B is better.
        train = end-start>120
        good = ((spec==a) if train else (spec==b))
        metrics={'alpha_net':.2 if good else -.2,'max_drawdown':-.01,'closed_trades':10,
                 'return_net':.2 if good else -.2}
        return SimpleNamespace(metrics=metrics, orders=[])
    monkeypatch.setattr(research,'simulate',stub)
    report=research.evaluate(bars,json.loads(MANIFEST.read_text()),grid=(a,b))
    assert all(x['winner_id']==a.identifier for x in report['fold_results'])
    assert report['execution_permission'] is False
    assert report['champion'] is None


def test_synthetic_positive_screen_cannot_approve(bars):
    provenance=json.loads(MANIFEST.read_text())
    report=evaluate(bars,provenance,grid=candidates()[:2])
    assert report['data_source_type']=='synthetic'
    assert report['aggregate_validation']['research_screen_passed'] is False
    assert report['execution_permission'] is False


def test_research_fee_stress_validation(bars):
    with pytest.raises(ValueError,match='fee stress'):
        evaluate(bars,json.loads(MANIFEST.read_text()),grid=candidates()[:2],fee_multiplier=3)


def make_ledger():
    state={'version':'0.9','activation':1793798169.,'circuit':False,'failures':0,
           'accounts':{str(i):{'cash':100,'quantity':0,'equity':100,'closed':0,'fees':0} for i in range(4)},
           'events':[]}
    event={'id':0,'previous':'0'*64,'kind':'ACTIVATED','time':1793798169.,'payload':{}}
    event['hash']=_digest(event)
    state['events'].append(event)
    state['seal']=_digest(state)
    return state


def test_monitor_validates_ledger_hashes():
    s=verify_ledger(make_ledger())
    assert s['integrity'].startswith('EVENT_CHAIN')
    assert len(s['accounts'])==4 and s['last_event']=='ACTIVATED'

@pytest.mark.parametrize('what',['cash','event','seal','quantity'])
def test_monitor_rejects_tampering(what):
    state=make_ledger()
    if what=='cash':state['accounts']['0']['cash']=100000
    elif what=='event':state['events'][0]['kind']='BUY'
    elif what=='seal':state['seal']='x'*64
    else:state['accounts']['0']['quantity']=-1
    with pytest.raises(ValueError):verify_ledger(state)


def test_monitor_fails_if_nonsensical_account_even_with_valid_seal():
    state=make_ledger();state['accounts']['0']['equity']=-1
    state['seal']=_digest({k:v for k,v in state.items() if k!='seal'})
    with pytest.raises(ValueError,match='Invalid virtual account'):verify_ledger(state)


def test_proposals_no_autopromotion():
    report={'schema':'atlas-research-v1.0','execution_permission':False,
            'aggregate_validation':{'folds_not_outperforming':1,'closed_trades':2,'worst_fold_drawdown':-.12}}
    proposal=propose(report)
    assert proposal['auto_merge'] is False
    assert proposal['auto_trade'] is False
    assert len(proposal['suggestions'])>=2


def test_proposals_reject_live_order_report():
    with pytest.raises(ValueError):propose({'schema':'atlas-research-v1.0','execution_permission':True})


def test_v10_dashboard_has_no_import_time_network_access(monkeypatch):
    import importlib,requests
    monkeypatch.setattr(requests,'get',lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('network import')))
    module=importlib.import_module('atlas10.dashboard')
    assert callable(module.main)


def test_staged_scheduler_is_outside_main_workflow_location():
    sched=ROOT/'STAGED_ONLY/.github/workflows/atlas-v10-forward-scheduler.yml'
    assert sched.exists()
    assert not (ROOT/'.github/workflows/atlas-v10-forward-scheduler.yml').exists()
    y=yaml.safe_load(sched.read_text())
    assert y['permissions']=={'contents':'read'}
    assert y['concurrency']['cancel-in-progress'] is False
    script=sched.read_text()
    assert 'python atlas_v09.py --directory ../atlas-state --git-ledger' in script
    assert 'python paper.py' not in script
    assert '--activate' not in script
    assert '--force' not in script
    assert 'paper_state.json' not in script
    assert 'atlas-v0.9-data' in script
    assert 'refs/heads/main' in script


def test_new_research_workflow_cannot_trade_or_write():
    path=ROOT/'.github/workflows/atlas-v10-research.yml'
    content=path.read_text()
    assert 'contents: read' in content and 'contents: write' not in content
    assert 'atlas_v10.py research' in content and 'atlas_v10.py propose' in content
    assert 'python atlas_v09.py' not in content


def test_workflow_shell_syntax_with_bash(tmp_path):
    import subprocess
    for path in (ROOT/'.github/workflows/atlas-v10-research.yml',
                 ROOT/'STAGED_ONLY/.github/workflows/atlas-v10-forward-scheduler.yml'):
        y=yaml.safe_load(path.read_text())
        for job in y['jobs'].values():
            for i,step in enumerate(job['steps']):
                if 'run' in step:
                    script=tmp_path/f'step-{i}.sh';script.write_text(step['run'])
                    subprocess.run(['bash','-n',str(script)],check=True,capture_output=True)


def test_unchanged_protected_source_files():
    manifest=json.loads((ROOT/'V09_BASELINE_SHA256.json').read_text())
    for file,sha in manifest['files'].items():
        assert hashlib.sha256((ROOT/file).read_bytes()).hexdigest()==sha,file


def test_no_evolved_code_contains_private_order_adapter():
    source='\n'.join(p.read_text() for p in (ROOT/'atlas10').glob('*.py'))
    for text in ('create_order(', 'create_market_buy_order(', 'ccxt.binance(', 'api_secret =', 'withdraw('):
        assert text not in source


def test_sealed_historical_period_explicitly_blocked(tmp_path,bars):
    from atlas10.policy import SEALED_HOLDOUT_START_MS
    data=bars.iloc[:720].copy()
    # Try to smuggle an observed set beginning exactly in the sealed 2026 holdout.
    data['timestamp'] += SEALED_HOLDOUT_START_MS-int(data.timestamp.iloc[0])
    file=tmp_path/'sealed.csv';data.to_csv(file,index=False)
    meta=json.loads(MANIFEST.read_text())
    meta.update(source_type='observed',sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                start_ms=int(data.timestamp.iloc[0]),end_exclusive_ms=int(data.timestamp.iloc[-1])+STEP_MS)
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='Sealed historical holdout'):
        approved_csv(file,manifest)


def test_unregistered_post_holdout_forward_dataset_blocked(tmp_path,bars):
    from atlas10.policy import POST_HOLDOUT_FORWARD_START_MS
    data=bars.iloc[:720].copy()
    data['timestamp'] += POST_HOLDOUT_FORWARD_START_MS-int(data.timestamp.iloc[0])
    file=tmp_path/'forward.csv';data.to_csv(file,index=False)
    meta=json.loads(MANIFEST.read_text())
    meta.update(source_type='observed',sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                start_ms=int(data.timestamp.iloc[0]),end_exclusive_ms=int(data.timestamp.iloc[-1])+STEP_MS)
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='unregistered post-holdout'):
        approved_csv(file,manifest)
    meta['forward_protocol_registration']='OWNER_APPROVED_FRESH_FORWARD_RESEARCH'
    manifest.write_text(json.dumps(meta))
    valid,policy=approved_csv(file,manifest)
    assert len(valid)==720 and policy['source_type']=='observed'


def test_static_ipad_snapshot_cannot_operate_trading(tmp_path):
    from atlas10.report import snapshot
    ledger=tmp_path/'ledger.json';ledger.write_text(json.dumps(make_ledger()))
    path=snapshot(ledger,tmp_path/'dashboard.html')
    markup=path.read_text()
    assert 'statische Momentaufnahme' in markup
    assert 'Keine Echtgeld-Trades' in markup
    assert 'EVENT_CHAIN_AND_SEAL_PASS' in markup
    assert '<html' in markup and '100.00 €' in markup
    assert 'fetch(' not in markup and 'api_key' not in markup


def test_cli_full_synthetic_integration(tmp_path):
    import subprocess,sys
    exe=ROOT/'atlas_v10.py';out=tmp_path/'out'
    call=[sys.executable,str(exe)]
    r=subprocess.run(call+['research','--csv',str(SAMPLE),'--approval',str(MANIFEST),'--out',str(out)],
                     check=True,capture_output=True,text=True,timeout=45)
    assert 'RESEARCH_ONLY_NOT_APPROVED' in r.stdout
    r2=subprocess.run(call+['propose','--report',str(out/'research.json'),'--out',str(out)],
                      check=True,capture_output=True,text=True,timeout=45)
    assert 'REVIEW_REQUIRED' in r2.stdout
    s=json.loads((out/'summary.json').read_text())
    assert s['passed_research_screen'] is False
    assert (out/'PROPOSALS_FOR_REVIEW.md').exists()
