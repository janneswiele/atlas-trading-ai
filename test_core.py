import pandas as pd
import pytest
from atlas.backtest import backtest
from atlas.data import normalize, validate_frame, TIMEFRAME_MS


def candles(n=300):
    ts=1_700_000_000_000
    rows=[]
    for i in range(n):
        p=100+i*.1
        rows.append({"timestamp":ts+i*TIMEFRAME_MS["1h"],"open":p,"high":p+1,"low":p-1,"close":p+.2,"volume":100+i%5})
    return pd.DataFrame(rows)


def test_normalize_sorts_and_deduplicates():
    raw=[[2,10,12,9,11,1],[1,9,10,8,9,2],[2,10,13,9,12,3]]
    out=normalize(raw)
    assert out.timestamp.tolist()==[1,2]
    assert out.iloc[-1].close==12


def test_validate_reports_missing_interval():
    d=candles(3).drop(index=1).reset_index(drop=True)
    assert validate_frame(d,"1h")["missing_intervals"]==1


@pytest.mark.parametrize("strategy",["EMA Trend","RSI Reversion","Breakout"])
def test_backtest_is_finite_and_never_negative(strategy):
    m,trades,equity,diag=backtest(candles(),strategy)
    assert m["final_equity"]>=0
    assert len(equity)==300
    assert diag["candles_evaluated"]==300
    assert all(equity.equity>=0)


def test_invalid_costs_rejected():
    with pytest.raises(ValueError): backtest(candles(),"EMA Trend",fee_rate=1.0)


def test_signal_executes_at_next_open_and_stop_wins_intrabar(monkeypatch):
    import atlas.backtest as engine
    frame=pd.DataFrame([
        {"timestamp":1,"open":100,"high":101,"low":99,"close":100,"volume":10},
        {"timestamp":2,"open":110,"high":111,"low":109,"close":110,"volume":10},
        {"timestamp":3,"open":120,"high":130,"low":90,"close":110,"volume":10},
    ])
    ind=frame.copy(); ind["atr"]=1.0
    monkeypatch.setattr(engine,"generate_signals",lambda df,name,params=None:(
        pd.Series([True,False,False]),pd.Series([False,False,False]),ind,"test signal"))
    _,trades,_,_=engine.backtest(frame,"EMA Trend",fee_rate=0,slippage=0)
    assert len(trades)==1
    assert trades.iloc[0].entry_price==110
    assert trades.iloc[0].exit_reason.startswith("Stop-Loss")


def test_history_pagination_fetches_multiple_pages_and_caches(tmp_path):
    from atlas.data import fetch_history
    step=TIMEFRAME_MS["1h"]; base=1_700_000_000_000
    rows=[[base+i*step,100,102,99,101,10] for i in range(5)]
    class FakeExchange:
        has={"fetchOHLCV":True}; rateLimit=0
        calls=[]
        def __init__(self,config): pass
        def fetch_ohlcv(self,symbol,timeframe,since,limit):
            self.calls.append(since)
            return [r for r in rows if r[0]>=since][:2]
        def milliseconds(self): return base+10*step
    FakeExchange.calls=[]
    df,info=fetch_history("fake","BTC/USDT","1h",base,base+5*step,
                          cache_path=tmp_path/"cache.sqlite",page_limit=2,
                          exchange_factory=FakeExchange)
    assert len(df)==5
    assert len(FakeExchange.calls)==3
    assert info["api_rows_fetched"]==5
    df2,info2=fetch_history("fake","BTC/USDT","1h",base,base+5*step,
                             cache_path=tmp_path/"cache.sqlite",page_limit=2,
                             exchange_factory=FakeExchange)
    assert len(df2)==5 and info2["cache_rows_reused"]==5
    assert len(FakeExchange.calls)==3
