import copy
import json
from pathlib import Path
import pandas as pd
import pytest
import paper
from research import build_report, evaluate_period

@pytest.fixture
def cfg(): return json.loads(Path('paper_config.json').read_text())

@pytest.fixture
def frame():
    ts = 1793692800
    return pd.DataFrame([[1000*(ts-(240-i)*paper.STEP),100.,101.,99.,100.,10.] for i in range(241)],columns=['timestamp','open','high','low','close','volume'])

def base(): return {'cash_eur':100.,'btc':0.,'entry_eur':None,'last_ts':0}

def clock(f): return int(f.timestamp.iloc[-1]/1000)+paper.STEP+60

def quote(f,p=100.): return {'bid':p,'ask':p,'observed_at':clock(f)}

def signals(monkeypatch, buy=False, sell=False):
    monkeypatch.setattr(paper,'generate_signals',lambda df,name:(pd.Series([buy]*len(df)),pd.Series([sell]*len(df)),df,'Controlled test signal'))
    monkeypatch.setattr(paper,'admitted',lambda *args:'SMA 20/50')

def test_buy_restore_sell_cost_accounting(frame,cfg,monkeypatch):
    signals(monkeypatch,buy=True)
    s=paper.cycle(base(),frame,quote(frame),cfg,None,clock(frame))
    assert s['cash_eur']==80 and s['btc']>0
    assert len(s['trades'])==1 and s['cost_basis_eur']==20
    restored=paper.migrate(json.loads(json.dumps(s)))
    later=frame.copy();later.timestamp+=paper.STEP*1000
    signals(monkeypatch,sell=True)
    out=paper.cycle(restored,later,quote(later,101),cfg,None,clock(later))
    assert out['btc']==0 and len(out['trades'])==2
    assert out['realized_pnl_eur']==pytest.approx(out['cash_eur']-100)
    assert out['fees_eur']==pytest.approx(sum(t['fee_eur'] for t in out['trades']))

def test_duplicate_and_delayed(frame,cfg,monkeypatch):
    signals(monkeypatch,buy=True)
    s=paper.cycle(base(),frame,quote(frame),cfg,None,clock(frame))
    duplicate=paper.cycle(s,frame,quote(frame),cfg,None,clock(frame))
    assert duplicate['trades']==s['trades'] and duplicate['cash_eur']==s['cash_eur']
    old=frame.copy();old.timestamp-=paper.STEP*1000
    with pytest.raises(ValueError): paper.cycle(s,old,quote(old),cfg,None,clock(old))

@pytest.mark.parametrize('bad',['nan','inf','gap','duplicate','negative','ohlc','future','stale'])
def test_bad_data_no_mutation(frame,cfg,bad):
    raw=base();original=copy.deepcopy(raw);f=frame.copy();now=clock(f)
    if bad in ('nan','inf'): f.loc[10,'close']=float(bad)
    elif bad=='gap': f=f.drop(index=10)
    elif bad=='duplicate': f.loc[10,'timestamp']=f.loc[9,'timestamp']
    elif bad=='negative': f.loc[10,'volume']=-1
    elif bad=='ohlc': f.loc[10,'high']=90
    elif bad=='future': now-=paper.STEP
    else: now+=paper.STEP
    with pytest.raises(ValueError): paper.cycle(raw,f,quote(frame),cfg,None,now)
    assert raw==original

def test_missing_approval_and_disabled(frame,cfg,monkeypatch):
    out=paper.cycle(base(),frame,quote(frame),cfg,None,clock(frame))
    assert not out['trades'] and out['cash_eur']==100
    signals(monkeypatch,buy=True);cfg['trading_enabled']=False
    out=paper.cycle(base(),frame,quote(frame),cfg,None,clock(frame))
    assert not out['trades']

def test_existing_legacy_position_exits_without_approval(frame,cfg):
    raw=base();raw.update(cash_eur=80,btc=.2,entry_eur=110,equity_eur=100)
    out=paper.cycle(raw,frame,quote(frame),cfg,None,clock(frame))
    assert out['btc']==0 and out['trades'][0]['net_pnl_eur'] is None
    assert out['legacy_snapshot']==raw

def test_loss_halt_persists(frame,cfg,monkeypatch):
    signals(monkeypatch,buy=True)
    s=paper.migrate(base());s['peak_equity_eur']=200
    out=paper.cycle(s,frame,quote(frame),cfg,None,clock(frame))
    assert out['halted'] and not out['trades']

def setup_dir(tmp_path,cfg):
    p=tmp_path/'paper_state.json';p.write_text(json.dumps(base()))
    (tmp_path/'paper_config.json').write_text(json.dumps(cfg));return p

def test_api_failure_preserves_bytes(tmp_path,cfg):
    p=setup_dir(tmp_path,cfg);old=p.read_bytes()
    def fail(now): raise TimeoutError('test')
    with pytest.raises(TimeoutError): paper.run(tmp_path,provider=fail,now=100)
    assert p.read_bytes()==old
    assert json.loads((tmp_path/'paper_status.json').read_text())['status']=='failed'

def test_migration_and_restart_on_disk(tmp_path,cfg,frame):
    p=setup_dir(tmp_path,cfg);old=p.read_bytes()
    provider=lambda now:(frame,quote(frame))
    first=paper.run(tmp_path,provider=provider,now=clock(frame))
    second=paper.run(tmp_path,provider=provider,now=clock(frame))
    assert second['cash_eur']==first['cash_eur'] and len(second['equity_history'])==1
    assert (tmp_path/'paper_state.pre-v04.json').read_bytes()==old

def test_corrupt_account_not_reset(tmp_path,cfg):
    p=setup_dir(tmp_path,cfg);p.write_text('{broken')
    with pytest.raises(ValueError): paper.run(tmp_path,provider=lambda _:pytest.fail('must not fetch'))
    assert p.read_text()=='{broken'

def test_atomic_write_failure(tmp_path,monkeypatch):
    p=tmp_path/'state.json';p.write_text('original')
    monkeypatch.setattr(paper.os,'replace',lambda *args:(_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError): paper.atomic_json(p,{'cash':100})
    assert p.read_text()=='original'

def test_risk_increase_rejected(cfg):
    cfg['max_allocation']=.21
    with pytest.raises(ValueError): paper.validate_config(cfg)

def test_research_short_history_rejected(frame):
    with pytest.raises(ValueError): build_report(frame,clock(frame))

def long_frame():
    ts=1793692800
    return pd.DataFrame([[1000*(ts-(1199-i)*paper.STEP),100.,101.,99.,100.,10.] for i in range(1200)],columns=['timestamp','open','high','low','close','volume'])

def test_holdout_cannot_change_winner(monkeypatch):
    import research
    calls=[]
    def fake(df,strategy,lo,hi,*args):
        calls.append((strategy,lo,hi))
        return {'trades':20,'return_pct':5 if strategy=='EMA Trend' else 2,'max_drawdown_pct':-1,'profit_factor':2,'buy_hold_return_pct':0}
    monkeypatch.setattr(research,'evaluate_period',fake)
    f=long_frame();r=build_report(f,clock(f))
    assert r['selected']=='EMA Trend'
    assert len(calls)==9 and calls[-1]==('EMA Trend',960,1200)
    f.loc[960:,'close']=100.5
    assert build_report(f,clock(f))['selected']==r['selected']

def test_report_eligibility_expiry_and_code(frame,cfg,monkeypatch):
    import research
    def fake(*args): return {'trades':20,'return_pct':5,'max_drawdown_pct':-1,'profit_factor':2,'buy_hold_return_pct':0}
    monkeypatch.setattr(research,'evaluate_period',fake)
    f=long_frame();now=clock(f);r=build_report(f,now)
    ts=int(f.timestamp.iloc[-1]/1000)+paper.STEP
    assert paper.admitted(r,cfg,now,ts) in paper.STRATEGIES
    assert paper.admitted(r,cfg,now+31*86400,ts) is None
    assert paper.admitted(r,cfg,now,ts-paper.STEP) is None
    r['strategy_hash']='changed';assert paper.admitted(r,cfg,now,ts) is None

def test_open_research_position_not_closed_trade(monkeypatch,frame):
    import research
    monkeypatch.setattr(research,'generate_signals',lambda df,name:(pd.Series([True]*len(df)),pd.Series([False]*len(df)),df,''))
    m=evaluate_period(frame,'SMA 20/50',0,len(frame))
    assert m['open_at_end'] and m['trades']==0

def test_signal_prefix_invariance(frame):
    from strategies import generate_signals,STRATEGIES
    for name in STRATEGIES:
        a,b,_,_=generate_signals(frame,name)
        aa,bb,_,_=generate_signals(frame.iloc[:220],name)
        assert a.iloc[:220].equals(aa) and b.iloc[:220].equals(bb)

def test_dashboard_import_and_render(monkeypatch):
    monkeypatch.setenv('ATLAS_LOCAL_STATE','1')
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_file('app.py').run(timeout=30)
    assert not at.exception
    assert any(m.label=='Virtueller Kontowert' and m.value=='100.00 €' for m in at.metric)

@pytest.mark.parametrize('bad',['inverted','wide','stale','nan'])
def test_bad_quotes(frame,cfg,bad):
    q=quote(frame)
    if bad=='inverted': q['ask']=90
    if bad=='wide': q['ask']=110
    if bad=='stale': q['observed_at']-=61
    if bad=='nan': q['bid']=float('nan')
    with pytest.raises(ValueError): paper.cycle(base(),frame,q,cfg,None,clock(frame))

def test_kraken_unfinished_candle_removed(frame,monkeypatch):
    now=clock(frame);data=frame.copy()
    last=data.iloc[-1].copy();last.timestamp+=paper.STEP*1000
    data=pd.concat([data,pd.DataFrame([last])],ignore_index=True)
    rows=[[int(r.timestamp/1000),r.open,r.high,r.low,r.close,100,r.volume,1] for r in data.itertuples()]
    monkeypatch.setattr(paper,'get_public',lambda endpoint,extra='':rows if endpoint=='OHLC' else {'b':['100'],'a':['100.1']})
    f,q=paper.market_snapshot(now)
    assert len(f)==len(frame) and int(f.timestamp.iloc[-1])==int(frame.timestamp.iloc[-1])

def test_concurrent_runs_serialized(tmp_path,frame,cfg):
    from concurrent.futures import ThreadPoolExecutor
    setup_dir(tmp_path,cfg)
    def task(): return paper.run(tmp_path,provider=lambda now:(frame,quote(frame)),now=clock(frame))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(task) for _ in range(2)]
        for f in futures: f.result()
    s=json.loads((tmp_path/'paper_state.json').read_text())
    assert len(s['equity_history'])==1 and len(s['decisions'])==2

def test_daily_limit_blocks_entry(frame,cfg,monkeypatch):
    signals(monkeypatch,buy=True)
    s=paper.migrate(base());s.update(risk_day=paper.utc(clock(frame))[:10],day_start_equity=104)
    out=paper.cycle(s,frame,quote(frame),cfg,None,clock(frame))
    assert not out['trades']

def test_dashboard_backtest_path(monkeypatch):
    import data
    from streamlit.testing.v1 import AppTest
    f=long_frame()
    info={'valid_candles':len(f),'missing_intervals':0,'first':int(f.timestamp.iloc[0]),'last':int(f.timestamp.iloc[-1]),'warnings':[],'candles':len(f),'exchange':'fake','symbol':'BTC/USDT','timeframe':'4h','api_rows_fetched':len(f),'cache_rows_reused':0}
    monkeypatch.setenv('ATLAS_LOCAL_STATE','1')
    monkeypatch.setattr(data,'fetch_history',lambda *args:(f,info))
    at=AppTest.from_file('app.py').run(timeout=30)
    next(b for b in at.button if b.label=='Historische Tests starten').click()
    at.run(timeout=30)
    assert not at.exception
    assert any(s.value=='Holdout-Ergebnisse' for s in at.subheader)

def test_real_fixed_research_rejects_flat_market():
    f=long_frame();r=build_report(f,clock(f))
    assert r['selected'] is None and all(c['reasons'] for c in r['candidates'])
