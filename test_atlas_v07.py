"""Atlas v0.7: independent data cross-check, long-window and account safety."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import atlas_v07 as v7
from paper import STEP


def synthetic(n=1050, end=None):
    end = (int(time.time()) // STEP) * STEP if end is None else end
    idx = np.arange(n)
    close = 75000 + 2500 * np.sin(idx/17) + idx * 10
    op = close * (1 + .001 * np.cos(idx/3))
    return pd.DataFrame({
        'timestamp': (end - (n-idx) * STEP) * 1000,
        'open': op, 'high': np.maximum(op, close) * 1.004,
        'low': np.minimum(op, close) * .996, 'close': close,
        'volume': np.full(n, 2.0)
    })


def to_kraken_json(frame, now, add_unclosed=True):
    rows = []
    for x in frame.itertuples(index=False):
        rows.append([int(x.timestamp//1000), str(x.open), str(x.high), str(x.low),
                     str(x.close), '0', str(x.volume), 100])
    if add_unclosed:
        # The last returned row is an UNFINISHED candle and must be excluded.
        rows.append([now, '100', '120', '90', '110', '0', '1', 1])
    return {'error': [], 'result': {'XXBTZEUR': rows, 'last': now}}


def test_kraken_valid_and_unclosed_excluded():
    now = (int(time.time()) // STEP) * STEP
    df = synthetic(260, end=now)
    output = v7.kraken_rows(to_kraken_json(df, now), now)
    assert len(output) == 260
    assert output.timestamp.tolist() == df.timestamp.tolist()


def test_kraken_invalid_payload_is_rejected():
    with pytest.raises(ValueError):
        v7.kraken_rows({'error': ['EQuery:Unknown asset pair'], 'result': {}}, int(time.time()))
    with pytest.raises(ValueError):
        v7.kraken_rows({'error': [], 'result': {}}, int(time.time()))


def test_kraken_duplicate_and_alignment_rejected():
    now = (int(time.time()) // STEP) * STEP
    d = synthetic(220, end=now)
    payload = to_kraken_json(d, now, add_unclosed=False)
    payload['result']['XXBTZEUR'].append(payload['result']['XXBTZEUR'][0].copy())
    with pytest.raises(ValueError, match='Duplicated'):
        v7.kraken_rows(payload, now)
    payload['result']['XXBTZEUR'].pop()
    payload['result']['XXBTZEUR'][0][0] += 1
    with pytest.raises(ValueError, match='Unaligned'):
        v7.kraken_rows(payload, now)


def test_kraken_bad_ohlc_rejected():
    now = (int(time.time()) // STEP) * STEP
    d = synthetic(220, end=now)
    payload = to_kraken_json(d, now, add_unclosed=False)
    payload['result']['XXBTZEUR'][10][2] = '1'  # high below real price
    with pytest.raises(ValueError):
        v7.kraken_rows(payload, now)


def test_cross_exchange_matching_recent_prices_pass():
    now = (int(time.time()) // STEP) * STEP
    k = synthetic(260, end=now)
    c = k.copy()
    c.loc[:, 'close'] *= 1.001
    c['high'] = c[['high','close']].max(axis=1)
    result, matches = v7.compare_recent_sources(c, k, now)
    assert result['status'] == 'PASS_RECENT_SUBSET'
    assert result['overlap_candles'] == 260
    assert result['close_difference_max_pct'] == pytest.approx(.1)
    assert len(matches) == 260


def test_cross_exchange_outlier_fails_closed():
    now = (int(time.time()) // STEP) * STEP
    c = synthetic(260, end=now)
    k = c.copy()
    c.loc[40,'close'] *= 1.04
    c.loc[40,'high'] = max(c.loc[40,'close'], c.loc[40,'high'])
    report, _ = v7.compare_recent_sources(c, k, now)
    assert report['status'] == 'FAIL'
    assert report['mismatch_count_above_tolerance'] == 1


def test_cross_exchange_insufficient_overlap_fails_closed():
    now = (int(time.time()) // STEP) * STEP
    k = synthetic(260, end=now)
    c = k.tail(150).reset_index(drop=True)
    report, _ = v7.compare_recent_sources(c, k, now)
    assert report['status'] == 'FAIL'
    assert report['overlap_candles'] == 150


def test_cross_exchange_stale_fails_closed():
    now = (int(time.time()) // STEP) * STEP
    d = synthetic(260, end=now - 5 * STEP)
    report, _ = v7.compare_recent_sources(d, d, now)
    assert report['status'] == 'FAIL'
    assert any('stale' in x for x in report['failures'])


def test_cross_exchange_reports_kraken_gaps():
    now = (int(time.time()) // STEP) * STEP
    k = synthetic(260, end=now)
    incomplete = k.drop(index=list(range(50, 70))).reset_index(drop=True)
    result, _ = v7.compare_recent_sources(k, incomplete, now)
    assert result['status'] == 'FAIL'
    assert result['kraken_gap_fraction'] > .02


@pytest.mark.parametrize('n,expected', [(1000,1), (1077,1), (1164,1), (2135,3)])
def test_60day_windows_nonoverlap_and_holdout_sealed(n, expected):
    sealed, windows = v7.validation_blocks(n)
    assert len(windows) == expected
    assert sealed == int(n*.8)
    assert all(hi-lo == 360 and hi <= sealed for lo,hi in windows)
    assert all(windows[i][1] <= windows[i+1][0] for i in range(len(windows)-1))
    assert windows[0][0] == 400


def test_short_segment_fails_closed():
    with pytest.raises(ValueError):
        v7.validation_blocks(999)


def test_regime_uses_only_prior_candles():
    df = synthetic(1000)
    a = v7.preceding_regime(df, 400)
    df.loc[400:, 'close'] = df.loc[400:, 'close'] * 100
    b = v7.preceding_regime(df, 400)
    assert a == b
    assert a['classification_based_on_validation_or_holdout'] is False


def test_archive_sha_verified_but_not_provenance(tmp_path):
    csv = tmp_path/'data.csv'
    csv.write_text('real? no guarantee')
    report = tmp_path/'v06_research.json'
    report.write_text(json.dumps({
        'version':'0.6.0','market':'BTC/EUR',
        'saved_4h_file_sha256':hashlib.sha256(csv.read_bytes()).hexdigest(),
    }))
    assert v7.validate_v06_saved_archive(csv,report)['archive_origin_still_not_independently_authenticated']
    csv.write_text('tampered')
    with pytest.raises(ValueError, match='hash'):
        v7.validate_v06_saved_archive(csv,report)


def test_archive_requires_csv(tmp_path):
    with pytest.raises(ValueError, match='needs --csv'):
        v7.run(tmp_path/'results', audit_json=tmp_path/'x.json')


def test_long_validation_fixed_rules_holdout_never_evaluated(monkeypatch):
    df = synthetic(1050)
    seen = []
    original = v7.evaluate_period
    def controlled(frame, strategy, lo, hi, fee, slip):
        assert hi <= int(len(frame)*.8), 'SEALED HOLDOUT WAS ACCESSED'
        seen.append((lo,hi))
        return original(frame,strategy,lo,hi,fee,slip)
    monkeypatch.setattr(v7,'evaluate_period',controlled)
    diag = v7.long_validation(df,.001,.0005,{'status':'PASS_RECENT_SUBSET'},offline=True)
    assert diag['long_validation_windows_per_strategy'] == 1
    assert diag['sealed_final_20pct_ever_evaluated'] is False
    assert diag['paper_trading_authorized'] is False
    assert diag['real_trading_authorized'] is False
    assert all(not x['manual_research_review_candidate_only'] for x in diag['strategies'])
    assert any(a == 400 and b == 760 for a,b in seen)


def test_cli_archive_mode_is_readonly_and_produces_results(tmp_path):
    data = synthetic(1050)
    csv = tmp_path/'previous.csv'
    data.to_csv(csv,index=False)
    result = v7.run(tmp_path/'output',csv=csv)
    assert result['cross_exchange_recent']['status'] == 'NOT_CHECKED_OFFLINE'
    assert result['offline_archive'] is True
    assert result['long_validation_windows_per_strategy'] == 1
    assert all(not x['manual_research_review_candidate_only'] for x in result['strategies'])
    assert (tmp_path/'output'/'v06_research.json').exists()
    assert (tmp_path/'output'/'v07_validation.json').exists()
    assert (tmp_path/'output'/'SUMMARY_V07_DE.txt').exists()
    assert not (tmp_path/'output'/'strategy_report.json').exists()
    assert not (tmp_path/'output'/'paper_state.json').exists()
    assert not (tmp_path/'output'/v7.KRAKEN_CSV).exists()


def test_diagnostics_cannot_write_inside_project():
    with pytest.raises(ValueError):
        v7.run(v7.PROJECT, csv=Path('does_not_matter.csv'))


def test_immutable_risk_config_explicitly_enforced():
    cfg = dict(v7.v06.EXPECTED_RISK)
    cfg['max_allocation'] = .21
    with pytest.raises(ValueError):
        v7.v06.verify_unchanged_config(cfg)


def test_kraken_fetch_offline_mock_and_json_parse():
    import io
    now = (int(time.time()) // STEP) * STEP
    source = synthetic(220,end=now)
    raw = json.dumps(to_kraken_json(source, now)).encode()
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self,*args): self.close()
    fetched = v7.fetch_kraken_recent(now,request_fn=lambda request,timeout: Response(raw),sleep_fn=lambda _:None)
    assert len(fetched) == 220
    assert fetched.close.iloc[0] == pytest.approx(source.close.iloc[0])


def test_failed_secondary_fetch_is_reported_and_never_authorizes(tmp_path, monkeypatch):
    df = synthetic(1050)
    def copied_verified_primary(output, **kwargs):
        output.mkdir(parents=True,exist_ok=True)
        csv_bytes = df.to_csv(index=False).encode()
        (output/'btc_eur_4h_research.csv').write_bytes(csv_bytes)
        (output/'v06_research.json').write_text('{"version":"0.6.0"}')
        return {'saved_4h_file_sha256':hashlib.sha256(csv_bytes).hexdigest()}
    monkeypatch.setattr(v7.v06,'run',copied_verified_primary)
    def fail(_):
        raise RuntimeError('Kraken unavailable')
    output=tmp_path/'research'
    output.mkdir()
    (output/v7.KRAKEN_CSV).write_text('STALE DO NOT TRUST')
    (output/v7.COMPARISON_CSV).write_text('STALE DO NOT TRUST')
    r=v7.run(output,kraken_fetch_fn=fail)
    assert r['cross_exchange_recent']['status']=='UNAVAILABLE_OR_INVALID'
    assert r['real_trading_authorized'] is False
    assert r['paper_trading_authorized'] is False
    assert not (output/v7.KRAKEN_CSV).exists()
    assert not (output/v7.COMPARISON_CSV).exists()
    assert all(not x['manual_research_review_candidate_only'] for x in r['strategies'])


def test_v07_detects_modified_v06_csv_during_run(tmp_path,monkeypatch):
    df=synthetic(1050)
    def tampered_v06(output,**kwargs):
        output.mkdir(parents=True,exist_ok=True)
        data=df.to_csv(index=False).encode()
        (output/'btc_eur_4h_research.csv').write_bytes(data)
        (output/'v06_research.json').write_text('{}')
        return {'saved_4h_file_sha256':'0'*64}
    monkeypatch.setattr(v7.v06,'run',tampered_v06)
    with pytest.raises(RuntimeError,match='hash mismatch'):
        v7.run(tmp_path/'results')
