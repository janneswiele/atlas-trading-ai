"""Atlas v0.8.4, RESEARCH ONLY: two fixed, pre-registered BTC/EUR spot hypotheses.

Strictly replays historical pre-holdout windows; does not authorise paper/live trading.
This is an exploratory, previously examined period, NOT fresh out-of-sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import atlas_v05 as v05
import atlas_v06 as v06
import atlas_v08 as v08
import atlas_v082 as v082

PROJECT = Path(__file__).resolve().parent
WINDOW_DAYS = 90
WINDOW_BARS = WINDOW_DAYS * 6
WARMUP_BARS = 541
CALIBRATION_BARS = 341
ALLOCATION = .2
CANDIDATES = ('Donchian30_Chandelier22_ATR14x2p5', 'TSMOM60_Vol30_180x1p5')
MODELS = (*v08.MODELS, *CANDIDATES)
PREREGISTRATION = {
    'status': 'FROZEN_EXPLORATORY_HYPOTHESES_NOT_A_TRADING_PERMISSION',
    'timeframe': 'BTC/EUR spot, 4h UTC closed candles, execution at NEXT 4h open only',
    'candidate_1': {
        'name': CANDIDATES[0], 'entry': 'close[t] > previous 30-bar highest HIGH (exclude t); rising-edge only',
        'exit': 'close[t] < rolling 22-bar highest HIGH (through t) minus 2.5 * ATR14[t]',
        'fixed_params': {'donchian': 30, 'chandelier_lookback': 22, 'atr': 14, 'atr_multiplier': 2.5},
    },
    'candidate_2': {
        'name': CANDIDATES[1],
        'entry': 'close[t] > close[t-60] and 30-bar log-return volatility[t] <= 1.5 * prior 180 observations median volatility; rising-edge only',
        'exit': 'momentum <= 0 OR volatility > 1.5 * prior median',
        'fixed_params': {'momentum': 60, 'vol_lookback': 30, 'vol_reference': 180, 'vol_ceiling_multiplier': 1.5},
    },
    'risk': 'Unchanged v0.4/v0.8: max 20% initial allocation, 2% stop, 4% take-profit, 3% daily-loss, 10% maximum drawdown; no intrabar execution',
    'cost_factors': (1, 2, 3),
    'comparison': 'SMA20/50, EMA Trend, passive fixed 20%, passive pre-window volatility-calibrated weight (diagnostic)',
    'no_grid_search': True, 'holdout_evaluated': False,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidate_signals(frame: pd.DataFrame, model: str) -> tuple[np.ndarray, np.ndarray]:
    """Signals of COMPLETED bar t only. Valid entry can fill at open t+1.

    No future shifts, no terminal-bar look ahead; all indicators reset at gaps.
    """
    if model not in CANDIDATES:
        raise ValueError('Strategy is not one of two frozen v0.8.4 hypotheses')
    v06.validate_4h_rows(frame)
    if (frame.timestamp.diff().dropna() != v08.STEP * 1000).any():
        raise ValueError('Signal history crosses a missing 4h candle')
    close = frame['close'].astype(float)
    if model == CANDIDATES[0]:
        previous_max = frame.high.rolling(30, min_periods=30).max().shift(1)
        breakout = (close > previous_max) & previous_max.notna()
        prev_close = close.shift(1)
        prev_channel = previous_max.shift(1)
        # Strict crossing; avoids repetitive entries while price remains above channel.
        enter = breakout & (prev_close <= prev_channel)
        prev = close.shift(1)
        true_range = pd.concat([
            frame.high - frame.low, (frame.high - prev).abs(), (frame.low - prev).abs()
        ], axis=1).max(axis=1)
        atr = true_range.rolling(14, min_periods=14).mean()
        chandelier = frame.high.rolling(22, min_periods=22).max() - 2.5 * atr
        exit_signal = (close < chandelier) & chandelier.notna()
    else:
        log_return = np.log(close).diff()
        volatility = log_return.rolling(30, min_periods=30).std(ddof=0)
        # Excludes the current candle's volatility from the historical median.
        reference = volatility.rolling(180, min_periods=180).median().shift(1)
        valid = reference.notna() & (reference > 0) & volatility.notna()
        momentum = close > close.shift(60)
        allowed = momentum & (volatility <= 1.5 * reference) & valid
        enter = allowed & (~allowed.shift(1, fill_value=False))
        exit_signal = (~allowed) & valid
    return enter.fillna(False).to_numpy(dtype=bool), exit_signal.fillna(False).to_numpy(dtype=bool)


def simulation(frame: pd.DataFrame, lo: int, hi: int, model: str, cfg: dict,
               fee: float, slip: float) -> tuple[dict, pd.DataFrame, list[dict]]:
    """v0.8 execution/risk-accounting copied verbatim except for signal injection.

    The baseline-equivalence test checks metrics/curve/trades against v08.simulate.
    All stop/take checks use current OPEN only, not retroactive candle highs/lows.
    """
    v06.verify_unchanged_config(cfg)
    if model not in MODELS or not 200 <= lo < hi <= len(frame):
        raise ValueError('Unregistered model or insufficient history/window')
    if not all(math.isfinite(float(x)) and 0 <= x < .03 for x in (fee, slip)):
        raise ValueError('Invalid research cost')
    data = frame.iloc[:hi].reset_index(drop=True)
    v06.validate_4h_rows(data)
    if (data.timestamp.diff().dropna() != v08.STEP * 1000).any():
        raise ValueError('Simulation cannot cross a missing candle')
    if model in v08.MODELS:
        buy, sell = v08.signals(data, model)
    else:
        buy, sell = candidate_signals(data, model)
    cash, qty, cost, entry, peak = 100., 0., 0., 0., 100.
    halted = False
    day, day_value = None, 100.
    trades, curve = [], []
    fees, turnover = 0., 0.
    benchmark_qty = 100 * ALLOCATION / (float(data.open.iloc[lo]) * (1 + slip) * (1 + fee))
    for i in range(lo, hi):
        bar = data.iloc[i]
        price = float(bar.open)
        value = cash + qty * price
        peak = max(peak, value)
        if int(bar.timestamp) // 86400000 != day:
            day, day_value = int(bar.timestamp) // 86400000, value
        daily = value <= day_value * (1 - cfg['daily_loss_limit'])
        halted = halted or value <= peak * (1 - cfg['max_drawdown'])
        # Priority and execution conventions identical to v0.8.
        if qty and (sell[i-1] or price <= entry * (1-cfg['stop_loss']) or
                    price >= entry * (1+cfg['take_profit']) or halted or daily):
            gross = qty * price * (1-slip)
            proceeds = gross * (1-fee)
            fees += gross * fee
            turnover += gross
            trades.append({'entry_time': entry_time, 'exit_time': int(bar.timestamp),
                           'net_pnl': proceeds-cost})
            cash += proceeds
            qty = 0.
        elif not qty and i > lo and buy[i-1] and not halted and not daily and cash >= 10:
            cost = cash * ALLOCATION
            entry = price * (1+slip)
            qty = cost / (entry*(1+fee))
            cash -= cost
            fees += cost*fee/(1+fee)
            turnover += cost/(1+fee)
            entry_time = int(bar.timestamp)
        marked = cash + qty*float(bar.close)*(1-slip)*(1-fee)
        curve.append({'timestamp': int(bar.timestamp), 'equity': marked,
                      'benchmark': 100*(1-ALLOCATION) + benchmark_qty*float(bar.close)*(1-slip)*(1-fee),
                      'exposure': qty*float(bar.close)/marked})
    curve = pd.DataFrame(curve)
    rets = np.diff(np.log(np.r_[100., curve.equity]))
    centered = rets - rets.mean()
    n = len(rets)
    lag = min(42, n-1)
    variance = float(centered @ centered / n)
    hac = variance + 2*sum((1-k/(lag+1))*float(centered[k:] @ centered[:-k])/n for k in range(1,lag+1))
    pnl = np.array([t['net_pnl'] for t in trades])
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    dd = lambda arr: float(np.min(arr/np.maximum.accumulate(arr)-1))
    metrics = {'return': float(curve.equity.iloc[-1]/100-1),
               'benchmark_return': float(curve.benchmark.iloc[-1]/100-1),
               'alpha': float((curve.equity.iloc[-1]-curve.benchmark.iloc[-1])/100),
               'max_drawdown': dd(np.r_[100.,curve.equity]),
               'benchmark_drawdown': dd(np.r_[100.,curve.benchmark]),
               'trades': len(trades),
               'win_rate': float((pnl>0).mean()) if len(pnl) else None,
               'profit_factor': float(gains/losses) if losses else None,
               'profit_factor_no_losses': bool(not losses and gains>0),
               'annual_volatility': float(np.sqrt(variance*2190)),
               'hac_sharpe': float(rets.mean()*np.sqrt(2190/hac)) if hac>0 else None,
               'exposure': float(curve.exposure.mean()),
               'turnover': turnover/100, 'paid_fees': fees,
               'open_at_end': bool(qty), 'halted': bool(halted)}
    return metrics, curve, trades


def calibration(frame: pd.DataFrame, lo: int, model: str, cfg: dict, fee: float, slip: float) -> dict:
    """Pre-window volatility only: previous 341 bars, with earlier indicator warmup."""
    if lo < WARMUP_BARS or lo > len(frame):
        raise ValueError('Insufficient calibration history')
    # At lo=541, calibration starts at bar 200 (v0.8 simulator minimum).
    if model in v08.MODELS:
        m, _, _, _ = v08.simulate(frame, lo-CALIBRATION_BARS, lo, model, cfg,
                                  ALLOCATION, fee, slip)
    else:
        m, _, _ = simulation(frame, lo-CALIBRATION_BARS, lo, model, cfg, fee, slip)
    price = frame.close.iloc[lo-CALIBRATION_BARS:lo].to_numpy(dtype=float)
    underlying_vol = v082.annual_volatility(price)
    strat_vol = m['annual_volatility']
    if not math.isfinite(underlying_vol) or underlying_vol <= 0:
        raise ValueError('Cannot calibrate against zero underlying volatility')
    valid = bool(m['trades'] >= 3 and strat_vol > 0)
    return {'benchmark_weight': float(np.clip(strat_vol/underlying_vol, 0, ALLOCATION)),
            'calibration_valid': valid, 'calibration_trades': int(m['trades'])}


def verified_input(source: Path):
    manifest, _, _, history, windows, equity, holdout = v082.load_verified(source)
    if manifest.get('source_hashes', {}).get('atlas_v08.py') != sha256(PROJECT/'atlas_v08.py'):
        raise ValueError('Source original simulator hash differs: cannot verify baseline')
    cfg = json.loads((PROJECT/'paper_config.json').read_text())
    v06.verify_unchanged_config(cfg)
    if manifest.get('risk_sha256') != sha256(PROJECT/'paper_config.json'):
        raise ValueError('Research risk policy fingerprint mismatch')
    kr_path = Path(source)/'kraken_btc_eur_4h.csv'
    if not kr_path.is_file() or manifest.get('artifacts_sha256', {}).get(kr_path.name) != sha256(kr_path):
        raise ValueError('Missing or unverified Kraken independent data file')
    kraken = pd.read_csv(kr_path)
    v06.validate_4h_rows(kraken)
    training = history.loc[history.timestamp < holdout].reset_index(drop=True)
    if training.empty or (training.timestamp >= holdout).any():
        raise ValueError('Attempt to read holdout into evaluation')
    # Kraken is truncated BEFORE any signal calculation.
    kraken = kraken.loc[kraken.timestamp < holdout].reset_index(drop=True)
    primary = windows[(windows.days == WINDOW_DAYS) & (windows.allocation == ALLOCATION) &
                      (windows.cost_factor == 1) & (windows.parameters == 'baseline')]
    if primary.empty or primary.duplicated(['strategy','segment','start']).any():
        raise ValueError('Invalid original preregistered windows')
    if set(primary.strategy) != set(v08.MODELS):
        raise ValueError('Original strategy baselines absent')
    return manifest, cfg, training, kraken, primary, equity, holdout


def evaluate(source: Path, *, bootstrap: int = 1000) -> tuple[pd.DataFrame, dict]:
    """Historical exploratory paired windows; no selection/approval/holdout access."""
    if not (100 <= bootstrap <= 100_000):
        raise ValueError('Invalid bootstrap count')
    manifest, cfg, training, kraken, primary, equity, holdout = verified_input(source)
    fee, slip = float(manifest['fee_rate_assumption']), float(manifest['slippage_assumption'])
    segments = v06.contiguous_segments(training)
    # Pre-split independent Kraken into O(1) timestamp index; never bridge holes.
    kr = kraken.set_index('timestamp', verify_integrity=True)
    rows, excluded = [], []
    original = primary.loc[primary.strategy == v08.MODELS[0]].sort_values('start')
    if len(original) < 3:
        raise ValueError('Insufficient independent original 90-day research windows')
    for w in original.to_dict('records'):
        segid, start, end = int(w['segment']), int(w['start']), int(w['end_exclusive'])
        if not (1 <= segid <= len(segments)) or not start < end <= holdout:
            raise ValueError('Window crosses sealed holdout or source segment boundary')
        cb = segments[segid-1]
        locations = cb.index[cb.timestamp == start].tolist()
        if len(locations) != 1:
            raise ValueError('Original baseline starting bar not found')
        lo, hi = locations[0], locations[0] + WINDOW_BARS
        if lo < WARMUP_BARS or hi > len(cb) or int(cb.timestamp.iloc[hi-1])+v08.STEP*1000 != end:
            raise ValueError('Historical baseline window no longer reproduces')
        # All indicators need at most 211 prior bars. The existing 541-bar
        # warmup is therefore sufficient. Use the SAME minimal window for both
        # exchanges: unrelated ancient Kraken gaps must not reject later windows.
        # Cutting at the 541-bar warmup never touches the global sealed holdout.
        local_lo, local_hi = WARMUP_BARS, WARMUP_BARS + WINDOW_BARS
        historic = cb.iloc[lo-WARMUP_BARS:hi].reset_index(drop=True)
        frames = {'Coinbase': historic}
        times = historic.timestamp.to_numpy(dtype=np.int64)
        if np.isin(times, kr.index.to_numpy(dtype=np.int64)).all():
            alt = kr.loc[times].reset_index()
            if np.array_equal(alt.timestamp.to_numpy(dtype=np.int64), times):
                frames['Kraken'] = alt
        else:
            excluded.append({'start': start, 'reason': 'Kraken gap in 541-bar warmup/window: no interpolation'})
        # All four strategies compare on identical, original 90-day time windows.
        for exchange, frame in frames.items():
            for model in MODELS:
                for factor in (1, 2, 3):
                    research_fee, research_slip = fee*factor, slip*factor
                    m, curve, trades = simulation(frame, local_lo, local_hi, model, cfg, research_fee, research_slip)
                    if exchange == 'Coinbase' and factor == 1 and model in v08.MODELS:
                        observed = primary[(primary.strategy == model) &
                                           (primary.segment == segid) & (primary.start == start)]
                        if len(observed) != 1 or not math.isclose(m['return'], float(observed.iloc[0]['return']), abs_tol=1e-10):
                            raise ValueError('Original frozen baseline return not reproduced')
                        archived = equity[(equity.strategy == model) & (equity.window_start == start)]
                        if len(archived) != len(curve) or not np.array_equal(archived.timestamp.to_numpy(),curve.timestamp.to_numpy()):
                            raise ValueError('Original archived equity timeline differs')
                        if not np.allclose(archived.equity,curve.equity,rtol=0,atol=1e-8):
                            raise ValueError('Original archived equity values differ')
                    cal = calibration(frame, local_lo, model, cfg, research_fee, research_slip)
                    risk_passive = v082.static_passive(float(frame.open.iloc[local_lo]),
                                                      frame.close.iloc[local_lo:local_hi].to_numpy(),
                                                      cal['benchmark_weight'], research_fee, research_slip)
                    rows.append({'source': exchange, 'strategy': model, 'segment': segid,
                                 'window_start_ms': start, 'window_end_exclusive_ms': end,
                                 'cost_factor': factor,
                                 'risk_calibrated_passive_return': float(risk_passive[-1]/100-1),
                                 'alpha_vs_prior_vol_calibrated_passive': float(m['return']-(risk_passive[-1]/100-1)),
                                 **cal, **m})
    result = pd.DataFrame(rows).sort_values(['source','strategy','window_start_ms','cost_factor']).reset_index(drop=True)
    stats = {}
    pvalues = []
    for model in CANDIDATES:
        sample = result[(result.source=='Coinbase')&(result.strategy==model)&(result.cost_factor==1)]
        if len(sample) < 3 or len(sample) != len(original):
            raise ValueError('Missing paired candidates')
        # 90d window returns, NOT 4h observations; limited sample, already examined.
        boot = v08.stationary_bootstrap(sample.alpha.to_numpy(), bootstrap, block=1, seed=804)
        pvalues.append(boot['p_one_sided'])
        stats[model] = {'windows': int(len(sample)),
                        'mean_strategy_return_pct': round(100*float(sample['return'].mean()),4),
                        'mean_alpha_vs_passive20_pp': round(100*float(sample.alpha.mean()),4),
                        'median_alpha_vs_passive20_pp': round(100*float(sample.alpha.median()),4),
                        'positive_alpha_windows': int((sample.alpha>0).sum()),
                        'closed_trades': int(sample.trades.sum()),
                        'mean_exposure_pct': round(100*float(sample.exposure.mean()),4),
                        'mean_max_drawdown_pct': round(100*float(sample.max_drawdown.mean()),4),
                        'bootstrap_window_alpha_ci_95_pp': [round(100*boot['ci_low'],4),round(100*boot['ci_high'],4)],
                        'bootstrap_exploratory_p': float(boot['p_one_sided']),
                        'risk_calibrated_windows_with_3plus_prior_trades': int(sample.calibration_valid.sum())}
    for model, adj in zip(CANDIDATES,v08.holm(pvalues)):
        stats[model]['holm_p_two_candidates_exploratory'] = float(adj)
    summary = {'version': '0.8.4-EXPLORATORY-NO-TRADING', 'hypotheses': PREREGISTRATION,
               'prior_research_commit': manifest.get('git_commit'),
               'first_complete_window_start_ms': int(original.start.min()),
               'holdout_start': manifest['holdout_start'], 'holdout_evaluated': False,
               'paper_trading_authorized': False,
               'release_gate': {'passed':False, 'status':'RESEARCH_ONLY_NEVER_AUTOMATICALLY_APPROVE',
                                'paper_trading_authorized':False},
               'sample_status':'REUSED_PRE_HOLDOUT_VALIDATION_WINDOWS_NOT_FRESH_OOS',
               'cost_assumptions': {'fee_per_fill':fee, 'slippage_per_fill':slip,
                                    'stress_multipliers':[1,2,3]},
               'primary_candidate_diagnostics':stats,
               'original_windows_count':int(len(original)),
               'kraken_complete_window_count':int(result[(result.source=='Kraken') & (result.strategy==CANDIDATES[0]) & (result.cost_factor==1)].shape[0]),
               'kraken_excluded_windows':excluded,
               'limitations':['PREVIOUSLY EXAMINED WINDOWS: none of the reported p-values are confirmatory',
                              'Risk-calibrated passive benchmark is pre-window estimated, not realized equal risk',
                              'Stop/take evaluated at NEXT 4h open; no intrabar stop guarantees',
                              'Window portfolios reset to EUR100, not continuous realised return',
                              'Cross-exchange missing windows excluded, never interpolated',
                              'No grids, fitting, selection of parameters, or automatic release',
                              'Final global 20% holdout never supplied to any signals/backtests']}
    return result, summary


def run(source: Path, output: Path, *, bootstrap: int = 1000) -> dict:
    """Do computations before creating output. No modifications to existing project files."""
    source = Path(source).resolve()
    out = v05.safe_output_dir(Path(output), project=PROJECT)
    if out.exists() or source == out or source in out.parents or out in source.parents:
        raise ValueError('Require a new, independent research output directory')
    original = v05.protected_hashes(PROJECT)
    results, summary = evaluate(source, bootstrap=bootstrap)
    if original != v05.protected_hashes(PROJECT):
        raise ValueError('Production-integrity hashes changed')
    out.mkdir(parents=True, exist_ok=False)
    results.to_csv(out/'historical_paired_windows.csv',index=False)
    v08.save_json(out/'diagnostics.json', summary)
    v08.save_json(out/'release_gate.json', summary['release_gate'])
    report = ['# Atlas v0.8.4 – zwei festgelegte Forschungshypothesen', '',
              '**Achtung:** Historische, mehrfach untersuchte Entwicklungsfenster, KEIN neuer Out-of-sample-Beweis.',
              '**Keine Strategie ist freigegeben.** Finaler Holdout bleibt versiegelt.', '',
              '## Vergleich auf den bestehenden Coinbase-90-Tage-Fenstern (Kosten 1x)', '',
              '| Strategie | Fenster | Trades | Mittel netto % | Alpha vs. passive 20 % (Prozentpunkte) | Exposure % |',
              '|---|---:|---:|---:|---:|---:|']
    for model in CANDIDATES:
        s = summary['primary_candidate_diagnostics'][model]
        report.append(f"| {model} | {s['windows']} | {s['closed_trades']} | {s['mean_strategy_return_pct']:.2f} | {s['mean_alpha_vs_passive20_pp']:.2f} | {s['mean_exposure_pct']:.2f} |")
    report.extend(['', 'Weitere Details: diagnostics.json und historical_paired_windows.csv.',
                   'Die Risiko-, Stop-/Take-Profit- und Ausführungsregeln wurden nicht gelockert.',
                   '3x Kostenstress, Kraken-Parität und zwei vorher fixierte Kandidaten sind enthalten.',
                   'Die geringen Fensterzahlen machen Konfidenzintervalle statistisch unsicher.',
                   'Neue Beobachtungen müssen separat über künftige Paper-Trades erhoben werden.'])
    (out/'BERICHT_V084_DE.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    v08.save_json(out/'SHA256SUMS.json',{p.name:sha256(p) for p in out.iterdir() if p.is_file()})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,type=Path,
                        help='Original verified v0.8 research directory (not a raw unverified CSV)')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--bootstrap',type=int,default=1000)
    args = parser.parse_args()
    print(json.dumps(run(args.input,args.output,bootstrap=args.bootstrap),indent=2,allow_nan=False))


if __name__=='__main__':
    main()
