"""Remote ZIP correctness tests use fake HTTP responses: no exchange requests."""
import csv
import io
import re
import zipfile
from datetime import datetime, timezone

import pytest

import atlas_v08_kraken_fetch as k


class FakeResponse(io.BytesIO):
    def __init__(self, data, content_range, status=206):
        super().__init__(data)
        self.status = status
        self.headers = {'Content-Range': content_range, 'ETag': '"stable"'}

    def getcode(self):
        return self.status


class FakeHTTP:
    def __init__(self, content, split=2, status=206, prefix="fake"):
        self.data = {}
        size = len(content)
        for i in range(split):
            self.data[f'https://unit.test/{prefix}/{i}'] = content[size*i//split:size*(i+1)//split]
        self.status = status
        self.calls = 0

    def __call__(self, req, timeout=45):
        self.calls += 1
        content = self.data[req.full_url]
        m = re.fullmatch(r'bytes=(\d+)-(\d+)', req.headers['Range'])
        assert m, req.headers
        a, b = map(int, m.groups())
        return FakeResponse(content[a:b+1], f'bytes {a}-{b}/{len(content)}', self.status)

    def urls(self):
        return tuple(self.data)


def build_zip(csv_data, *, second_market=False):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr('unrelated/ETHUSD_240.csv', b'not the market')
        # Writes a ZIP64 local file header even when the test CSV is short.
        with z.open('prefix/XBTEUR_240.csv', 'w', force_zip64=True) as f:
            f.write(csv_data)
        if second_market:
            z.writestr('another/XBTEUR_240.csv', csv_data)
    return stream.getvalue()


def candles_csv(n=24):
    stream = io.StringIO()
    out = csv.writer(stream)
    for i in range(n):
        out.writerow([i * k.STEP, 100, 102, 99, 101, 1.25, 3])
    return stream.getvalue().encode()


def test_split_zip_reads_only_selected_market():
    content = build_zip(candles_csv())
    fake = FakeHTTP(content, 5)
    with k.SegmentedRangeReader(fake.urls(), opener=fake, block_size=1024, cache_blocks=2) as reader:
        assert reader.read(7) == content[:7]
        reader.seek(-12, io.SEEK_END)
        assert reader.read() == content[-12:]
        reader.seek(0)
        selected, meta = k.extract_market(reader)
        assert selected == candles_csv()
        assert meta['member'] == 'prefix/XBTEUR_240.csv'
        assert reader.transferred < 30_000
    assert fake.calls > 5


def test_merged_two_official_zip_sources_no_gaps():
    a, b = candles_csv(24), candles_csv(32)
    # Q3 fixture starts after the first fixture, analogous to a quarterly update.
    b = b'\n'.join(b.splitlines()[24:]) + b'\n'
    af, bf = FakeHTTP(build_zip(a), 3, prefix="full"), FakeHTTP(build_zip(b), 2, prefix="q3")
    sources = [('full', af.urls()), ('quarter', bf.urls())]
    def opener(req, timeout=45):
        return af(req,timeout) if req.full_url in af.data else bf(req,timeout)
    rows, report = k.fetch_archives(0, 32*k.STEP, source_groups=sources, opener=opener)
    assert len(rows) == 32
    assert report['expected_bars'] == report['observed_bars'] == 32
    assert report['coverage'] == 1
    assert len(report['sources']) == 2
    assert report['full_cross_exchange_validation'] is False
    assert report['strategy_approval'] is False


def test_unavailable_period_reports_gaps():
    fake = FakeHTTP(build_zip(candles_csv(12)))
    rows, report = k.fetch_archives(0, 24*k.STEP, source_groups=[('demo',fake.urls())], opener=fake)
    assert len(rows) == 12
    assert report['coverage'] == .5
    assert report['missing_bars'] == 12


def test_range_ignored_is_hard_failure():
    fake = FakeHTTP(build_zip(candles_csv()), status=200)
    with pytest.raises(k.RangeError, match='byte-range support'):
        k.SegmentedRangeReader(fake.urls(), opener=fake)


def test_wrong_market_and_duplicate_market_rejected():
    fake = FakeHTTP(build_zip(candles_csv(), second_market=True))
    with k.SegmentedRangeReader(fake.urls(), opener=fake) as reader:
        with pytest.raises(ValueError, match='exactly one'):
            k.extract_market(reader)


def test_malformed_candles_and_duplicate_rows_rejected():
    f = candles_csv(2)
    with pytest.raises(ValueError, match='Duplicate'):
        k.parse_csv(f+f, 0, 4*k.STEP)
    with pytest.raises(ValueError, match='Impossible'):
        k.parse_csv(b'0,100,98,99,101,1,3\n', 0, 4*k.STEP)
    with pytest.raises(ValueError, match='Non-4h'):
        k.parse_csv(b'60,100,102,99,101,1,3\n', 0, 4*k.STEP)


@pytest.mark.parametrize('stamp', ['2026-11-01T01:00:00Z','2026-10-01T00:00:00','2026-10-01T01:00:00+01:00','2026-10-01T00:00:00.5Z'])
def test_reject_not_exact_utc_4h_boundary(stamp):
    with pytest.raises(ValueError):
        k.parse_utc(stamp)


def test_preflight_rejects_later_than_archived_quarter(tmp_path,monkeypatch):
    monkeypatch.setattr(k,'fetch_archives',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('network touched')))
    out=tmp_path/'download.csv';manifest=tmp_path/'manifest.json'
    code = k.run_cli(['--start','2023-11-01T00:00:00Z','--end','2026-11-01T00:00:00Z',
                      '--output',str(out),'--manifest',str(manifest)])
    assert code == 2 and not out.exists()
    assert 'stop' in manifest.read_text()


def test_preflight_emits_provenance_but_no_approval(tmp_path,monkeypatch):
    rows = [(0,'100','102','99','101','1','4')]
    audit = {'expected_bars':1,'observed_bars':1,'coverage':1,'sources':[]}
    monkeypatch.setattr(k,'fetch_archives', lambda *a,**kw:(rows,audit))
    out=tmp_path/'download.csv';manifest=tmp_path/'manifest.json'
    code=k.run_cli(['--start','1970-01-01T00:00:00Z','--end','1970-01-01T04:00:00Z',
                    '--output',str(out),'--manifest',str(manifest)])
    assert code==0 and out.exists()
    assert 'DOWNLOADED_AND_VALIDATED_SOURCE_FORMAT' in manifest.read_text()
    with pytest.raises(SystemExit,match='overwrite'):
        k.run_cli(['--start','1970-01-01T00:00:00Z','--end','1970-01-01T04:00:00Z',
                    '--output',str(out),'--manifest',str(manifest)])
