"""Fully offline input validation and fail-closed tests for Atlas research."""
import io
import json
from pathlib import Path
from urllib.error import HTTPError
import pandas as pd
import pytest
import atlas_research as ar


def four_hours(start, close=100.0):
    return [(start + i * ar.HOUR, close, close + 1, close - 1, close, 12.0) for i in range(4)]


def test_coinbase_row_order_and_boundary_filter():
    values = [[0, 90, 110, 100, 105, 9], [3600, 95, 120, 102, 115, 10], [7200, 95, 125, 110, 115, 10]]
    rows = ar.parse_hourly_rows(values, 0, 7200)
    assert rows == [(0, 100, 110, 90, 105, 9), (3600, 102, 120, 95, 115, 10)]

@pytest.mark.parametrize('payload', [None, {}, [[0, 1]], [[0, 0, 1, 1, 1, 1]], [[1, 1, 2, 1, 1, 1]], [[0, -1, 2, 1, 1, 1]]])
def test_rejects_bad_payload(payload):
    with pytest.raises(ValueError): ar.parse_hourly_rows(payload, 0, 3600)


def test_aggregate_4h_open_high_low_close_volume():
    now = ar.STEP * 1010 + 100
    # 180 days, 1080 bars. Fake data is only for TESTS and never an actual strategy report.
    def fetch(start,stop):
        return [(t, 100 + ((t//ar.HOUR)%10), 110, 90, 101, 2) for t in range(start,stop,ar.HOUR)]
    df=ar.fetch_history(now,180,fetch_fn=fetch,sleep_fn=lambda _:None)
    assert len(df)==1080
    assert df.timestamp.diff().iloc[1:].eq(ar.STEP*1000).all()
    assert df.iloc[0]['open']==100+(((now//ar.STEP*ar.STEP-180*86400)//ar.HOUR)%10)
    assert df.iloc[0]['high']==110
    assert df.iloc[0]['low']==90
    assert df.iloc[0]['close']==101
    assert df.iloc[0]['volume']==8


def test_missing_hour_fails_closed():
    now=ar.STEP*1100+300
    first=[None]
    def fetch(start,stop):
        rows=four_hours(start) if False else [(t,100.,101.,99.,100.,1.) for t in range(start,stop,ar.HOUR)]
        if first[0] is None:
            first[0]=start
        return [r for r in rows if r[0] != first[0]]
    with pytest.raises(ValueError, match='gaps'):
        ar.fetch_history(now,180,fetch_fn=fetch,sleep_fn=lambda _:None)


def test_conflicting_duplicate_fails_closed():
    now=ar.STEP*1100+300
    def fetch(start,stop):
        rows=[(t,100.,101.,99.,100.,1.) for t in range(start,stop,ar.HOUR)]
        if start==((now//ar.STEP)*ar.STEP-180*86400):
            rows.append((start,100.,102.,99.,100.,1.))
        return rows
    with pytest.raises(ValueError, match='Conflicting'):
        ar.fetch_history(now,180,fetch_fn=fetch,sleep_fn=lambda _:None)


def test_reject_unapproved_history_length():
    with pytest.raises(ValueError): ar.fetch_history(ar.STEP*1400+60,100,fetch_fn=lambda x,y:[],sleep_fn=lambda _:None)


def test_api_http_error_is_explicit():
    def fail(request, timeout):
        raise HTTPError(request.full_url,451,'Unavailable',{},None)
    with pytest.raises(RuntimeError,match='HTTP 451'):
        ar._fetch_window(0,ar.HOUR,request_fn=fail,sleep_fn=lambda _:None)


def test_report_is_candidate_not_authorization(tmp_path, monkeypatch):
    # Supply made-up candles for testing only and an explicit fake report builder.
    now=ar.STEP*1510+30
    def fetch(start,stop):
        return [(t,100.,101.,99.,100.,3.) for t in range(start,stop,ar.HOUR)]
    def build(df,now,fee,slip):
        return {'selected':None,'candidates':[], 'dummy_test_only':True}
    report,n=ar.research_to_directory(tmp_path,now=now,days=180,fetch_fn=fetch,
                                      sleep_fn=lambda _:None,build_fn=build)
    assert n==1080
    assert report['live_trading_approved'] is False
    assert (tmp_path/'strategy_report_CANDIDATE.json').exists()
    assert not (tmp_path/'strategy_report.json').exists()
    assert not (tmp_path/'paper_state.json').exists()
    assert not (tmp_path/'paper_config.json').exists()


def test_no_partial_report_on_provider_failure(tmp_path):
    def fail(start,stop): raise RuntimeError('Network not available')
    with pytest.raises(RuntimeError,match='Network'):
        ar.research_to_directory(tmp_path,now=ar.STEP*1510+30,days=180,fetch_fn=fail,
                                 sleep_fn=lambda _:None)
    assert not list(tmp_path.glob('*'))
