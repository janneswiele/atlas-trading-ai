"""Synthetic fixtures only: these tests are not performance evidence."""
import copy
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from atlas09 import core as c
from atlas09.report import render
from atlas09.market import PublicMarket

ROOT=Path(__file__).parent
@pytest.fixture
def cfg():
    value=json.loads((ROOT/'atlas_v09_config.json').read_text()); value['enabled']=True
    return value
@pytest.fixture
def frame():
    price=100+np.sin(np.arange(240)/5)
    return pd.DataFrame(dict(timestamp=(c.WARMUP_START+np.arange(240)*c.STEP)*1000,
        open=price,high=price+1,low=price-1,close=price,volume=np.ones(240)))

def clock(frame): return int(frame.timestamp.iloc[-1]/1000)+c.STEP+10

def prepared(cfg,frame,monkeypatch,enter=True,leave=False):
    now=clock(frame)
    monkeypatch.setattr(c,'generate_signals',lambda f,m:(pd.Series([enter]*len(f)),pd.Series([leave]*len(f)),f,''))
    monkeypatch.setattr(c.v084,'candidate_signals',lambda f,m:(np.full(len(f),enter),np.full(len(f),leave)))
    s=c.new_state(cfg,now-100,'code')
    return c.prepare(s,frame,cfg,now)

def quote(now,price=100): return dict(bid=price,ask=price,exchange_time=now,observed_at=now)


def test_buy_budget_fees_and_restore(cfg,frame,monkeypatch):
    s=prepared(cfg,frame,monkeypatch); now=clock(frame)+1
    s=c.settle(s,quote(now),cfg,now)
    for a in s['accounts'].values():
        assert a['cash']==pytest.approx(80)
        assert a['basis']==pytest.approx(20)
        assert a['quantity']==pytest.approx(20/(100*1.0005*1.006))
        assert a['fees']==pytest.approx(20*.006/1.006)
    restored=json.loads(json.dumps(s)); c.validate_state(restored,cfg,'code')
    assert c.settle(restored,quote(now+1),cfg,now+1)==restored

@pytest.mark.parametrize('price,reason',[(97,'STOP_LOSS'),(105,'TAKE_PROFIT'),(100,'SIGNAL_EXIT')])
def test_sell_reasons(cfg,frame,monkeypatch,price,reason):
    s=prepared(cfg,frame,monkeypatch); now=clock(frame)+1
    s=c.settle(s,quote(now),cfg,now)
    original=s['accounts'][c.MODELS[0]].copy()
    s['pending']=dict(at=now+1,expires=now+300,signals={m:dict(enter=False,exit=True) for m in c.MODELS})
    s=c.settle(s,quote(now+2,price),cfg,now+2)
    a=s['accounts'][c.MODELS[0]]
    assert a['quantity']==0 and a['closed']==1
    expected=original['quantity']*price*.9995*.994
    assert a['cash']==pytest.approx(80+expected)
    assert a['realized']==pytest.approx(expected-20)
    assert next(e for e in s['events'] if e['kind']=='SELL')['payload']['reason']==reason

@pytest.mark.parametrize('price,field',[(40,'max_drawdown'),(84,'daily_loss_limit')])
def test_loss_halt_persists(cfg,frame,monkeypatch,price,field):
    s=prepared(cfg,frame,monkeypatch); now=clock(frame)+1
    s=c.settle(s,quote(now),cfg,now)
    s['pending']=dict(at=now+1,expires=now+300,signals={m:dict(enter=True,exit=False) for m in c.MODELS})
    s=c.settle(s,quote(now+2,price),cfg,now+2)
    assert all(a['halted'] and a['quantity']==0 for a in s['accounts'].values())
    assert next(e for e in s['events'] if e['kind']=='SELL')['payload']['reason']=='RISK_HALT'

@pytest.mark.parametrize('mutation',['future','gap','duplicate','nan','negative','holdout','stale'])
def test_bad_candles(cfg,frame,mutation):
    now=clock(frame)
    if mutation=='future': now-=20
    elif mutation=='gap': frame=frame.drop(15)
    elif mutation=='duplicate': frame.loc[1,'timestamp']=frame.loc[0,'timestamp']
    elif mutation=='nan': frame.loc[2,'close']=float('nan')
    elif mutation=='negative': frame.loc[2,'close']=-1
    elif mutation=='holdout': frame.timestamp-=240*c.STEP*1000
    elif mutation=='stale': now+=3600
    s=c.new_state(cfg,clock(frame)-100 if mutation!='holdout' else c.WARMUP_START+1,'code')
    before=copy.deepcopy(s)
    with pytest.raises(ValueError): c.prepare(s,frame,cfg,now)
    assert s==before

@pytest.mark.parametrize('field,value',[('bid',0),('ask',float('nan')),('ask',90),('ask',120),('exchange_time',1),('observed_at',1)])
def test_bad_quote(cfg,frame,monkeypatch,field,value):
    s=prepared(cfg,frame,monkeypatch); before=copy.deepcopy(s); now=clock(frame)+1
    q=quote(now); q[field]=value
    with pytest.raises(ValueError): c.settle(s,q,cfg,now)
    assert s==before


def test_expiry_never_retro_fills(cfg,frame,monkeypatch):
    s=prepared(cfg,frame,monkeypatch); now=clock(frame)+301
    result=c.settle(s,quote(now),cfg,now)
    assert result['pending'] is None
    assert result['events'][-1]['kind']=='EXPIRED_NO_FILL'
    assert result['accounts']==s['accounts']


def test_duplicate_and_revised_bar(cfg,frame,monkeypatch):
    s=prepared(cfg,frame,monkeypatch); now=clock(frame)+1
    s=c.settle(s,quote(now),cfg,now)
    s2=c.prepare(s,frame,cfg,now+1)
    assert s2['pending'] is None and s2['accounts']==s['accounts']
    frame.loc[0,'volume']+=1
    with pytest.raises(ValueError,match='revised'): c.prepare(s2,frame,cfg,now+2)


def test_pending_restart_not_replaced(cfg,frame,monkeypatch):
    s=prepared(cfg,frame,monkeypatch)
    again=c.prepare(s,frame,cfg,clock(frame)+1)
    assert again['pending']==s['pending']
    c.validate_state(again,cfg,'code')


def test_warmup_and_activation_no_backfill(cfg,frame):
    now=clock(frame)
    s=c.new_state(cfg,now,'code')
    s=c.prepare(s,frame,cfg,now)
    assert s['pending'] is None and s['events'][-1]['kind']=='WARMUP'
    s=c.new_state(cfg,now-100,'code'); s=c.prepare(s,frame.iloc[-200:],cfg,now)
    assert s['pending'] is None


def test_kill_switch_and_errors(cfg,frame):
    now=clock(frame); s=c.new_state(cfg,now-100,'code')
    for i in range(3): s=c.failed(s,now+i,'API unavailable')
    assert s['circuit'] and all(a['cash']==100 for a in s['accounts'].values())
    with pytest.raises(ValueError): c.prepare(s,frame,cfg,now+4)
    cfg['enabled']=False
    with pytest.raises(ValueError): c.new_state(cfg,now,'code')

@pytest.mark.parametrize('mutation',['cash','event','config','code','position'])
def test_integrity(cfg,mutation):
    s=c.new_state(cfg,c.WARMUP_START+10,'code')
    code='code'
    if mutation=='cash': s['accounts'][c.MODELS[0]]['cash']=500
    if mutation=='event': s['events'][0]['payload']['mode']='LIVE'
    if mutation=='config': cfg['fee']=.001
    if mutation=='code': code='different'
    if mutation=='position':
        s['accounts'][c.MODELS[0]]['quantity']=1
        s['seal']=c.digest({k:v for k,v in s.items() if k!='seal'})
    with pytest.raises(ValueError): c.validate_state(s,cfg,code)


def test_config_baseline(cfg):
    production=json.loads((ROOT/'paper_config.json').read_text())
    c.config_check(cfg,production)
    cfg['risk']['max_allocation']=.5
    with pytest.raises(ValueError): c.config_check(cfg,production)

@pytest.mark.parametrize('model',c.MODELS)
def test_strategy_causality(frame,model):
    def sig(f):
        if model in c.v084.CANDIDATES: return c.v084.candidate_signals(f,model)
        a,b,*_=c.generate_signals(f,model); return a.to_numpy(),b.to_numpy()
    a,b=sig(frame)
    future=frame.copy(); future.loc[220:,'close']=200;future.loc[220:,'high']=201
    aa,bb=sig(future)
    assert np.array_equal(a[:220],aa[:220]) and np.array_equal(b[:220],bb[:220])


def test_dashboard_empty_and_escape(cfg,tmp_path):
    s=c.new_state(cfg,c.WARMUP_START+1,'code'); s=c.failed(s,c.WARMUP_START+2,'<script>alert(1)</script>')
    target=tmp_path/'dashboard.html'; render(s,target)
    content=target.read_text()
    assert 'Keine erfundene' in content and '&lt;script&gt;' in content
    assert '<script>alert(1)</script>' not in content


def test_market_api_failure(tmp_path,monkeypatch):
    import requests
    monkeypatch.setattr(requests,'get',lambda *a,**k: (_ for _ in ()).throw(requests.Timeout('offline')))
    with pytest.raises(requests.Timeout): PublicMarket(tmp_path).candles(c.WARMUP_START+c.STEP+10)


def test_real_evidence_hashes():
    import hashlib
    folder=ROOT/'research_evidence/v085'
    for path,expected in json.loads((folder/'SHA256SUMS.json').read_text()).items():
        assert hashlib.sha256((folder/path).read_bytes()).hexdigest()==expected


def test_two_runner_persistence_and_conflict(cfg,tmp_path):
    import subprocess
    from atlas09.persist import checkpoint
    def git(path,*args):
        return subprocess.run(['git','-C',str(path),*args],check=True,capture_output=True,text=True).stdout.strip()
    remote=tmp_path/'remote.git'; remote.mkdir(); git(remote,'init','--bare')
    first=tmp_path/'first';first.mkdir();git(first,'init');git(first,'remote','add','origin',str(remote))
    s=c.new_state(cfg,c.WARMUP_START+10,'code')
    (first/'ledger.json').write_text(json.dumps(s));checkpoint(first)
    second=tmp_path/'second'
    subprocess.run(['git','clone','--branch','atlas-v0.9-data',str(remote),str(second)],check=True,capture_output=True)
    restored=json.loads((second/'ledger.json').read_text());c.validate_state(restored,cfg,'code')
    restored=c.failed(restored,c.WARMUP_START+11,'test-only error')
    (second/'ledger.json').write_text(json.dumps(restored));checkpoint(second)
    s=c.failed(s,c.WARMUP_START+12,'stale runner')
    (first/'ledger.json').write_text(json.dumps(s))
    with pytest.raises(subprocess.CalledProcessError): checkpoint(first)
    assert git(remote,'show','refs/heads/atlas-v0.9-data:ledger.json')==json.dumps(restored)


def test_workflow_and_protected_paths():
    import yaml
    workflow=yaml.safe_load((ROOT/'.github/workflows/atlas-v09.yml').read_text())
    assert workflow['permissions']=={'contents':'read'}
    assert workflow['concurrency']['cancel-in-progress'] is False
    steps=workflow['jobs']['shadow']['steps']
    execution=next(x['run'] for x in steps if x.get('id')=='run')
    assert 'atlas_v09.py' in execution and '--git-ledger' in execution and 'paper.py' not in execution
    text=(ROOT/'.github/workflows/atlas-v09.yml').read_text()
    assert '--force' not in text and 'HEAD:refs/heads/atlas-v0.9-data' in text


def test_missed_cycles_are_not_backfilled(cfg,frame,monkeypatch):
    s=prepared(cfg,frame,monkeypatch); now=clock(frame)+1
    s=c.settle(s,quote(now),cfg,now)
    shifted=frame.copy(); shifted.timestamp+=3*c.STEP*1000
    # Constant fixtures maintain overlap consistency.
    s['seen']={}
    advanced=c.prepare(s,shifted,cfg,now+3*c.STEP)
    assert any(e['kind']=='MISSED_CANDLES_NO_BACKFILL' and e['payload']['missed']==2 for e in advanced['events'])
    assert advanced['accounts']==s['accounts']

@pytest.mark.parametrize('problem',['none','missing_hour','conflict','kraken_error','kraken_gap','price_anomaly','bad_ohlc'])
def test_official_response_formats(tmp_path,problem):
    start=c.WARMUP_START
    class Fake(PublicMarket):
        def get(self,url,params=None):
            if 'coinbase' in url:
                rows=[[start+i*3600,99,101,100,100,1] for i in range(8)]
                if problem=='missing_hour': rows.pop(2)
                if problem=='conflict': rows.append([start,99,101,100,100,2])
                if problem=='bad_ohlc': rows[0][1]=102
                return rows
            rows=[[start+i*c.STEP,'100','101','99','100','100','4',4] for i in range(2)]
            if problem=='kraken_gap': rows.pop()
            if problem=='price_anomaly':
                for row in rows: row[1:5]=['200','201','199','200']
            return {'error':['error'] if problem=='kraken_error' else [],'result':{'XXBTZEUR':rows,'last':start}}
    market=Fake(tmp_path)
    if problem=='none':
        frame,quality=market.candles(start+2*c.STEP+10)
        assert len(frame)==2 and frame.volume.tolist()==[4,4] and quality['status']=='PASS'
    else:
        with pytest.raises(ValueError): market.candles(start+2*c.STEP+10)


def test_runner_persists_decision_before_quote(cfg,frame,tmp_path,monkeypatch):
    import atlas_v09 as cli
    root=tmp_path/'code';root.mkdir()
    (root/'atlas_v09_config.json').write_text(json.dumps(cfg))
    (root/'paper_config.json').write_text((ROOT/'paper_config.json').read_text())
    monkeypatch.setattr(cli,'ROOT',root)
    monkeypatch.setattr(cli,'source_hash',lambda _: 'code')
    now=clock(frame); folder=tmp_path/'ledger';folder.mkdir()
    s=c.new_state(cfg,now-100,'code');(folder/'ledger.json').write_text(json.dumps(s))
    times=iter([now,now,now+2])
    monkeypatch.setattr(cli.time,'time',lambda:next(times))
    class Fake:
        def __init__(self,*args): pass
        def candles(self,now): return frame,{'status':'PASS'}
        def quote(self):
            saved=json.loads((folder/'ledger.json').read_text())
            assert saved['pending']['at']==now
            return quote(now+1)
    monkeypatch.setattr(cli,'PublicMarket',Fake)
    cli.run(folder)
    restored=json.loads((folder/'ledger.json').read_text()); c.validate_state(restored,cfg,'code')
    assert restored['events'][-1]['kind']=='VALUATION'
    assert (folder/'dashboard.html').is_file()


def test_runner_missing_state_never_resets(cfg,tmp_path,monkeypatch):
    import atlas_v09 as cli
    root=tmp_path/'code';root.mkdir()
    (root/'atlas_v09_config.json').write_text(json.dumps(cfg))
    (root/'paper_config.json').write_text((ROOT/'paper_config.json').read_text())
    monkeypatch.setattr(cli,'ROOT',root);monkeypatch.setattr(cli,'source_hash',lambda _: 'code')
    with pytest.raises(ValueError,match='Missing state'): cli.run(tmp_path/'shadow')
    assert not (tmp_path/'shadow/ledger.json').exists()

@pytest.mark.parametrize('fee',[0,.005,.006,.008,.012,.018])
def test_cost_model_matches_v085_stop_take(fee):
    from atlas_v085 import stop_take_round_trip
    theoretical=stop_take_round_trip(fee)
    bought=c.fill(20,100,'buy',fee,.0005)
    win=c.fill(bought['quantity'],bought['price']*1.04,'sell',fee,.0005)['cash']/20-1
    loss=c.fill(bought['quantity'],bought['price']*.98,'sell',fee,.0005)['cash']/20-1
    # Fields in the existing v0.8.5 audit are preserved unchanged.
    assert win==pytest.approx(theoretical['take_profit_net_pct_at_exact_threshold']/100)
    assert loss==pytest.approx(theoretical['stop_loss_net_pct_at_exact_threshold']/100)


def test_unchanged_historical_and_production_modules():
    import hashlib
    manifest=json.loads((ROOT/'V09_BASELINE_SHA256.json').read_text())
    for filename,expected in manifest['files'].items():
        assert hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()==expected, filename


def test_dashboard_import_has_no_network_side_effect(monkeypatch):
    import requests, importlib
    monkeypatch.setattr(requests,'get',lambda *a,**k: (_ for _ in ()).throw(AssertionError('network on import')))
    module=importlib.import_module('atlas_dashboard_v09')
    assert callable(module.main)


def test_workflow_shell_syntax(tmp_path):
    import yaml,subprocess
    workflow=yaml.safe_load((ROOT/'.github/workflows/atlas-v09.yml').read_text())
    for job in workflow['jobs'].values():
        for i,step in enumerate(job['steps']):
            if 'run' in step:
                path=tmp_path/f'step{i}.sh';path.write_text(step['run'])
                subprocess.run(['bash','-n',str(path)],check=True,capture_output=True)


def test_workflow_orphan_branch_never_modifies_main(cfg,tmp_path):
    import subprocess
    from atlas09.persist import checkpoint
    def git(path,*args):
        return subprocess.run(['git','-C',str(path),*args],check=True,capture_output=True,text=True).stdout.strip()
    remote=tmp_path/'origin.git';remote.mkdir();git(remote,'init','--bare')
    code=tmp_path/'source';code.mkdir();git(code,'init','-b','main')
    (code/'paper_state.json').write_text('{"protected":true}')
    git(code,'add','.');git(code,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','production fixture')
    git(code,'remote','add','origin',str(remote));git(code,'push','origin','main')
    original=git(remote,'rev-parse','main')
    data=tmp_path/'data'
    git(code,'worktree','add','--orphan','-b','atlas-v0.9-data',str(data))
    (data/'ledger.json').write_text(json.dumps(c.new_state(cfg,c.WARMUP_START+10,'code')))
    checkpoint(data)
    assert git(remote,'rev-parse','main')==original
    assert (code/'paper_state.json').read_text()=='{"protected":true}'
    assert not (data/'paper_state.json').exists()


def test_streamlit_dashboard_starts_without_existing_ledger(monkeypatch):
    import requests
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(requests,'get',lambda *a,**k: (_ for _ in ()).throw(requests.HTTPError('404 no study activated')))
    app=AppTest.from_file(str(ROOT/'atlas_dashboard_v09.py')).run(timeout=15)
    assert len(app.exception)==0
    assert any('Keine verifizierten Forward-Daten' in w.value for w in app.warning)
