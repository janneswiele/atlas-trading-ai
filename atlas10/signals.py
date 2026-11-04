"""Deterministic, causal signals: signals[t] use no data after close[t]."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import pandas as pd
import numpy as np

@dataclass(frozen=True)
class Candidate:
    family: str
    fast: int = 20
    slow: int = 50
    atr_period: int = 14
    atr_multiplier: float = 2.5
    vol_limit: float = 0.0

    def __post_init__(self):
        if self.family not in ('sma', 'ema', 'momentum', 'donchian', 'atr_breakout'):
            raise ValueError('Unregistered strategy')
        if not 3 <= self.fast < self.slow <= 180:
            raise ValueError('Invalid causal signal window')
        if not 5 <= self.atr_period <= 40 or not 0.5 <= self.atr_multiplier <= 5:
            raise ValueError('Invalid ATR policy')
        if self.vol_limit not in (0.0, 0.015, 0.025, 0.045):
            raise ValueError('Volatility filter must be a predefined research level')

    @property
    def label(self):
        return f'{self.family}-{self.fast}-{self.slow}-atr{self.atr_period}x{self.atr_multiplier:g}-vol{self.vol_limit:g}'

    @property
    def identifier(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


def candidates() -> tuple[Candidate, ...]:
    """Small, fixed grid (not an unconstrained brute-force profit optimiser)."""
    grid = []
    for family in ('sma', 'ema', 'momentum', 'donchian', 'atr_breakout'):
        for fast, slow in ((10, 40), (20, 60), (30, 90)):
            for vol in (0.0, 0.025):
                grid.append(Candidate(family, fast, slow, vol_limit=vol))
    return tuple(grid)


def signals(df: pd.DataFrame, spec: Candidate) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate on an *entire prefix*. Execution is at NEXT bar's open.

    ATR measures historical volatility and is an additional exit for all
    candidate families. No future shifts or price interpolation are used.
    """
    close = df.close.astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([df.high-df.low, (df.high-prev_close).abs(), (df.low-prev_close).abs()], axis=1).max(axis=1)
    atr = tr.rolling(spec.atr_period, min_periods=spec.atr_period).mean()
    if spec.family in ('sma', 'ema'):
        if spec.family == 'sma':
            fast = close.rolling(spec.fast, min_periods=spec.fast).mean()
            slow = close.rolling(spec.slow, min_periods=spec.slow).mean()
        else:
            fast = close.ewm(span=spec.fast, adjust=False, min_periods=spec.fast).mean()
            slow = close.ewm(span=spec.slow, adjust=False, min_periods=spec.slow).mean()
        active = (fast > slow) & fast.notna() & slow.notna()
        exit_signal = (fast < slow) & fast.notna() & slow.notna()
    elif spec.family == 'momentum':
        fast = close.pct_change(spec.fast)
        slow = close.pct_change(spec.slow)
        active = (fast > 0) & (slow > 0) & slow.notna()
        exit_signal = (fast <= 0) & fast.notna()
    elif spec.family in ('donchian', 'atr_breakout'):
        prior_max = df.high.rolling(spec.slow, min_periods=spec.slow).max().shift(1)
        active = (close > prior_max) & prior_max.notna()
        exit_signal = (close < df.low.rolling(spec.fast, min_periods=spec.fast).min().shift(1))
    # Rising-edge only for entries to limit false repeated reentry signals.
    vol = close.pct_change().rolling(20, min_periods=20).std(ddof=0)
    if spec.vol_limit > 0:
        active = active & (vol < spec.vol_limit) & vol.notna()
    active = active.fillna(False)
    enter = active & (~active.shift(1, fill_value=False))
    # Trailing ATR channel is used only for exit signals from PREVIOUS close.
    atr_exit = (close < (df.high.rolling(spec.fast, min_periods=spec.fast).max() - spec.atr_multiplier * atr)) & atr.notna()
    leave = (exit_signal | atr_exit).fillna(False)
    return enter.to_numpy(dtype=bool), leave.to_numpy(dtype=bool)
