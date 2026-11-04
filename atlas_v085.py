"""Atlas v0.8.5 RESEARCH ONLY: fixed, exploratory fee-feasibility audit.

No new trading hypothesis, parameter optimization, trading authorization or holdout use.
Never writes or changes paper.py, paper_state.json, paper_config.json, or main.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import atlas_v05 as v05
import atlas_v06 as v06
import atlas_v08 as v08
import atlas_v084 as v084

PROJECT = Path(__file__).resolve().parent
# All assumptions are PRESET (not optimized). Assumed next-open taker-like fills,
# 5 bps slippage per fill. These are diagnostic examples, not exchange quotes.
COST_SCENARIOS = (
    ('fee_free_idealization', 0.),
    ('illustrative_0p5pct', .005),
    ('original_0p6pct', .006),
    ('kraken_pro_tier1_taker_0p8pct', .008),
    ('cost_stress_1p2pct', .012),
)
SLIPPAGE = .0005
MODELS = (*v08.MODELS, *v084.CANDIDATES)


def stop_take_round_trip(fee: float, slip: float = SLIPPAGE,
                         stop: float = .02, take: float = .04) -> dict:
    """Hypothetical filled-price economics, not a simulation of gap/stop execution.

    A position is bought with the full allocated cost, fee included; the stop/take
    is triggered relative to the entry fill price. Real next-open gaps differ.
    """
    if not (0 <= fee < .03 and 0 <= slip < .03 and 0 < stop < take < 1):
        raise ValueError('Invalid fixed fee/slippage/risk parameters')
    # Entry fill is price*(1+slip), so the stop/TP thresholds in the simulator
    # are relative to this fill (not the no-slip market price). Express the
    # pre-exit notional at a hypothetical market price equal to the threshold
    # applied to entry fill and account for the sell fill/slippage/fees.
    # Net return on amount spent to open:
    multiplier = (1 - slip) * (1 - fee) / (1 + fee)
    win = (1 + take) * multiplier - 1
    loss = (1 - stop) * multiplier - 1
    if win <= 0 or loss >= 0:
        threshold = None
    else:
        threshold = -loss / (win - loss)
    return {'fee_per_fill': fee, 'slippage_per_fill': slip,
            'take_profit_net_pct_at_exact_threshold':100 * win,
            'stop_loss_net_pct_at_exact_threshold':100 * loss,
            'break_even_win_rate_pct_at_exact_threshold': None if threshold is None else 100 * threshold,
            'note':'Simplified fixed threshold fills. Next-open price gaps and non-stop exits change realized results.'}


def historical_cost_audit(source: Path) -> tuple[pd.DataFrame, dict]:
    """Reuses ONLY the original seven 90d pre-holdout windows; never selects a winner."""
    manifest, cfg, training, _kraken, primary, archived_equity, holdout = v084.verified_input(source)
    if not math.isclose(float(manifest['fee_rate_assumption']), .006, abs_tol=1e-12):
        raise ValueError('Original fee assumption has changed; do not silently rebase')
    if not math.isclose(float(manifest['slippage_assumption']), SLIPPAGE, abs_tol=1e-12):
        raise ValueError('Original slippage assumption has changed')
    v06.verify_unchanged_config(cfg)
    original = primary.loc[primary.strategy == v08.MODELS[0]].sort_values('start')
    if len(original) != 7:
        raise ValueError('Expected exactly seven original paired 90-day windows')
    segments = v06.contiguous_segments(training)
    results = []
    for window in original.to_dict('records'):
        start, end, segment = int(window['start']), int(window['end_exclusive']), int(window['segment'])
        if end > holdout or segment < 1 or segment > len(segments):
            raise ValueError('Window touches global holdout or invalid segment')
        cand = segments[segment - 1]
        hits = cand.index[cand.timestamp == start].tolist()
        if len(hits) != 1:
            raise ValueError('Window not in previously frozen training data')
        lo = hits[0]
        hi = lo + v084.WINDOW_BARS
        if lo < v084.WARMUP_BARS or hi > len(cand) or int(cand.timestamp.iloc[hi - 1])+v08.STEP*1000 != end:
            raise ValueError('Window moved or insufficient warmup')
        frames = cand.iloc[lo-v084.WARMUP_BARS:hi].reset_index(drop=True)
        local_lo = v084.WARMUP_BARS
        local_hi = local_lo + v084.WINDOW_BARS
        for model in MODELS:
            for name, fee in COST_SCENARIOS:
                metrics, curve, trades = v084.simulation(frames, local_lo, local_hi, model, cfg, fee, SLIPPAGE)
                if name == 'original_0p6pct' and model in v08.MODELS:
                    o = primary[(primary.strategy == model) & (primary.segment == segment) & (primary.start == start)]
                    if len(o) != 1 or not math.isclose(metrics['return'], float(o.iloc[0]['return']), abs_tol=1e-10):
                        raise ValueError('Original baseline return diverges')
                    equity = archived_equity[(archived_equity.strategy == model) & (archived_equity.window_start == start)]
                    if len(equity) != len(curve) or not np.array_equal(equity.timestamp.to_numpy(),curve.timestamp.to_numpy()) or not np.allclose(equity.equity,curve.equity,atol=1e-8,rtol=0):
                        raise ValueError('Original baseline equity diverges')
                results.append({'strategy':model, 'window_start_ms':start,
                                'window_end_exclusive_ms':end,'cost_scenario':name,'fee_per_fill':fee,
                                'slippage_per_fill':SLIPPAGE,'net_return':metrics['return'],
                                'alpha_vs_same_cost_passive20':metrics['alpha'],
                                'same_cost_passive20_return':metrics['benchmark_return'],
                                'trades':metrics['trades'],'mean_exposure':metrics['exposure'],
                                'paid_fees_EUR_per_window_100EUR':metrics['paid_fees'],
                                'turnover_on_100EUR':metrics['turnover'],
                                'max_drawdown':metrics['max_drawdown'],
                                'open_at_end':metrics['open_at_end']})
    df = pd.DataFrame(results).sort_values(['strategy','window_start_ms','fee_per_fill']).reset_index(drop=True)
    summary = {'version':'0.8.5-FEE-AUDIT-RESEARCH-ONLY',
               'purpose':'Diagnose if existing fixed strategies lack gross signal edge or costs erase it; not a strategy search',
               'sample_status':'REUSED_PREVIOUSLY_EXAMINED_HISTORICAL_PRE_HOLDOUT_WINDOWS_NOT_NEW_OOS',
               'fee_scenarios':[{'label':label,'fee_per_fill':fee} for label,fee in COST_SCENARIOS],
               'slippage_per_fill':SLIPPAGE,
               'exchange_price_warning':'0.8% Kraken Pro tier-1 taker fee from public Nov 2026 schedule; user account/venue may differ. All figures are assumptions, not executed trades.',
               'code_fingerprints':{file:v084.sha256(PROJECT/file) for file in ('atlas_v08.py','atlas_v084.py','atlas_v085.py','paper_config.json')},
               'model_summaries':{},
               'hypothetical_stop_take_economics':[stop_take_round_trip(fee) for _,fee in COST_SCENARIOS],
               'global_holdout_start':manifest['holdout_start'],
               'holdout_evaluated':False,'paper_trading_authorized':False,
               'release_gate':{'passed':False,'paper_trading_authorized':False,'reason':'Fee diagnostics never authorize trading'},
               'limitations':[
                   'Retrospective diagnostics on pre-examined windows; selecting a winner would be data snooping',
                   'Assumed exact next-4h-open fills ignore orderbook depth and limit-order nonfills',
                   'Fixed stops/take-profits are evaluated at NEXT 4h open and may have price gaps',
                   'No guarantee that the 0.5% scenario applies to any specific broker/account',
                   'Zero-fee scenario is impossible as a practical baseline for many users and is not an approval',
                   'Original 100-EUR starting value resets for each 90-day window',
                   'Final global holdout excluded by verified_input before any simulation',
                   'No changes to production paper trading or real orders',
               ]}
    for model in MODELS:
        sd = {}
        for label, _fee in COST_SCENARIOS:
            subset = df[(df.strategy == model) & (df.cost_scenario == label)]
            if len(subset) != 7:
                raise ValueError('Incomplete historical fee sensitivity')
            sd[label] = {
                'window_count':int(len(subset)),
                'average_return_pct':round(100*float(subset.net_return.mean()),4),
                'average_alpha_vs_same_cost_passive20_pp':round(100*float(subset.alpha_vs_same_cost_passive20.mean()),4),
                'alpha_positive_windows':int((subset.alpha_vs_same_cost_passive20>0).sum()),
                'trades_total':int(subset.trades.sum()),
                'average_fees_EUR_per_window_on_100EUR':round(float(subset.paid_fees_EUR_per_window_100EUR.mean()),4),
            }
        summary['model_summaries'][model] = sd
    return df, summary


def run(source:Path, output:Path) -> dict:
    """Read-only research inputs; new independent output only; never mutate trading state."""
    source=Path(source).resolve()
    output=v05.safe_output_dir(Path(output),project=PROJECT)
    if source==output or output.exists() or source in output.parents or output in source.parents:
        raise ValueError('Output must be a new independent research directory')
    protected_before=v05.protected_hashes(PROJECT)
    rows,summary=historical_cost_audit(source)
    if protected_before!=v05.protected_hashes(PROJECT):
        raise ValueError('Protected trading files were modified')
    output.mkdir(parents=True,exist_ok=False)
    rows.to_csv(output/'historical_fee_scenarios.csv',index=False)
    v08.save_json(output/'fee_diagnostics.json',summary)
    v08.save_json(output/'release_gate.json',summary['release_gate'])
    lines=[
      '# Atlas v0.8.5 – Gebührenrealismus und Break-even (nur Forschung)', '',
      '**Keine Strategie freigegeben.** Ausschließlich bisherige historische Entwicklungsfenster, kein neuer OOS-Beweis. Globaler Holdout versiegelt.', '',
      '## Bestehende vier Strategien, unveränderte Signale und Risikoregeln', '',
      '| Modell | 0,0% Gebühr: Return je Fenster | 0,6% Gebühr: Return je Fenster | 0,8% Gebühr: Return je Fenster | 0,8% Gebühr: Alpha vs passive 20% |',
      '|---|---:|---:|---:|---:|'
    ]
    for model in MODELS:
        s=summary['model_summaries'][model]
        a=s['fee_free_idealization']['average_return_pct']
        b=s['original_0p6pct']['average_return_pct']
        c=s['kraken_pro_tier1_taker_0p8pct']['average_return_pct']
        alpha=s['kraken_pro_tier1_taker_0p8pct']['average_alpha_vs_same_cost_passive20_pp']
        lines.append(f'| {model} | {a:+.2f}% | {b:+.2f}% | {c:+.2f}% | {alpha:+.2f} pp |')
    lines.extend(['','## Stop/Take-Profit-Kostendruck (vereinfachte hypothetische Schwellenfills)',
                  'Bei unverändertem 2% Stop und 4% Take-Profit, zusätzlich 0,05% Slippage pro Fill:',
                  '','| Gebühr je Ausführung | Nettoertrag TP | Nettoverlust Stop | nötige Gewinnquote bei ausschließlichen TP-/Stop-Exits |',
                  '|---|---:|---:|---:|'])
    for item in summary['hypothetical_stop_take_economics']:
        breakeven='nicht möglich' if item['break_even_win_rate_pct_at_exact_threshold'] is None else f"{item['break_even_win_rate_pct_at_exact_threshold']:.1f}%"
        lines.append(f"| {item['fee_per_fill']*100:.1f}% | {item['take_profit_net_pct_at_exact_threshold']:+.2f}% | {item['stop_loss_net_pct_at_exact_threshold']:+.2f}% | {breakeven} |")
    lines.extend(['', 'Die Tabelle ist eine Kostenidentität, kein Prognosemodell. Gaps, andere Ausstiege und Marktverhalten verändern echte Gewinnquoten.',
                  'Bei Kraken Pro ist 0,8% Taker-Gebühr in der niedrigsten Spot-Stufe öffentlich ausgewiesen (4. November 2026).',
                  'Quelle: https://www.kraken.com/pro/fees',
                  'Auch niedrigere Gebühren verwandeln ein negatives Forschungsergebnis nicht automatisch in ein robustes Handelssignal.',
                  'Weitere Daten und Einschränkungen: fee_diagnostics.json und historical_fee_scenarios.csv.'])
    (output/'BERICHT_V085_DE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    v08.save_json(output/'SHA256SUMS.json',{p.name:v084.sha256(p) for p in output.iterdir() if p.is_file()})
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(run(a.input,a.output),allow_nan=False,indent=2))


if __name__=='__main__':
    main()
