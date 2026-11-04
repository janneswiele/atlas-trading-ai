"""Deterministic forward accounting; callers supply genuinely observed quotes.

Decision and settlement are separate durable transactions. No historical fill
reconstruction is supported. All accounts are research-only and never approved.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path
import pandas as pd
import atlas_v06 as v06
import atlas_v084 as v084
from strategies import generate_signals

STEP = 14400
MODELS = tuple(v084.MODELS)
# Freeze after the historical sample, excluding its entire sealed holdout.
WARMUP_START = 1790812800  # 2026-10-01T00:00:00Z
WARMUP = 240
RISK = {k: v06.EXPECTED_RISK[k] for k in (
    'max_allocation', 'max_positions', 'stop_loss', 'take_profit',
    'daily_loss_limit', 'max_drawdown')}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def finite(x, positive=False):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or (positive and x == 0):
        raise ValueError('Invalid nonnegative finite number')
    return float(x)


def config_check(config, production):
    v06.verify_unchanged_config(production)
    if config['risk'] != RISK or any(type(config['risk'][k]) is not type(v) for k,v in RISK.items()) or config['warmup_start'] != WARMUP_START:
        raise ValueError('Risk rules or holdout boundary changed')
    if type(config['enabled']) is not bool or config['mode'] != 'SHADOW_RESEARCH_ONLY':
        raise ValueError('Invalid mode / kill switch')
    if not 0 <= finite(config['fee']) <= .02 or not 0 <= finite(config['slippage']) <= .01:
        raise ValueError('Implausible research costs')
    if finite(config['capital'], True) != 100:
        raise ValueError('Frozen initial capital changed')


def fingerprint(config):
    return digest({k: v for k, v in config.items() if k != 'enabled'})


def source_hash(root):
    files = ['strategies.py', 'atlas_v084.py', 'atlas_v06.py', 'atlas09/core.py', 'atlas09/market.py', 'atlas09/persist.py', 'atlas_v09.py']
    return digest({p: hashlib.sha256((Path(root)/p).read_bytes()).hexdigest() for p in files})


def emit(state, kind, time, **payload):
    finite(time, True)
    if state['events'] and time < state['events'][-1]['time']:
        raise ValueError('Clock moved backwards')
    event = dict(id=len(state['events']), previous=state['events'][-1]['hash'] if state['events'] else '0'*64,
                 kind=kind, time=time, payload=payload)
    event['hash'] = digest(event)
    state['events'].append(event)
    state['seal'] = digest({k: v for k, v in state.items() if k != 'seal'})


def new_state(config, now, code_hash):
    if not config['enabled'] or now < WARMUP_START:
        raise ValueError('Explicit activation required after historical sample')
    state = dict(version='0.9', activation=now, config=fingerprint(config), code=code_hash,
                 protocol=copy.deepcopy(config), market=dict(pair='BTC/EUR', primary='Coinbase', control='Kraken', timeframe='4h UTC'),
                 last_bar=None, seen={}, pending=None, failures=0, circuit=False, benchmark=None,
                 accounts={m: dict(cash=config['capital'], quantity=0., entry=0., basis=0.,
                    fees=0., slippage_cost=0., realized=0., closed=0, wins=0, gross_profit=0., gross_loss=0.,
                    peak=config['capital'], equity=config['capital'], drawdown=0.,
                    day=None, day_equity=config['capital'], halted=False) for m in MODELS}, events=[])
    emit(state, 'ACTIVATED', now, mode='SHADOW_RESEARCH_ONLY', holdout_evaluated=False)
    return state


def validate_state(state, config, code_hash):
    if state.get('seal') != digest({k: v for k, v in state.items() if k != 'seal'}):
        raise ValueError('State checksum mismatch; no reset permitted')
    if state['config'] != fingerprint(config) or state['code'] != code_hash:
        raise ValueError('Study configuration/code changed; start a separate preregistered study')
    previous = '0'*64
    for i, event in enumerate(state['events']):
        if event['id'] != i or event['previous'] != previous or event['hash'] != digest({k:v for k,v in event.items() if k!='hash'}):
            raise ValueError('Broken event chain')
        previous = event['hash']
    if set(state['accounts']) != set(MODELS):
        raise ValueError('Unexpected accounts')
    for a in state['accounts'].values():
        for k in ('cash','quantity','entry','basis','fees','equity','peak'):
            finite(a[k])
        if (a['quantity']==0) != (a['basis']==0) or (a['quantity']==0) != (a['entry']==0):
            raise ValueError('Inconsistent position')


def validated_frame(frame, now):
    v06.validate_4h_rows(frame, now=int(now))
    if frame.empty or (frame.timestamp.diff().dropna() != STEP*1000).any():
        raise ValueError('Missing candles; never interpolate')
    if frame.timestamp.min() < WARMUP_START*1000:
        raise ValueError('Historical holdout data forbidden')
    close = int(frame.timestamp.iloc[-1]//1000) + STEP
    if now-close < 0 or now-close > 3600:
        raise ValueError('Stale or open candle / delayed execution')
    return close


def prepare(state, frame, config, now):
    """Returns a copy. Persist this before requesting a later market quote."""
    if not config['enabled'] or state['circuit']:
        raise ValueError('Kill switch / circuit breaker')
    close = validated_frame(frame, now)
    s = copy.deepcopy(state)
    for row in frame.itertuples(index=False, name=None):
        key = str(int(row[0]))
        hashed = digest([float(v) for v in row])
        if key in s['seen'] and s['seen'][key] != hashed:
            raise ValueError('Previously observed candle revised')
        s['seen'][key] = hashed
    if s['pending'] is not None:
        emit(s, 'PENDING_RETRY', now, decision_at=s['pending']['at'])
        return s  # never replace an existing decision
    if s['last_bar'] is not None and close <= s['last_bar']:
        s['failures']=0
        emit(s, 'DUPLICATE', now, candle_close=close)
        return s
    previous_close=s['last_bar']
    s['last_bar'] = close
    if previous_close is not None and close-previous_close > STEP:
        emit(s, 'MISSED_CANDLES_NO_BACKFILL', now, missed=(close-previous_close)//STEP-1)
    if close <= s['activation'] or len(frame) < WARMUP:
        s['failures']=0
        emit(s, 'WARMUP', now, candle_close=close, bars=len(frame), required=WARMUP)
        return s
    decisions = {}
    for model in MODELS:
        if model in v084.CANDIDATES:
            enter, leave = v084.candidate_signals(frame, model)
        else:
            enter, leave, _, _ = generate_signals(frame, model)
            enter, leave = enter.to_numpy(), leave.to_numpy()
        decisions[model] = dict(enter=bool(enter[-1]), exit=bool(leave[-1]))
    s['pending'] = dict(at=now, close=close, expires=min(close+3600, now+300), signals=decisions, bars=len(frame),
                        frame_start=int(frame.timestamp.iloc[0]), frame_hash=digest(frame.astype(float).values.tolist()))
    emit(s, 'DECISION', now, **s['pending'])
    return s


def fill(cash_or_quantity, price, side, fee, slippage):
    """Buy budget INCLUDES fees; sell uses actual bid; slippage is additional."""
    for x in (cash_or_quantity, price): finite(x, True)
    finite(fee); finite(slippage)
    if fee > .02 or slippage > .01 or side not in ('buy','sell'):
        raise ValueError('Invalid fill')
    execution = price*(1+slippage if side=='buy' else 1-slippage)
    quantity = cash_or_quantity/(execution*(1+fee)) if side=='buy' else cash_or_quantity
    notional = quantity*execution
    return dict(price=execution, quantity=quantity, fee=notional*fee,
                slippage=quantity*abs(execution-price),
                cash=notional*(1+fee if side=='buy' else 1-fee))


def settle(state, quote, config, now):
    s = copy.deepcopy(state)
    if not config['enabled'] or s['circuit']: raise ValueError('Trading disabled')
    p = s['pending']
    if p is None: return s
    if now > p['expires']:
        s['pending'] = None
        emit(s, 'EXPIRED_NO_FILL', now, decision_at=p['at'])
        return s
    bid, ask = finite(quote['bid'], True), finite(quote['ask'], True)
    observed, traded = finite(quote['observed_at'], True), finite(quote['exchange_time'], True)
    if not p['at'] <= traded <= observed <= now or now-observed > 30 or ask < bid or ask/bid-1 > .01:
        raise ValueError('Quote predates decision, is stale or invalid')
    fee, slip = config['fee'], config['slippage']
    day = int(now//86400)
    for model, a in s['accounts'].items():
        equity = a['cash'] + a['quantity']*bid*(1-slip)*(1-fee)
        if a['day'] != day:
            a['day'], a['day_equity'] = day, a['equity']
        a['peak'] = max(a['peak'], equity)
        dd = 1-equity/a['peak']
        day_loss = 1-equity/a['day_equity']
        if dd >= RISK['max_drawdown'] or day_loss >= RISK['daily_loss_limit']:
            a['halted'] = True  # persistent; no silent daily restart
        signal = p['signals'][model]
        reason = 'HOLD'
        if a['quantity']:
            if a['halted']: reason = 'RISK_HALT'
            elif bid <= a['entry']*(1-RISK['stop_loss']): reason = 'STOP_LOSS'
            elif bid >= a['entry']*(1+RISK['take_profit']): reason = 'TAKE_PROFIT'
            elif signal['exit']: reason = 'SIGNAL_EXIT'
            if reason != 'HOLD':
                trade = fill(a['quantity'], bid, 'sell', fee, slip)
                pnl = trade['cash']-a['basis']
                a['cash'] += trade['cash']; a['realized'] += pnl
                a['closed'] += 1; a['wins'] += int(pnl>0)
                a['gross_profit'] += max(0,pnl); a['gross_loss'] += max(0,-pnl)
                a['fees'] += trade['fee']; a['slippage_cost'] += trade['slippage']
                a['quantity']=a['entry']=a['basis']=0.
                emit(s, 'SELL', now, model=model, reason=reason, pnl=pnl, decision_at=p['at'], quote=quote, **trade)
        elif signal['enter'] and not a['halted']:
            trade = fill(a['cash']*RISK['max_allocation'], ask, 'buy', fee, slip)
            a['cash'] -= trade['cash']; a['basis']=trade['cash']
            a['quantity']=trade['quantity']; a['entry']=trade['price']
            a['fees'] += trade['fee']; a['slippage_cost'] += trade['slippage']
            reason='SIGNAL_ENTRY'
            emit(s, 'BUY', now, model=model, reason=reason, decision_at=p['at'], quote=quote, **trade)
        a['equity']=a['cash']+a['quantity']*bid*(1-slip)*(1-fee)
        a['peak']=max(a['peak'], a['equity'])
        a['drawdown']=max(a['drawdown'], 1-a['equity']/a['peak'])
        a['last_decision']=reason
    if s['benchmark'] is None:
        trade=fill(config['capital']*.2, ask, 'buy', fee, slip)
        s['benchmark']=dict(cash=config['capital']*.8, quantity=trade['quantity'], started=now)
    s['benchmark']['equity']=s['benchmark']['cash']+s['benchmark']['quantity']*bid*(1-slip)*(1-fee)
    s['pending']=None; s['failures']=0
    emit(s, 'VALUATION', now, accounts=copy.deepcopy(s['accounts']), benchmark=copy.deepcopy(s['benchmark']),
         note='Passive 20% initial allocation is a contextual benchmark without strategy stops')
    return s


def failed(state, now, error):
    s=copy.deepcopy(state); s['failures']+=1; s['circuit']=s['failures']>=3
    emit(s, 'ERROR', now, error=str(error)[:500], circuit=s['circuit'])
    return s
