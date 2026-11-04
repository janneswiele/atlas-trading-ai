"""Approval-bound training and walk-forward research, never self-promotes."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import pandas as pd
from .backtest import simulate
from .policy import Assumptions, approved_csv, sha_file
from .signals import Candidate, candidates

TRAIN_BARS = 480
VALID_BARS = 120
STEP_BARS = 120
MIN_FOLDS = 2
MIN_CLOSED_TRADES = 8


def windows(length: int) -> list[tuple[int, int, int]]:
    """For each fold, pick on [0,train_end), evaluate on [train_end,val_end).

    Inputs/strategy choices for fold k never depend on validation of fold k.
    Later folds may train on earlier observed validation bars, as standard for
    rolling walk-forward; all results stay experimental and non-promotable.
    """
    return [(train_end-TRAIN_BARS, train_end, train_end+VALID_BARS)
            for train_end in range(TRAIN_BARS, length-VALID_BARS+1, STEP_BARS)]


def _rank(m: dict) -> float:
    """Conservative internal training score, with penalty for sparse trading."""
    return (m['alpha_net'] - 1.5 * abs(m['max_drawdown'])
            - .01 * max(0, 5-m['closed_trades']))


def evaluate(bars: pd.DataFrame, provenance: dict, *, grid: tuple[Candidate,...]|None = None,
             fee_multiplier: float = 1.0) -> dict:
    """Pre-register grid. Select candidate by training only, validate later.

    Reserves NO additional holdout evaluation; there is no promotion API.
    """
    if grid is None: grid = candidates()
    if len(grid)==0 or len(set(s.identifier for s in grid))!=len(grid):
        raise ValueError('Candidate grid empty or duplicates')
    if not 1 <= fee_multiplier <= 2:
        raise ValueError('Unsupported fee stress')
    folds = windows(len(bars))
    if len(folds)<MIN_FOLDS: raise ValueError('Need at least two walk-forward validation folds (>=720 4h candles)')
    cfg = Assumptions(fee=Assumptions().fee*fee_multiplier)
    trials=[]
    for train_start,train_end,val_end in folds:
        train_results=[]
        for spec in grid:
            stats = simulate(bars, spec, max(train_start, 205), train_end, cfg).metrics
            train_results.append((spec, stats))
        winner, training_metrics = max(train_results, key=lambda x: (_rank(x[1]),-len(x[0].label),x[0].identifier))
        validation = simulate(bars,winner,train_end,val_end,cfg)
        trials.append({'train_start_ms':int(bars.timestamp.iloc[max(train_start,205)]),
                       'train_end_exclusive_ms':int(bars.timestamp.iloc[train_end]),
                       'validate_end_exclusive_ms':int(bars.timestamp.iloc[val_end-1])+14_400_000,
                       'selection_rule':'max training alpha - 1.5*abs(drawdown) - sparse-trade penalty',
                       'winner':asdict(winner),'winner_id':winner.identifier,
                       'training':training_metrics,'validation':validation.metrics,
                       'validation_orders':validation.orders})
    oos = [f['validation'] for f in trials]
    total_trades=sum(m['closed_trades'] for m in oos)
    alpha_sum=sum(m['alpha_net'] for m in oos)
    negative=sum(m['alpha_net']<=0 for m in oos)
    maxdd=min(m['max_drawdown'] for m in oos)
    # A research-only gate; never grants virtual execution or code promotion.
    research_gate = (len(folds)>=3 and total_trades>=MIN_CLOSED_TRADES and
                     negative==0 and alpha_sum>0 and maxdd>-0.10)
    result={'schema':'atlas-research-v1.0','status':'RESEARCH_ONLY_NOT_APPROVED',
            'execution_permission':False,'champion':None,'candidate_pool_size':len(grid),
            'data_source_type':provenance['source_type'],'data_approval_id':provenance['approval_id'],
            'data_sha256':provenance['sha256'],
            'data_window':{'start_ms':provenance['start_ms'],'end_exclusive_ms':provenance['end_exclusive_ms']},
            'assumptions':asdict(cfg),'strategy_grid_sha256':sha256(json.dumps([asdict(x) for x in grid],sort_keys=True).encode()).hexdigest(),
            'walk_forward':{'train_prefix_bars':TRAIN_BARS,'training_execution_warmup_bars':205,'validation_bars':VALID_BARS,'step_bars':STEP_BARS,
                            'folds':len(folds),'selection_uses_validation':False},
            'aggregate_validation':{'closed_trades':total_trades,'sum_net_alpha':alpha_sum,
                                    'folds_not_outperforming':negative,'worst_fold_drawdown':maxdd,
                                    'research_screen_passed':bool(research_gate and provenance['source_type']=='observed')},
            'notes':['No sealed holdout evaluated','No strategy automatically promoted',
                     'Paper execution uses unchanged v0.9 runner, not this research report'],
            'fold_results':trials}
    return result


def run_file(csv:Path, manifest:Path, out:Path, *, fee_multiplier=1.0) -> Path:
    bars, provenance = approved_csv(csv,manifest,min_bars=TRAIN_BARS+2*VALID_BARS)
    results = evaluate(bars,provenance,fee_multiplier=fee_multiplier)
    path=Path(out)
    path.mkdir(parents=True,exist_ok=True)
    (path/'research.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    summary={'schema':results['schema'],'approval_id':results['data_approval_id'],
             'source_type':results['data_source_type'], 'passed_research_screen':results['aggregate_validation']['research_screen_passed'],
             'folds':results['walk_forward']['folds'],'candidate_pool_size':results['candidate_pool_size'],
             'permission':'RESEARCH_ONLY_NEVER_TRADE'}
    (path/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return path/'research.json'
