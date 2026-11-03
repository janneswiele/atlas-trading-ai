"""Recover incomplete Coinbase 1h data using verified Coinbase 15m candles.

Research only. Never writes an account file or authorizes a strategy.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import atlas_research as base

QUARTER = 900


def parse_quarter_rows(payload, start, stop):
    """Read only genuine 15m candles. Reject incomplete or invalid data."""
    if not isinstance(payload, list):
        raise ValueError("Unexpected Coinbase 15-minute response")
    found = {}
    for item in payload:
        if not isinstance(item, list) or len(item) != 6:
            raise ValueError("Invalid Coinbase 15-minute candle")
        ts, low, high, op, close, volume = item
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts) or int(ts) != ts:
            raise ValueError("Invalid 15-minute timestamp")
        ts = int(ts)
        if not start <= ts < stop:
            continue
        if ts % QUARTER:
            raise ValueError("Misaligned 15-minute timestamp")
        try:
            low, high, op, close, volume = map(float, (low, high, op, close, volume))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid 15-minute OHLCV data") from exc
        if (not all(map(math.isfinite, (low, high, op, close, volume))) or
            min(low, op, close) <= 0 or volume < 0 or
            high < max(low, op, close) or low > min(op, close)):
            raise ValueError("Impossible 15-minute OHLCV")
        value = (ts, op, high, low, close, volume)
        if ts in found and found[ts] != value:
            raise ValueError("Conflicting 15-minute candles")
        found[ts] = value
    return found


def fetch_quarters(start, stop, request_fn=urlopen, sleep_fn=time.sleep):
    """Request at most four quarter-hour candles; retry only transient errors."""
    if stop-start != base.HOUR or start % base.HOUR:
        raise ValueError("15-minute recovery accepts one aligned hour only")
    url = base.ENDPOINT + "?" + urlencode({
        "start": base._iso(start), "end": base._iso(stop), "granularity": QUARTER
    })
    req = Request(url, headers={"User-Agent":"AtlasResearchRecovery/0.4.1", "Accept":"application/json"})
    for attempt in range(3):
        try:
            with request_fn(req, timeout=25) as response:
                return parse_quarter_rows(json.load(response), start, stop)
        except HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt == 2:
                raise RuntimeError(f"Coinbase 15m recovery HTTP {exc.code}") from exc
        except (TimeoutError, URLError) as exc:
            if attempt == 2:
                raise RuntimeError("Coinbase 15m recovery network failure") from exc
        sleep_fn(1.5*(attempt+1))
    raise RuntimeError("Unreachable retry state")


def aggregate_hour(start, quarters):
    needed = [start + i*QUARTER for i in range(4)]
    if sorted(quarters) != needed:
        raise ValueError(f"Missing genuine Coinbase 15m candles at {base._iso(start)}; cannot reconstruct hour")
    q = [quarters[t] for t in needed]
    return (start, q[0][1], max(x[2] for x in q), min(x[3] for x in q), q[-1][4], sum(x[5] for x in q))


def recover_window(start, stop, hourly_fn=None, quarter_fn=None):
    """Backfill only missing hours from smaller genuine candles, never synthetic prices."""
    hourly_fn = hourly_fn or base._fetch_window
    quarter_fn = quarter_fn or fetch_quarters
    if start % base.HOUR or stop % base.HOUR or stop <= start:
        raise ValueError("Bad hourly request window")
    seen = {}
    for row in hourly_fn(start, stop):
        ts = row[0]
        if ts % base.HOUR or not start <= ts < stop:
            raise ValueError("Invalid hourly response timestamp")
        if ts in seen and seen[ts] != row:
            raise ValueError("Conflicting hourly candles")
        seen[ts] = row
    missing = [t for t in range(start, stop, base.HOUR) if t not in seen]
    for ts in missing:
        retry = hourly_fn(ts, ts+base.HOUR)
        retry = [row for row in retry if row[0] == ts]
        if len(retry) > 1 and any(row != retry[0] for row in retry):
            raise ValueError("Conflicting hourly retry candles")
        if retry:
            recovered = retry[0]
            source = "1h retry"
        else:
            recovered = aggregate_hour(ts, quarter_fn(ts, ts+base.HOUR))
            source = "4 genuine 15m candles"
        seen[ts] = recovered
        print(f"Recovered missing hour {base._iso(ts)} using {source}", flush=True)
    return [seen[t] for t in range(start, stop, base.HOUR)]


def main():
    parser = argparse.ArgumentParser(description="Historical BTC/EUR research with verified missing-hour recovery")
    parser.add_argument("--days", type=int, default=240)
    parser.add_argument("--output", default="atlas-research-output")
    args = parser.parse_args()
    report, count = base.research_to_directory(Path(args.output), days=args.days, fetch_fn=recover_window)
    print(f"Research complete: {count} four-hour bars; candidate: {report.get('selected') or 'none'}")
    print("Research artifact only; no account or trading strategy modified.")

if __name__ == "__main__":
    main()
