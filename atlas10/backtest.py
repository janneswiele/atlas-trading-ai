"""Next-open-only, long-only, fee-aware, offline virtual execution.

Never submits actual orders. All decisions are based on completed prior candles.
Never uses candle high/low as if an intrabar stop could be filled retroactively.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
from .policy import Assumptions, BARS_PER_YEAR, FROZEN, validate_bars
from .signals import Candidate, signals

@dataclass
class Simulation:
    metrics: dict
    curve: list[dict]
    orders: list[dict]


def _dd(curve: list[float]) -> float:
    peak = max(curve[0], 1e-12)
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return float(worst)


def simulate(bars: pd.DataFrame, spec: Candidate, start: int, end: int,
             cfg: Assumptions = Assumptions()) -> Simulation:
    """Simulate indices [start,end), training context allowed strictly before start.

    No cash/position carries across independent validation folds. This is a
    *candidate-research simulation*, separate from the immutable v0.9 ledger.
    """
    cfg.validate()
    data = validate_bars(bars, minimum=80)
    if not isinstance(start, int) or not isinstance(end, int) or start < max(spec.slow + 25, 80) or end > len(data) or end - start < 5:
        raise ValueError('Invalid research window / incomplete indicator warmup')
    prefix = data.iloc[:end]
    entry, exit_ = signals(prefix, spec)
    cash, qty, basis, entry_price = float(cfg.initial_cash), 0.0, 0.0, 0.0
    entry_time = None
    halted = False
    fees, realized = 0., 0.
    orders, curve = [], []
    prev_day = None
    peak = cfg.initial_cash
    day_start = cfg.initial_cash
    bm_qty = cfg.initial_cash * cfg.allocation / (
        float(data.open.iloc[start]) * (1 + cfg.slippage) * (1 + cfg.fee))
    bm_cash = cfg.initial_cash * (1 - cfg.allocation)
    for i in range(start, end):
        bar = data.iloc[i]
        t, op, cl = int(bar.timestamp), float(bar.open), float(bar.close)
        sell_bid = op * (1 - cfg.slippage)
        equity_at_open = cash + qty * sell_bid * (1 - cfg.fee)
        day = t // 86_400_000
        if day != prev_day:
            day_start, prev_day = equity_at_open, day
        peak = max(peak, equity_at_open)
        dd = 1 - equity_at_open / peak
        day_loss = 1 - equity_at_open / max(day_start, 1e-12)
        if dd >= FROZEN['max_drawdown'] or day_loss >= FROZEN['daily_loss_limit']:
            halted = True
        previous_entry = bool(entry[i-1])
        previous_exit = bool(exit_[i-1])
        reason = None
        if qty:
            if halted: reason = 'RISK_HALT'
            elif op <= entry_price * (1-FROZEN['stop_loss']): reason = 'STOP_AT_NEXT_OPEN'
            elif op >= entry_price * (1+FROZEN['take_profit']): reason = 'TAKE_AT_NEXT_OPEN'
            elif previous_exit: reason = 'PRIOR_CLOSE_EXIT'
            if reason:
                proceeds = qty * sell_bid * (1-cfg.fee)
                fee = qty * sell_bid * cfg.fee
                cash += proceeds
                pnl = proceeds - basis
                realized += pnl
                fees += fee
                orders.append({'timestamp':t,'side':'SELL','reason':reason,'quantity':qty,
                               'execution_price':sell_bid,'fee':fee,'net_realized_pnl':pnl,
                               'entry_time':entry_time})
                qty, basis, entry_price, entry_time = 0., 0., 0., None
        elif not halted and previous_entry and cash > 0:
            allocation = min(cfg.initial_cash * cfg.allocation, cash * cfg.allocation)
            if allocation >= .01:
                executed = op * (1 + cfg.slippage)
                qty = allocation / (executed * (1+cfg.fee))
                fee = qty * executed * cfg.fee
                cash -= allocation
                basis = allocation
                entry_price, entry_time = executed, t
                fees += fee
                orders.append({'timestamp':t,'side':'BUY','reason':'PRIOR_CLOSE_ENTRY',
                               'quantity':qty,'execution_price':executed,'fee':fee})
        equity = cash + qty * cl * (1-cfg.slippage) * (1-cfg.fee)
        benchmark = bm_cash + bm_qty * cl * (1-cfg.slippage) * (1-cfg.fee)
        if equity < -1e-8 or not math.isfinite(equity):
            raise ValueError('Non-physical virtual equity')
        peak = max(peak, equity)
        curve.append({'timestamp':t, 'equity':equity, 'benchmark':benchmark,
                      'cash':cash,'quantity':qty,'exposure':qty*cl/max(equity,1e-12)})
    all_equity = np.array([cfg.initial_cash]+[x['equity'] for x in curve], dtype=float)
    rets = np.diff(all_equity) / all_equity[:-1]
    vol = float(rets.std(ddof=1) * math.sqrt(BARS_PER_YEAR)) if len(rets)>1 else 0.
    sharpe = float(rets.mean()/rets.std(ddof=1)*math.sqrt(BARS_PER_YEAR)) if len(rets)>1 and rets.std(ddof=1)>1e-12 else None
    closed = [o for o in orders if o['side']=='SELL']
    wins = [o for o in closed if o['net_realized_pnl']>0]
    losses = -sum(o['net_realized_pnl'] for o in closed if o['net_realized_pnl']<0)
    profits = sum(o['net_realized_pnl'] for o in wins)
    metrics = {'strategy':spec.label, 'candidate_id':spec.identifier, 'start_ms':int(data.timestamp.iloc[start]),
               'end_exclusive_ms':int(data.timestamp.iloc[end-1])+14_400_000,
               'bars':end-start, 'return_net':float(all_equity[-1]/cfg.initial_cash-1),
               'benchmark_return_net':float(curve[-1]['benchmark']/cfg.initial_cash-1),
               'alpha_net':float((all_equity[-1]-curve[-1]['benchmark'])/cfg.initial_cash),
               'max_drawdown':_dd(all_equity.tolist()), 'annual_volatility':vol, 'sharpe':sharpe,
               'fees_paid':float(fees), 'realized_pnl':float(realized),
               'closed_trades':len(closed), 'win_rate':len(wins)/len(closed) if closed else None,
               'profit_factor':profits/losses if losses>0 else None,
               'exposure_mean':float(np.mean([x['exposure'] for x in curve])),
               'open_position':bool(qty), 'risk_halted':halted, 'virtual_only':True}
    return Simulation(metrics=metrics, curve=curve, orders=orders)
