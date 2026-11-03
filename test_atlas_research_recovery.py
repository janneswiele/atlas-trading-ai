"""Offline regression tests for real-candle historical recovery."""
import pytest
import atlas_research_recovery as rec


def hours(a, b):
    return [(ts,100.,105.,95.,101.,2.) for ts in range(a,b,3600)]


def quarters(t, include_all=True):
    q = {}
    for i in range(4 if include_all else 3):
        ts=t+900*i
        q[ts]=(ts,100.+i,105.+i,95.,101.+i,2.)
    return q


def test_no_missing_hours_does_not_query_quarters():
    r=rec.recover_window(0,7200,hourly_fn=hours,quarter_fn=lambda *_:pytest.fail('unnecessary recovery'))
    assert len(r)==2


def test_retry_one_hour_recovery():
    calls=[]
    def hourly(a,b):
        calls.append((a,b))
        return hours(a,b) if (b-a)==3600 else [hours(0,3600)[0]]
    r=rec.recover_window(0,7200,hourly_fn=hourly,quarter_fn=lambda *_:pytest.fail('not needed'))
    assert len(r)==2 and (3600,7200) in calls


def test_quarters_reconstruct_true_ohlcv():
    def hourly(a,b):
        return hours(0,3600) if (a,b)==(0,7200) else []
    r=rec.recover_window(0,7200,hourly_fn=hourly,quarter_fn=lambda a,b:quarters(a))
    assert r[1] == (3600,100.,108.,95.,104.,8.)


def test_missing_quarter_fails_closed():
    with pytest.raises(ValueError,match='Missing genuine'):
        rec.aggregate_hour(0,quarters(0,False))


def test_15m_parser_handles_boundary_and_validates():
    p=[[0,99,105,100,102,3],[900,99,105,100,103,4],[1800,99,105,100,104,5],[2700,99,106,100,105,6],[3600,99,107,100,105,7]]
    parsed=rec.parse_quarter_rows(p,0,3600)
    assert len(parsed)==4 and 3600 not in parsed
    assert rec.aggregate_hour(0,parsed)==(0,100.,106.,99.,105.,18.)


def test_invalid_quarter_rejected():
    with pytest.raises(ValueError,match='Impossible'):
        rec.parse_quarter_rows([[0,111,100,100,100,1]],0,3600)


def test_conflicting_duplicate_rejected():
    with pytest.raises(ValueError,match='Conflicting'):
        rec.parse_quarter_rows([[0,99,105,100,100,1],[0,98,105,100,100,1]],0,3600)
