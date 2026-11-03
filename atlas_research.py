"""Atlas v0.4.1: read-only historical BTC/EUR research runner.

Uses public Coinbase Exchange BTC-EUR 1h candles because that API exposes
paged historical ranges and no public Kraken 4h API can return >720 candles.
The saved candidate report is NOT live trading authorization. Coinbase fills
are not interchangeable with Kraken fills or a validated live strategy.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

HOUR = 3600
STEP = 4 * HOUR
SOURCE = 'Coinbase Exchange public BTC-EUR 1h candles'
ENDPOINT = 'https://api.exchange.coinbase.com/products/BTC-EUR/candles'
COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_hourly_rows(payload, start: int, stop: int):
    """Return only hour buckets in [start, stop); fail on malformed data."""
    if not isinstance(payload, list):
        raise ValueError('Coinbase API payload is not an array')
    rows = []
    for value in payload:
        if not isinstance(value, list) or len(value) != 6:
            raise ValueError('Unexpected Coinbase candle row')
        ts, low, high, op, close, volume = value
        if isinstance(ts, bool) or int(ts) != ts:
            raise ValueError('Invalid candle timestamp')
        ts = int(ts)
        if ts < start or ts >= stop:
            continue  # Coinbase may include boundary buckets; do not double-count
        if ts % HOUR:
            raise ValueError('Misaligned 1h candle')
        low, high, op, close, volume = map(float, (low, high, op, close, volume))
        if any(not math.isfinite(n) for n in (low, high, op, close, volume)):
            raise ValueError('Non-finite candle value')
        if min(low, op, close) <= 0 or high < max(low, op, close) or volume < 0:
            raise ValueError('Impossible OHLCV candle')
        rows.append((ts, op, high, low, close, volume))
    return rows


def _fetch_window(start: int, stop: int, request_fn=urlopen, sleep_fn=time.sleep):
    url = ENDPOINT + '?' + urlencode({'start': _iso(start), 'end': _iso(stop), 'granularity': HOUR})
    req = Request(url, headers={'User-Agent': 'AtlasResearch/0.4.1', 'Accept': 'application/json'})
    for attempt in range(3):
        try:
            with request_fn(req, timeout=25) as response:
                return parse_hourly_rows(json.load(response), start, stop)
        except HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f'Coinbase returned HTTP {e.code} - no report created') from e
        except (TimeoutError, URLError) as e:
            if attempt == 2:
                raise RuntimeError(f'Coinbase connection failure: {type(e).__name__}') from e
        sleep_fn(1.5 * (attempt + 1))
    raise RuntimeError('Unreachable retry state')


def fetch_history(now: int, days: int, fetch_fn=_fetch_window, sleep_fn=time.sleep):
    if isinstance(days, bool) or not isinstance(days, int) or not 168 <= days <= 365:
        raise ValueError('History must be 168-365 whole days')
    # Align both ends to complete UTC four-hour sessions.
    right = (int(now) // STEP) * STEP
    left = right - days * 86400
    if left % STEP:
        raise ValueError('Unaligned historical window')
    seen = {}
    cursor = left
    while cursor < right:
        stop = min(cursor + 240 * HOUR, right)  # safely below Coinbase 300-candle limit
        batch = fetch_fn(cursor, stop)
        for row in batch:
            ts = row[0]
            if not cursor <= ts < stop or ts % HOUR:
                raise ValueError('Provider returned out-of-window candle')
            if ts in seen and seen[ts] != row:
                raise ValueError('Conflicting historical candles')
            seen[ts] = row
        cursor = stop
        if cursor < right:
            sleep_fn(0.3)
    required = (right - left) // HOUR
    if len(seen) != required:
        missing = next((t for t in range(left, right, HOUR) if t not in seen), None)
        raise ValueError(f'Historical data has gaps: {len(seen)}/{required} hours, first missing {_iso(missing) if missing is not None else "unknown"}')
    hours = pd.DataFrame([seen[t] for t in range(left, right, HOUR)], columns=COLUMNS)
    # Precisely four complete 1h bars per 4h candle, no interpolation or synthetic prices.
    result = []
    for base in range(left, right, STEP):
        part = hours[(hours.timestamp >= base) & (hours.timestamp < base + STEP)]
        if part.timestamp.tolist() != [base + i * HOUR for i in range(4)]:
            raise ValueError('Incomplete four-hour aggregation')
        result.append((base * 1000, float(part.open.iloc[0]), float(part.high.max()),
                       float(part.low.min()), float(part.close.iloc[-1]), float(part.volume.sum())))
    return pd.DataFrame(result, columns=COLUMNS)


def research_to_directory(directory: Path, now: int | None = None, days: int = 240, fetch_fn=_fetch_window,
                          sleep_fn=time.sleep, build_fn=None):
    # Imports kept inside the research path: collecting data never touches paper_state.json.
    from research import build_report
    from paper import validate_candles
    now = int(time.time() if now is None else now)
    df = fetch_history(now, days, fetch_fn=fetch_fn, sleep_fn=sleep_fn)
    validate_candles(df, now)
    cfg = json.loads(Path(__file__).with_name('paper_config.json').read_text())
    report = (build_fn or build_report)(df, now=now, fee=cfg['fee_rate'], slip=cfg['slippage'])
    report.update(source=SOURCE, source_product='BTC-EUR', source_timeframe='1h aggregated to 4h',
                  paper_execution_exchange='Kraken', manual_review_required=True,
                  live_trading_approved=False,
                  warning='Research candles from Coinbase; live paper engine quotes Kraken. Cross-exchange differences and historic API availability require independent review. This is NOT strategy_report.json.')
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    csv = folder / 'coinbase_btc_eur_4h.csv'
    candidate = folder / 'strategy_report_CANDIDATE.json'  # deliberate non-production filename
    summary = folder / 'READ_ME_FIRST.txt'
    # Output files are a research artifact, not committed to the paper ledger.
    df.to_csv(csv, index=False)
    candidate.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    rejected = [r for r in report['candidates'] if r['reasons']]
    summary.write_text(
        f'ATLAS RESEARCH (NOT FOR LIVE/PAPER RELEASE)\nData: {SOURCE}\n'
        f'4h bars: {len(df)}\nStart (UTC): {_iso(int(df.timestamp.iloc[0]/1000))}\n'
        f'End candle start (UTC): {_iso(int(df.timestamp.iloc[-1]/1000))}\n'
        f'Candidate selected in validation: {report.get("selected") or "NONE"}\n'
        f'Rejected candidates: {len(rejected)} of {len(report["candidates"])}\n'
        f'IMPORTANT: Do not rename strategy_report_CANDIDATE.json to strategy_report.json or upload it to main.\n'
        f'Compare Coinbase source with Kraken and review holdout/protocol before any approval.\n'
    )
    return report, len(df)


def main():
    parser = argparse.ArgumentParser(description='Read-only BTC/EUR 4h historical research; NEVER authorizes trading')
    parser.add_argument('--days', type=int, default=240)
    parser.add_argument('--output', default='atlas-research-output')
    args = parser.parse_args()
    report, count = research_to_directory(Path(args.output), days=args.days)
    print(f'Research complete: {count} bars; validation candidate: {report.get("selected") or "none"}')
    print(f'Files in {args.output}. No changes made to trading account or strategy authorization.')

if __name__ == '__main__':
    main()
