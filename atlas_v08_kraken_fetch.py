"""Read ONLY official Kraken XBTEUR_240.csv members over HTTP byte ranges.

The pre-2026-Q3 history lives in five ~2 GiB parts of ONE ZIP archive.
This module presents those parts as a seekable remote file to Python's
ZIP64-aware stdlib zipfile and transfers just the ZIP index and BTC/EUR CSV.
It fails closed if Range is unsupported; it never downloads the full archive,
changes trading state, substitutes candles, or certifies a strategy.

Source: https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import os
import re
import time
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://assets.kraken.com/marketing/institutions/"
FULL_PARTS = tuple(BASE + f"Kraken_OHLCVT_Full.zip.part{i:02d}" for i in range(5))
Q3_ARCHIVE = BASE + "Kraken_OHLCVT_2026Q3.zip"
MARKET_MEMBER = "XBTEUR_240.csv"
STEP = 4 * 3600
MAX_MEMBER_BYTES = 120_000_000
RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def parse_utc(value: str) -> int:
    value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamps with Z or +00:00 required")
    ts = int(dt.timestamp())
    if ts % STEP or dt.timestamp() != ts:
        raise ValueError("Only exact UTC 4h boundaries are accepted")
    return ts


class RangeError(RuntimeError):
    """A remote archive cannot be safely and exactly accessed in byte ranges."""


class SegmentedRangeReader(io.RawIOBase):
    """Seekable view over a concatenated multipart ZIP using ranged GETs.

    A 1 MiB LRU block cache reduces HTTP round-trips. Each response must
    cover exactly its requested byte range and (where supplied) match the
    ETag / Last-Modified snapshot from the first request.
    """

    def __init__(self, urls, *, opener=urlopen, block_size=1 << 20, cache_blocks=6, retries=2):
        super().__init__()
        if not urls or block_size < 1024 or cache_blocks < 1:
            raise ValueError("Invalid remote ZIP inputs")
        self.urls = tuple(urls)
        self.opener = opener
        self.block_size = block_size
        self.cache_blocks = cache_blocks
        self.retries = retries
        self.metadata = []
        self.ends = []
        self.transferred = 0
        self.requests = 0
        self.cache = OrderedDict()
        self.offset = 0
        for url in self.urls:
            body, total, validator = self._get(url, 0, 0, expected=None, validator=None)
            if len(body) != 1 or total < 1:
                raise RangeError("Empty or malformed official Kraken archive part")
            self.metadata.append({'url': url, 'size': total, 'validator': validator})
            self.ends.append(total + (self.ends[-1] if self.ends else 0))
        self.size = self.ends[-1]

    def _get(self, url, start, end, expected, validator):
        headers = {'Range': f'bytes={start}-{end}',
                   'Accept-Encoding': 'identity', 'User-Agent': 'AtlasResearch/0.8.1-archive-reader'}
        if validator:
            headers['If-Range'] = validator
        for attempt in range(self.retries + 1):
            try:
                with self.opener(Request(url, headers=headers), timeout=45) as response:
                    status = getattr(response, 'status', response.getcode())
                    if status != 206:
                        raise RangeError(f'HTTP {status}: byte-range support required for {url}')
                    h = response.headers
                    match = RANGE_RE.match(h.get('Content-Range', ''))
                    if not match:
                        raise RangeError(f'Missing valid Content-Range for {url}')
                    a, b, total = map(int, match.groups())
                    if (a, b) != (start, end) or (expected is not None and total != expected):
                        raise RangeError('Remote archive changed or returned the wrong bytes')
                    current_validator = h.get('ETag') or h.get('Last-Modified')
                    if validator and current_validator and current_validator != validator:
                        raise RangeError('Official archive changed during download')
                    body = response.read(end - start + 2)
                    if len(body) != end - start + 1:
                        raise RangeError('Incomplete HTTP Range response')
                    self.requests += 1
                    self.transferred += len(body)
                    return body, total, current_validator
            except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
                if attempt == self.retries:
                    raise RangeError(f'Unable to access remote Kraken archive {url}: {exc}') from exc
                time.sleep(attempt + 1)
        raise AssertionError('unreachable')

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.offset

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_END:
            offset += self.size
        elif whence == io.SEEK_CUR:
            offset += self.offset
        elif whence != io.SEEK_SET:
            raise ValueError('Unknown seek origin')
        if offset < 0:
            raise ValueError('Negative seek')
        self.offset = offset
        return self.offset

    def _block(self, piece, local_start):
        block = local_start // self.block_size * self.block_size
        key = (piece, block)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        p = self.metadata[piece]
        last = min(block + self.block_size, p['size']) - 1
        data, _, _ = self._get(p['url'], block, last, expected=p['size'], validator=p['validator'])
        self.cache[key] = data
        if len(self.cache) > self.cache_blocks:
            self.cache.popitem(last=False)
        return data

    def read(self, size=-1):
        if self.closed:
            raise ValueError('Read from closed range reader')
        if self.offset >= self.size:
            return b''
        if size is None or size < 0:
            size = self.size - self.offset
        size = min(size, self.size - self.offset)
        parts = []
        while size:
            piece = bisect.bisect_right(self.ends, self.offset)
            prev = 0 if piece == 0 else self.ends[piece - 1]
            local = self.offset - prev
            data = self._block(piece, local)
            within = local % self.block_size
            amount = min(size, len(data) - within)
            if amount <= 0:
                raise RangeError('Incorrect segment boundary')
            parts.append(data[within:within + amount])
            self.offset += amount
            size -= amount
        return b''.join(parts)


def extract_market(reader, *, market_member=MARKET_MEMBER):
    """Return official CSV bytes and metadata. Reject ambiguous market names."""
    with zipfile.ZipFile(reader, 'r', allowZip64=True) as archive:
        candidates = [i for i in archive.infolist()
                      if i.filename.rsplit('/', 1)[-1].upper() == market_member.upper()]
        if len(candidates) != 1:
            raise ValueError(f'Expected exactly one {market_member}, found {len(candidates)}')
        info = candidates[0]
        if info.file_size > MAX_MEMBER_BYTES or info.compress_size > MAX_MEMBER_BYTES:
            raise ValueError('Unexpectedly large BTC/EUR archive member')
        # zipfile verifies CRC while reading the complete selected member.
        data = archive.read(info)
        return data, {'member': info.filename, 'uncompressed_bytes': info.file_size,
                      'compressed_bytes': info.compress_size, 'sha256': hashlib.sha256(data).hexdigest(),
                      'crc32': f'{info.CRC:08x}'}


def parse_csv(data, start, end):
    """Parse 240m OHLCVT rows with strict schema, UTC grid and OHLC checks."""
    records = {}
    try:
        content = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('Kraken CSV is not valid UTF-8') from exc
    for i, row in enumerate(csv.reader(io.StringIO(content)), 1):
        if not row:
            continue
        if len(row) != 7:
            raise ValueError(f'Wrong OHLCVT field count on line {i}')
        try:
            stamp = int(row[0]); numeric = tuple(float(x) for x in row[1:])
        except (ValueError, OverflowError) as exc:
            raise ValueError(f'Invalid OHLCVT data on line {i}') from exc
        if stamp % STEP or not all(map(math.isfinite, numeric)):
            raise ValueError(f'Non-4h or nonfinite OHLCVT row {i}')
        op, high, low, close, volume, trades = numeric
        if min(op, high, low, close) <= 0 or high < max(op, close, low) or low > min(op, close) or volume < 0 or trades < 0 or int(trades) != trades:
            raise ValueError(f'Impossible OHLCVT values on line {i}')
        if start <= stamp < end:
            if stamp in records:
                raise ValueError(f'Duplicate 4h row in single archive: {stamp}')
            records[stamp] = (stamp, *row[1:])
    return records


def fetch_archives(start, end, *, source_groups=None, opener=urlopen):
    """Return validated rows and source audit metadata; never synthesize gaps."""
    if start >= end or start % STEP or end % STEP:
        raise ValueError('Invalid UTC research window')
    sources = source_groups if source_groups is not None else [('full_through_2026Q2', FULL_PARTS), ('2026Q3', (Q3_ARCHIVE,))]
    rows = {}
    audit = []
    for label, urls in sources:
        with SegmentedRangeReader(urls, opener=opener) as remote:
            data, member = extract_market(remote)
            selected = parse_csv(data, start, end)
            for ts, record in selected.items():
                if ts in rows and rows[ts] != record:
                    raise ValueError(f'Conflicting real Kraken candles across archives at {ts}')
                rows[ts] = record
            audit.append({'source': label, 'parts': [{'url': m['url'], 'bytes': m['size']} for m in remote.metadata],
                          'market_csv': member, 'matched_rows': len(selected),
                          'http_range_requests': remote.requests, 'bytes_transferred': remote.transferred})
    expected = (end - start) // STEP
    missing = expected - len(rows)
    return [rows[k] for k in sorted(rows)], {'market': 'Kraken BTC/EUR 240m (XBTEUR)',
           'window_start': datetime.fromtimestamp(start,timezone.utc).isoformat(),
           'window_end_exclusive': datetime.fromtimestamp(end,timezone.utc).isoformat(),
           'expected_bars': expected, 'observed_bars': len(rows), 'missing_bars': missing,
           'coverage': len(rows)/expected, 'sources': audit,
           'archive_notice': 'Official archives cover through 2026Q3 only; no synthetic candles.',
           'full_cross_exchange_validation': False,
           'strategy_approval': False}


def run_cli(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', required=True, help='Inclusive 4h UTC ISO boundary, e.g. 2023-10-02T00:00:00Z')
    p.add_argument('--end', required=True, help='Exclusive 4h UTC ISO boundary, latest archive 2026-10-01T00:00:00Z')
    p.add_argument('--output', default='atlas-data/XBTEUR_240.csv')
    p.add_argument('--manifest', default='atlas-data/kraken_provenance.json')
    args = p.parse_args(argv)
    start, end = parse_utc(args.start), parse_utc(args.end)
    output, manifest = Path(args.output), Path(args.manifest)
    if output == manifest or output.exists() or manifest.exists():
        raise SystemExit('Refusing to overwrite existing data or manifest')
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'BLOCKED', 'requested_start': args.start, 'requested_end': args.end}
    try:
        if end > parse_utc('2026-10-01T00:00:00Z'):
            raise ValueError('Official downloaded archives stop at 2026-09-30; freeze research end to 2026-10-01 UTC')
        rows, audit = fetch_archives(start, end)
        report.update(audit)
        if not rows:
            raise ValueError('The selected archives yielded no BTC/EUR bars')
        tmp = output.with_name(output.name + '.tmp')
        try:
            with tmp.open('w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerows(rows)
            tmp.replace(output)
        finally:
            tmp.unlink(missing_ok=True)
        report['kraken_csv_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
        report['status'] = 'DOWNLOADED_AND_VALIDATED_SOURCE_FORMAT'
        report['note'] = 'Kraken source only. Coinbase cross-check and holdout gate are separate.'
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        manifest.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'manifest': str(manifest),
                      'observed_bars': report.get('observed_bars'), 'error': report.get('error')}, indent=2))
    return 0 if report['status'] == 'DOWNLOADED_AND_VALIDATED_SOURCE_FORMAT' else 2


if __name__ == '__main__':
    raise SystemExit(run_cli())
