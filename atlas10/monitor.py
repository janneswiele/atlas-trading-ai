"""Read-only, tamper-evident view into the frozen v0.9 research ledger.

Does not import live trading modules and has no write/delete or order methods.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

LEDGER_URL = 'https://raw.githubusercontent.com/janneswiele/atlas-trading-ai/atlas-v0.9-data/ledger.json'

def _digest(o: object) -> str:
    return sha256(json.dumps(o, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def verify_ledger(state: dict) -> dict:
    """Verifies seal and event-chain only; not source code hash attestation."""
    if not isinstance(state, dict) or state.get('version')!='0.9':
        raise ValueError('Unexpected research ledger schema')
    events=state.get('events')
    if not isinstance(events,list) or not events:
        raise ValueError('Missing ledger events')
    if state.get('seal') != _digest({k:v for k,v in state.items() if k!='seal'}):
        raise ValueError('Ledger seal mismatch')
    previous = '0'*64
    for i,event in enumerate(events):
        if event.get('id') != i or event.get('previous') != previous:
            raise ValueError('Ledger event order/hash chain mismatch')
        expected = _digest({k:v for k,v in event.items() if k!='hash'})
        if event.get('hash') != expected:
            raise ValueError('Ledger event content tampered with')
        previous = expected
    names=state.get('accounts')
    if not isinstance(names,dict) or len(names)!=4:
        raise ValueError('Unexpected virtual account count')
    accounts={}
    for name, account in names.items():
        if not isinstance(account,dict): raise ValueError('Malformed virtual account')
        cash,qty,equity = (account.get(x) for x in ('cash','quantity','equity'))
        if not all(isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x) and x>=0 for x in (cash,qty,equity)):
            raise ValueError('Invalid virtual account value')
        accounts[name]={'cash_eur':float(cash),'btc_quantity':float(qty),
                        'equity_eur':float(equity),'closed_trades':int(account.get('closed',0)),
                        'fees_eur':float(account.get('fees',0)),
                        'risk_halted':bool(account.get('halted',False))}
    last=events[-1]
    return {'integrity':'EVENT_CHAIN_AND_SEAL_PASS_NOT_SOURCE_ATTESTATION',
            'version':state['version'],'activation_utc':datetime.fromtimestamp(state['activation'],timezone.utc).isoformat(),
            'last_event':last['kind'],'last_event_utc':datetime.fromtimestamp(last['time'],timezone.utc).isoformat(),
            'failures':int(state.get('failures',0)), 'circuit':bool(state.get('circuit',False)),
            'last_bar_ms':state.get('last_bar'), 'events':len(events),'accounts':accounts,
            'mode':'SHADOW_RESEARCH_ONLY','real_trading_allowed':False}


def load_ledger(local: str | Path | None = None) -> dict:
    if local is not None:
        state=json.loads(Path(local).read_text(encoding='utf-8'))
    else:
        import requests
        result=requests.get(LEDGER_URL,timeout=(5,15),headers={'User-Agent':'Atlas-v1.0-Readonly-Dashboard'})
        result.raise_for_status()
        if len(result.content)>5_000_000:
            raise ValueError('Research ledger unexpectedly large')
        state=result.json()
    return state


def status(local: str | Path | None = None) -> dict:
    return verify_ledger(load_ledger(local))
