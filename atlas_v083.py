"""Atlas v0.8.3: reproducible exit/entry attribution on sealed-holdout research.

An audit, NOT a new trading strategy. No orders, parameter search, release or
paper-state writes. Inputs must be verified v0.8.1 pre-holdout artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

import atlas_v05 as v05
import atlas_v06 as v06
import atlas_v08 as v08
import atlas_v082 as v082

PROJECT = Path(__file__).resolve().parent
PRIMARY_DAYS = 90
COST_FACTOR = 1
ALLOCATION = .2
EXIT_PRIORITY = ('drawdown_halt', 'daily_loss', 'stop_loss', 'take_profit', 'signal_exit')


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replay_attribution(segment: pd.DataFrame, lo: int, hi: int, model: str,
                       cfg: dict, fee: float, slip: float) -> tuple[dict, list[dict], pd.DataFrame, list[dict]]:
    """Independently replay decisions, then require exact agreement with v0.8.

    Only information available at each 4h *open* is consulted for a decision:
    the preceding bar's close signals, the current open, and previous risk
    state. Intrabar stop/take levels are NOT simulated as executable prices.
    """
    v06.verify_unchanged_config(cfg)
    if not (200 <= lo < hi <= len(segment)) or model not in v08.MODELS:
        raise ValueError('Invalid replay interval/model')
    if not (0 <= fee < .03 and 0 <= slip < .03):
        raise ValueError('Invalid research cost')
    data = segment.iloc[:hi].reset_index(drop=True)
    v06.validate_4h_rows(data)
    if (data.timestamp.diff().dropna() != v08.STEP * 1000).any():
        raise ValueError('Replay cannot traverse gaps')

    buy, sell = v08.signals(data, model)
    baseline, expected_curve, expected_trades, _ = v08.simulate(
        segment, lo, hi, model, cfg, ALLOCATION, fee, slip)
    cash, qty, entry_price, paid_cost, peak = 100.0, 0.0, 0.0, 0.0, 100.0
    halted, day, day_equity = False, None, 100.0
    entry_ts = None
    events: list[dict] = []
    positions = []
    tallies = Counter()
    simulated_curve = []
    for i in range(lo, hi):
        row = data.iloc[i]
        ts = int(row.timestamp)
        open_price = float(row.open)
        value_open = cash + qty * open_price
        peak = max(peak, value_open)
        utc_day = ts // 86400000
        if utc_day != day:
            day = utc_day
            day_equity = value_open
        daily_loss = value_open <= day_equity * (1 - cfg['daily_loss_limit'])
        halted = halted or value_open <= peak * (1 - cfg['max_drawdown'])
        prior_buy = i > lo and bool(buy[i-1])
        prior_sell = bool(sell[i-1])
        if prior_buy:
            tallies['closed_candle_buy_signals'] += 1
        if prior_sell:
            tallies['closed_candle_sell_signals'] += 1
        if not qty:
            tallies['flat_bars_at_open'] += 1
            if not prior_buy:
                tallies['flat_no_entry_signal_bars'] += 1
            elif halted or daily_loss:
                tallies['entry_blocked_by_risk'] += 1
            elif cash < 10:
                tallies['entry_blocked_by_cash'] += 1
            else:
                tallies['entry_candidates'] += 1
        elif prior_buy:
            tallies['buy_signals_while_in_position'] += 1

        triggers = {
            'signal_exit': bool(prior_sell),
            'stop_loss': bool(qty and open_price <= entry_price*(1-cfg['stop_loss'])),
            'take_profit': bool(qty and open_price >= entry_price*(1+cfg['take_profit'])),
            'drawdown_halt': bool(qty and halted),
            'daily_loss': bool(qty and daily_loss),
        }
        if qty and any(triggers.values()):
            reason = next(reason for reason in EXIT_PRIORITY if triggers[reason])
            gross = qty * open_price * (1-slip)
            proceeds = gross * (1-fee)
            pnl = proceeds - paid_cost
            events.append({'strategy': model, 'entry_time': entry_ts,
                           'exit_time': ts, 'exit_reason_primary': reason,
                           'all_triggers': '|'.join(k for k in EXIT_PRIORITY if triggers[k]),
                           'hold_bars': (ts-entry_ts)//(v08.STEP*1000),
                           'net_pnl_eur': pnl, 'exit_open_eur': open_price,
                           'entry_executed_eur': entry_price,
                           'note': '4h sampled OPEN; not an executable intrabar stop price'})
            tallies['exit_'+reason] += 1
            tallies['closed_trades'] += 1
            cash += proceeds
            qty = 0.0
        elif not qty and prior_buy and not halted and not daily_loss and cash >= 10:
            paid_cost = cash * ALLOCATION
            entry_price = open_price * (1+slip)
            qty = paid_cost/(entry_price*(1+fee))
            cash -= paid_cost
            entry_ts = ts
            tallies['entries'] += 1

        mark = cash + qty*float(row.close)*(1-slip)*(1-fee)
        simulated_curve.append(mark)
        positions.append({'timestamp': ts, 'position_open_after_decision': int(qty>0),
                          'equity_eur_after_mark': mark,
                          'risk_halted': bool(halted),
                          'daily_loss_at_open': bool(daily_loss)})
        if qty:
            tallies['bars_in_position'] += 1
        if halted:
            tallies['bars_halted'] += 1
    trace = pd.DataFrame(positions)
    # Reject even subtle drift in our independent replay: source curve is authority.
    if not np.allclose(trace.equity_eur_after_mark.to_numpy(), expected_curve.equity.to_numpy(),
                       atol=1e-8, rtol=0):
        raise ValueError('Replayed decisions/equity differ from existing v0.8 simulator')
    if len(events) != len(expected_trades):
        raise ValueError('Replayed trade count disagrees with existing v0.8 simulator')
    for actual, expected in zip(events, expected_trades):
        if (actual['entry_time'] != expected['entry_time'] or
                actual['exit_time'] != expected['exit_time'] or
                not math.isclose(actual['net_pnl_eur'], expected['net_pnl'], rel_tol=0, abs_tol=1e-9)):
            raise ValueError('Replayed trade timestamps/PnL disagree with v0.8 simulator')
    if not math.isclose(trace.equity_eur_after_mark.iloc[-1]/100-1,
                        baseline['return'], abs_tol=1e-10):
        raise ValueError('Final research equity mismatch')
    if len(events) != baseline['trades']:
        raise ValueError('Expected trade count mismatch')
    counts = {name: int(tallies[name]) for name in (
        'closed_candle_buy_signals', 'closed_candle_sell_signals',
        'flat_bars_at_open', 'flat_no_entry_signal_bars', 'entry_blocked_by_risk',
        'entry_blocked_by_cash', 'entry_candidates', 'buy_signals_while_in_position',
        'entries', 'closed_trades', 'bars_in_position', 'bars_halted',
        *(f'exit_{name}' for name in EXIT_PRIORITY))}
    counts['validation_bars'] = int(hi-lo)
    counts['position_bar_fraction'] = float(tallies['bars_in_position']/(hi-lo))
    counts['open_position_at_window_end'] = bool(qty)
    counts['return'] = float(baseline['return'])
    counts['benchmark_return'] = float(baseline['benchmark_return'])
    counts['original_mean_exposure'] = float(baseline['exposure'])
    return counts, events, trace, expected_trades


def analyze(source: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    manifest, gate, audit, history, windows, equity, holdout = v082.load_verified(source)
    if manifest.get('source_hashes',{}).get('atlas_v08.py') != sha256(PROJECT/'atlas_v08.py'):
        raise ValueError('Research replay source version differs from archived v0.8 code')
    fee, slip = float(manifest['fee_rate_assumption']),float(manifest['slippage_assumption'])
    if manifest['protocol']['primary_days'] != PRIMARY_DAYS:
        raise ValueError('Unexpected primary research protocol')
    cfg = json.loads((PROJECT/'paper_config.json').read_text())
    v06.verify_unchanged_config(cfg)
    if sha256(PROJECT/'paper_config.json') != manifest.get('risk_sha256'):
        raise ValueError('Research risk config differs from archived source')
    segments = v06.contiguous_segments(history[history.timestamp<holdout].copy())
    primary = windows[(windows.days == PRIMARY_DAYS) & (windows.allocation == ALLOCATION) &
                      (windows.cost_factor == COST_FACTOR) & (windows.parameters == 'baseline')]
    if primary.empty or primary.duplicated(['strategy','segment','start']).any():
        raise ValueError('Missing or duplicated primary research windows')
    win_rows, trade_rows, bar_rows = [],[],[]
    for w in primary.to_dict('records'):
        model, segid = w['strategy'], int(w['segment'])
        if model not in v08.MODELS or not 1 <= segid <= len(segments):
            raise ValueError('Unexpected strategy/segment')
        seg = segments[segid-1]
        start, end = int(w['start']), int(w['end_exclusive'])
        if not (start<end<=holdout):
            raise ValueError('Attempt to evaluate the sealed holdout')
        match = seg.index[seg.timestamp==start].tolist()
        if len(match)!=1:
            raise ValueError('Window start not in verified segment')
        lo, hi = match[0], match[0]+PRIMARY_DAYS*6
        if hi>len(seg) or int(seg.timestamp.iloc[hi-1])+v08.STEP*1000!=end:
            raise ValueError('Invalid research window/continuity')
        # Validate source per-window curve *before* attributing its trades.
        c = equity[(equity.strategy==model)&(equity.window_start==start)].sort_values('timestamp')
        if len(c)!=hi-lo or not np.array_equal(c.timestamp.to_numpy(),seg.timestamp.iloc[lo:hi].to_numpy()):
            raise ValueError('Archived equity timestamps mismatch')
        m, original_curve, _, _ = v08.simulate(seg,lo,hi,model,cfg,ALLOCATION,fee,slip)
        if not np.allclose(original_curve[['equity','benchmark','exposure']],
                           c[['equity','benchmark','exposure']],atol=1e-8,rtol=0):
            raise ValueError('Archived equity curves differ from independently replayed v0.8')
        if int(w['trades']) != m['trades'] or not math.isclose(w['return'], m['return'],abs_tol=1e-8):
            raise ValueError('Archived window metrics differ from v0.8')
        stats, events, bars, _ = replay_attribution(seg,lo,hi,model,cfg,fee,slip)
        key = {'strategy':model,'segment':segid,'window_start_ms':start,
               'window_end_exclusive_ms':end}
        win_rows.append({**key,**stats})
        trade_rows.extend({**key,**e} for e in events)
        bar_rows.extend({**key,**b} for b in bars.to_dict('records'))
    results = pd.DataFrame(win_rows).sort_values(['strategy','window_start_ms']).reset_index(drop=True)
    trades = pd.DataFrame(trade_rows)
    bars = pd.DataFrame(bar_rows)
    summary = {'version':'0.8.3-entry-exit-attribution','data_source':'real Coinbase BTC/EUR research, Kraken cross-audited',
               'original_run_git_sha':manifest['git_commit'],'source_end_exclusive':manifest['end_exclusive'],
               'holdout_start':manifest['holdout_start'],'primary_90d_windows':len(results),
               'models':{},'release_gate':{'passed':False,'paper_trading_authorized':False,
                                            'holdout_evaluated':False,'status':'DIAGNOSTIC_ONLY'},
               'methodology':'Independent next-4h-open decision replay; exact original equity/trade verification. No counterfactual parameter fitting.',
               'limits':['Repeatedly examined historical validation windows; do not treat as fresh OOS.',
                         'Stops and take-profits are assessed only at the next 4h open, not intrabar.',
                         'Per-window 100 EUR portfolios reset; summed trade PnL is not a continuous portfolio.',
                         'Closed trades exclude unrealized open positions at each window end.',
                         'Holdout excluded from signals, simulation and diagnostics.',
                         'Diagnostic findings do not justify changing rules or approving strategies.']}
    for model,g in results.groupby('strategy'):
        tr = trades[trades.strategy==model] if not trades.empty else pd.DataFrame()
        reason_counts = {name:int((tr.exit_reason_primary==name).sum()) if len(tr) else 0 for name in EXIT_PRIORITY}
        summary['models'][model]={'windows':len(g),'validation_bars':int(g.validation_bars.sum()),
                                  'closed_trades':int(g.closed_trades.sum()),
                                  'entry_signals':int(g.closed_candle_buy_signals.sum()),
                                  'entries':int(g.entries.sum()),
                                  'avg_position_bar_fraction':float(g.position_bar_fraction.mean()),
                                  'avg_actual_exposure':float(g.original_mean_exposure.mean()),
                                  'flat_bars_without_entry_signal':int(g.flat_no_entry_signal_bars.sum()),
                                  'risk_blocked_entries':int(g.get('entry_blocked_by_risk',pd.Series(0,index=g.index)).sum()),
                                  'exits_by_primary_reason':reason_counts,
                                  'mean_hold_days_closed':float(tr.hold_bars.mean()/6) if len(tr) else None,
                                  'sum_net_closed_trade_pnl_EUR_across_reset_windows_DIAGNOSTIC_ONLY':float(tr.net_pnl_eur.sum()) if len(tr) else 0.0}
    return results,trades,bars,summary


def report_text(summary:dict) -> str:
    lines=['# Atlas Trading AI v0.8.3 – Ein- und Ausstiegsaudit', '',
           '**Nur Forschungsdiagnostik – keine Handelsfreigabe, finaler Holdout versiegelt.**','',
           f"Originaldaten bis {summary['source_end_exclusive']}; Holdout beginnt am {summary['holdout_start']}.",
           f"Kontrollierte 90-Tage-Fenster: {summary['primary_90d_windows']}.",'',
           '| Strategie | Abschlüsse | Einstiegssignale | Positionierte Bars | Durchschnittliche Exposure |',
           '|---|---:|---:|---:|---:|']
    for model, v in summary['models'].items():
        lines.append(f"| {model} | {v['closed_trades']} | {v['entry_signals']} | {v['avg_position_bar_fraction']:.1%} | {v['avg_actual_exposure']:.2%} |")
    lines+=['','## Primäre Ausstiegsgründe','']
    for model,v in summary['models'].items():
        lines += [f'**{model}:** '+', '.join(f'{k}: {n}' for k,n in v['exits_by_primary_reason'].items())+'.']
    lines +=['','**Interpretation:** Einstiegshäufigkeit, Haltezeit und Stop/Take-Verteilung beschreiben Mechanik, **nicht** einen nachgewiesenen Trading-Vorteil. Nicht anhand dieser wiederverwendeten Fenster eine Gewinnerstrategie wählen.','',
             '## Nächster wissenschaftlicher Schritt','',
             'Vorab genau eine testbare Hypothese, Parameter und Kosten festlegen; anschließend neue zeitlich spätere Live-Paper-Daten sammeln und strikt OOS vergleichen. Keine automatische Freigabe.','',
             '## Einschränkungen','']
    lines += ['- '+x for x in summary['limits']]
    return '\n'.join(lines)+'\n'


def plot_attribution(summary: dict, output: Path) -> None:
    """Purely descriptive; no ranked/optimized strategies or significance claims."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    models=list(summary['models'])
    if not models:
        return
    fig,ax=plt.subplots(figsize=(9,4.5))
    labels=['stop_loss','take_profit','signal_exit','drawdown_halt','daily_loss']
    x=np.arange(len(labels),dtype=float)
    width=.8/len(models)
    for i,model in enumerate(models):
        counts=summary['models'][model]['exits_by_primary_reason']
        ax.bar(x-.4+width*(i+.5),[counts[name] for name in labels],width=width,label=model)
    ax.set_xticks(x,['Stop-Loss','Take-Profit','Signal','Max. Drawdown','Tagesverlust'])
    ax.set_ylabel('Abgeschlossene Trades (7 getrennte Fenster je Strategie)')
    ax.set_title('Atlas v0.8.3: Historische Ausstiegsgründe (nur Diagnostik)')
    ax.legend()
    fig.tight_layout()
    fig.savefig(output/'exit_reasons.png',dpi=140)
    plt.close(fig)


def run(source: Path, output: Path) -> dict:
    source = Path(source).resolve()
    output = v05.safe_output_dir(Path(output),project=PROJECT)
    if output==source or source in output.parents or output in source.parents or output.exists():
        raise ValueError('Separate, previously nonexistent output directory required')
    before = v05.protected_hashes(PROJECT)
    windows,trades,bars,summary=analyze(source)
    if before!=v05.protected_hashes(PROJECT):
        raise ValueError('Protected paper account or config changed during analysis')
    output.mkdir(parents=True,exist_ok=False)
    windows.to_csv(output/'entry_exit_windows.csv',index=False)
    trades.to_csv(output/'attributed_trades.csv',index=False)
    bars.to_csv(output/'position_decision_bars.csv',index=False)
    (output/'SUMMARY_V083_DE.md').write_text(report_text(summary))
    (output/'diagnostics.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    plot_attribution(summary,output)
    hashes={p.name:sha256(p) for p in output.iterdir() if p.is_file()}
    (output/'SHA256SUMS.json').write_text(json.dumps(hashes,indent=2)+'\n')
    if before!=v05.protected_hashes(PROJECT):
        raise ValueError('Protected paper account or config changed during report writing')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('atlas-v083-diagnostics'))
    opts=p.parse_args()
    result=run(opts.input,opts.output)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
