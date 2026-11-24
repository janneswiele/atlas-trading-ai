"""Frozen research safety policy and reproducible data provenance."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import pandas as pd

STEP_MS = 14_400_000
BARS_PER_YEAR = 365.25 * 6
SEALED_HOLDOUT_START_MS = 1771891200 * 1000  # 2026-02-24T00:00:00Z
POST_HOLDOUT_FORWARD_START_MS = 1790812800 * 1000  # 2026-10-01T00:00:00Z
HOLDOUT_BLOCK_START_MS = SEALED_HOLDOUT_START_MS  # compatibility for guardrail tests
FROZEN = {
    'max_allocation': 0.20, 'max_positions': 1, 'stop_loss': 0.02,
    'take_profit': 0.04, 'daily_loss_limit': 0.03, 'max_drawdown': 0.10,
}

@dataclass(frozen=True)
class Assumptions:
    initial_cash: float = 100.0
    fee: float = 0.006
    slippage: float = 0.0005
    allocation: float = FROZEN['max_allocation']

    def validate(self) -> None:
        numbers = (self.initial_cash, self.fee, self.slippage, self.allocation)
        if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in numbers):
            raise ValueError('Invalid non-finite assumptions')
        if self.initial_cash != 100.0 or not 0 <= self.fee <= .02 or not 0 <= self.slippage <= .01:
            raise ValueError('Frozen account/cost assumptions violated')
        if self.allocation != FROZEN['max_allocation']:
            raise ValueError('Frozen maximum allocation must not be raised or changed')


def sha_file(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def validate_bars(frame: pd.DataFrame, *, minimum: int = 2) -> pd.DataFrame:
    """Reject missing 4h closes, bad OHLC, invalid volumes, duplicate timestamps.

    Time is UTC milliseconds. No interpolation, sorting, or row repair.
    """
    required = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    if list(frame.columns) != required:
        raise ValueError('Expected timestamp,open,high,low,close,volume columns in that order')
    if len(frame) < minimum:
        raise ValueError('Not enough rows for research')
    try:
        n = frame.astype({x: 'float64' for x in required})
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Invalid numeric market data') from exc
    import numpy as np
    a = n.to_numpy(dtype=float)
    if not np.isfinite(a).all():
        raise ValueError('NaN/inf market data forbidden')
    t = n.timestamp.to_numpy()
    if not np.equal(t, np.floor(t)).all() or not np.equal(np.mod(t, STEP_MS), 0).all():
        raise ValueError('Timestamps must be aligned integer UTC milliseconds')
    if not np.equal(np.diff(t), STEP_MS).all():
        raise ValueError('Missing/duplicate/out-of-order four-hour candles')
    if not (n[['open','high','low','close']] > 0).all().all() or (n.volume < 0).any():
        raise ValueError('Non-positive price or negative volume')
    if (n.low > n[['open','close']].min(axis=1)).any() or (n.high < n[['open','close']].max(axis=1)).any():
        raise ValueError('Invalid OHLC extremes')
    if (n.high < n.low).any():
        raise ValueError('Invalid candle range')
    return n


def approved_csv(csv_path: Path, manifest_path: Path, *, min_bars=480) -> tuple[pd.DataFrame, dict]:
    """An explicit *research-only* SHA-bound manifest is mandatory.

    The sealed historical holdout and the newer v0.9 forward stream are not
    automatically research input. This loader accepts pre-approved training
    files, without retroactively authorising any reserved evaluation sample.
    """
    csv_path, manifest_path = Path(csv_path), Path(manifest_path)
    meta = json.loads(manifest_path.read_text(encoding='utf-8'))
    if meta.get('purpose') != 'RESEARCH_ONLY' or meta.get('status') != 'APPROVED':
        raise ValueError('Data is not explicitly approved for research')
    if meta.get('source_type') not in ('synthetic', 'observed'):
        raise ValueError('Data source must be declared')
    if meta.get('sha256') != sha_file(csv_path):
        raise ValueError('SHA256 research input mismatch')
    if not isinstance(meta.get('start_ms'), int) or not isinstance(meta.get('end_exclusive_ms'), int):
        raise ValueError('Missing integer research boundaries')
    if not meta.get('approval_id') or not isinstance(meta.get('approval_id'), str):
        raise ValueError('Missing research data approval identifier')
    if meta['source_type'] == 'observed':
        historical_training = meta['end_exclusive_ms'] <= SEALED_HOLDOUT_START_MS
        fresh_forward = (meta['start_ms'] >= POST_HOLDOUT_FORWARD_START_MS and
                         meta.get('forward_protocol_registration') == 'OWNER_APPROVED_FRESH_FORWARD_RESEARCH')
        if not (historical_training or fresh_forward):
            raise ValueError('Sealed historical holdout or unregistered post-holdout forward period forbidden')
    # Synthetic fixtures are explicitly NOT evidence of profitable real-world trading.
    df = pd.read_csv(csv_path)
    df = validate_bars(df, minimum=min_bars)
    if int(df.timestamp.iloc[0]) != meta['start_ms'] or int(df.timestamp.iloc[-1]) + STEP_MS != meta['end_exclusive_ms']:
        raise ValueError('Manifest date range mismatch')
    return df, meta
