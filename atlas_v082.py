"""Atlas v0.8.2: *read-only*, pre-holdout benchmark/exposure diagnostics.

Takes the existing v0.8.1 research artifact, never downloads market data, trades,
or evaluates the sealed strategy holdout. Outputs are exploratory only and
cannot be used to approve strategies. A pre-window volatility-calibrated
passive control is NOT proof of equal realized risk.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import atlas_v05 as v05
import atlas_v06 as v06
import atlas_v08 as v08

PROJECT = Path(__file__).resolve().parent
CALIBRATION_BARS = 341          # 56 days + 20 h; uses only preceding closed bars
MIN_CALIBRATION_TRADES = 3    # diagnostic validity flag, not a trading gate
ANNUAL_BARS = 365 * 6
REQUIRED = ('manifest.json', 'release_gate.json', 'data_quality_report.json',
            'coinbase_btc_eur_4h.csv', 'per_window_results.csv', 'equity_windows.csv')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_utc_ms(value: str) -> int:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError('UTC timestamp required')
    seconds = stamp.timestamp()
    if seconds != int(seconds) or int(seconds) % v08.STEP:
        raise ValueError('4h UTC boundary required')
    return int(seconds) * 1000


def annual_volatility(equity: np.ndarray) -> float:
    values = np.asarray(equity, dtype=float)
    if values.ndim != 1 or len(values) < 3 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Valid positive equity curve required')
    rets = np.diff(np.log(values))
    return float(np.std(rets, ddof=0) * np.sqrt(ANNUAL_BARS))


def static_passive(open_price: float, closes: np.ndarray, weight: float,
                   fee: float, slip: float) -> np.ndarray:
    """Identical static buy-and-hold cost convention as v0.8; full-account EUR.

    Start at first validation bar *open*, mark to each bar's *close*,
    include hypothetical sale cost at every mark. No future-calibrated weight.
    """
    c = np.asarray(closes, dtype=float)
    if not np.isfinite(c).all() or len(c) < 1 or (c <= 0).any() or open_price <= 0:
        raise ValueError('Invalid BTC prices')
    if not (0 <= weight <= .20) or not all(math.isfinite(x) and 0 <= x < .03 for x in (fee, slip)):
        raise ValueError('Invalid passive-control costs or weight')
    units = 100 * weight / (open_price * (1 + slip) * (1 + fee))
    return 100 * (1 - weight) + units * c * (1 - slip) * (1 - fee)


def volatility_calibration(segment: pd.DataFrame, lo: int, model: str,
                           cfg: dict, fee: float, slip: float) -> dict:
    """Calibration ends *strictly before* first validation bar; no OOS peek.

    Fixed 341-bar history with 200 further past indicator-warmup bars.
    Training-vol / BTC-vol is clamped to the unchanged 20% cap. If
    volatility or trade activity is insufficient, still report the math but
    label the comparison inconclusive.
    """
    if lo < 200 + CALIBRATION_BARS or lo > len(segment):
        raise ValueError('Insufficient unbroken pre-window history')
    before = segment.iloc[:lo]
    v06.validate_4h_rows(before)
    if (before.timestamp.diff().dropna() != v08.STEP * 1000).any():
        raise ValueError('Calibration crosses a data gap')
    m, _, _, _ = v08.simulate(segment, lo - CALIBRATION_BARS, lo,
                              model, cfg, .2, fee, slip)
    # BTC reference uses trailing 341 actual closed bars only.
    closes = before.close.iloc[-CALIBRATION_BARS:].to_numpy(dtype=float)
    btc_vol = annual_volatility(closes)
    strat_vol = m['annual_volatility']
    if not (math.isfinite(strat_vol) and math.isfinite(btc_vol)) or btc_vol <= 0:
        raise ValueError('Cannot calibrate: zero or invalid historical BTC volatility')
    target = float(np.clip(strat_vol / btc_vol, 0, .2))
    valid = m['trades'] >= MIN_CALIBRATION_TRADES and strat_vol > 0
    return {'weight': target, 'pre_vol_strategy': strat_vol,
            'pre_vol_btc': btc_vol, 'pre_closed_trades': int(m['trades']),
            'calibration_start_ms': int(before.timestamp.iloc[-CALIBRATION_BARS]),
            'calibration_end_exclusive_ms': int(before.timestamp.iloc[-1]) + v08.STEP * 1000,
            'calibration_valid': bool(valid),
            'calibration_note': 'PRE_WINDOW_VOLATILITY_ESTIMATE_ONLY' if valid
                                  else 'LOW_TRADE_COUNT_OR_ZERO_SIGNAL_VOLATILITY'}


def load_verified(source: Path):
    source = Path(source).resolve()
    for file in REQUIRED:
        if not (source / file).is_file():
            raise FileNotFoundError(f'Missing required v0.8.1 artifact: {file}')
    manifest = json.loads((source/'manifest.json').read_text())
    gate = json.loads((source/'release_gate.json').read_text())
    audit = json.loads((source/'data_quality_report.json').read_text())
    if manifest.get('holdout_evaluated') is not False or manifest.get('paper_trading_authorized') is not False:
        raise ValueError('Original holdout or trading flag is not sealed')
    if gate.get('status') != 'RESEARCH_COMPLETE_HOLDOUT_SEALED' or gate.get('passed') is not False or gate.get('paper_trading_authorized') is not False:
        raise ValueError('Expected blocked, pre-holdout research artifact only')
    if audit.get('passed') is not True or not all(audit.get('checks', {}).values()) or not audit.get('checks'):
        raise ValueError('Cross-exchange data-quality validation not passed')
    hashes = manifest.get('artifacts_sha256', {})
    for name in REQUIRED[1:]:
        if hashes.get(name) != sha256(source/name):
            raise ValueError(f'Hash mismatch or missing input fingerprint: {name}')
    # manifest hash is not self-referential, but all crucial input CSVs are.
    history = pd.read_csv(source/'coinbase_btc_eur_4h.csv')
    v06.validate_4h_rows(history)
    windows = pd.read_csv(source/'per_window_results.csv')
    equity = pd.read_csv(source/'equity_windows.csv')
    holdout = require_utc_ms(manifest['holdout_start'])
    return manifest, gate, audit, history, windows, equity, holdout


def investigate(source: Path) -> tuple[pd.DataFrame, dict]:
    manifest, gate, audit, history, windows, equity, holdout = load_verified(source)
    fee, slip = float(manifest['fee_rate_assumption']), float(manifest['slippage_assumption'])
    if not (0 <= fee < .03 and 0 <= slip < .03) or manifest['protocol']['primary_days'] != 90:
        raise ValueError('Unexpected protocol/costs')
    cfg = json.loads((PROJECT/'paper_config.json').read_text())
    v06.verify_unchanged_config(cfg)
    training = history[history.timestamp < holdout].copy()
    # Never pass holdout history to strategy simulation, even as a warmup.
    segments = v06.contiguous_segments(training)
    primary = windows[(windows.days == 90) & (windows.allocation == .2) &
                      (windows.cost_factor == 1) & (windows.parameters == 'baseline')]
    if primary.empty:
        raise ValueError('No primary validation windows')
    if primary.duplicated(subset=['strategy', 'segment', 'start']).any():
        raise ValueError('Duplicate primary validation windows')
    required_curve_cols = {'timestamp', 'equity', 'benchmark', 'exposure', 'strategy', 'window_start'}
    if not required_curve_cols.issubset(equity.columns):
        raise ValueError('Missing required equity-curve columns')
    rows = []
    for w in primary.to_dict('records'):
        model, segment_id = w['strategy'], int(w['segment'])
        if model not in v08.MODELS or not 1 <= segment_id <= len(segments):
            raise ValueError('Unexpected strategy/segment')
        segment = segments[segment_id - 1]
        start, finish = int(w['start']), int(w['end_exclusive'])
        if not start < finish <= holdout:
            raise ValueError('Pre-holdout boundary violation')
        idx = segment.index[segment.timestamp == start].tolist()
        if len(idx) != 1:
            raise ValueError('Window not located inside contiguous pre-holdout segment')
        lo = idx[0]; hi = lo + 90 * 6
        if hi > len(segment) or int(segment.timestamp.iloc[hi-1]) + v08.STEP * 1000 != finish:
            raise ValueError('Window exceeds contiguous segment or has unexpected duration')
        c = equity[(equity.strategy == model) & (equity.window_start == start)].sort_values('timestamp')
        expected_times = segment.timestamp.iloc[lo:hi].to_numpy()
        if len(c) != hi-lo or not np.array_equal(c.timestamp.to_numpy(), expected_times):
            raise ValueError('Curve timestamps do not match verified Coinbase bars')
        strat = c.equity.to_numpy(dtype=float)
        old_passive = c.benchmark.to_numpy(dtype=float)
        exposure = c.exposure.to_numpy(dtype=float)
        if not all(np.isfinite(x).all() for x in (strat, old_passive, exposure)) or (strat <= 0).any() or (old_passive <= 0).any() or ((exposure < 0) | (exposure > 1)).any():
            raise ValueError('Invalid validation equity/exposure')
        if abs(strat[-1]/100-1-float(w['return'])) > 1e-8 or abs(old_passive[-1]/100-1-float(w['benchmark_return'])) > 1e-8:
            raise ValueError('Primary results and equity curves disagree')
        open0 = float(segment.open.iloc[lo])
        closes = segment.close.iloc[lo:hi].to_numpy(dtype=float)
        old_again = static_passive(open0, closes, .2, fee, slip)
        if not np.allclose(old_passive, old_again, rtol=0, atol=1e-8):
            raise ValueError('Original benchmark does not match immutable cost model')
        cal = volatility_calibration(segment, lo, model, cfg, fee, slip)
        fixed = static_passive(open0, closes, cal['weight'], fee, slip)
        # EX-POST matching based on observed validation exposure; purely descriptive.
        post_weight = float(np.mean(exposure))
        post = static_passive(open0, closes, min(.2, post_weight), fee, slip)
        sv, pv = annual_volatility(np.r_[100, strat]), annual_volatility(np.r_[100, fixed])
        key = {'strategy': model, 'segment': segment_id, 'window_start_ms': start,
               'window_end_exclusive_ms': finish, 'duration_days':90,
               'closed_trades': int(w['trades']),
               'strategy_return': float(strat[-1]/100-1),
               'old_20pct_passive_return': float(old_passive[-1]/100-1),
               'strategy_mean_exposure_ex_post': post_weight,
               'strategy_max_exposure_ex_post': float(np.max(exposure)),
               'strategy_annualized_volatility_ex_post': sv,
               'fixed_20pct_benchmark_volatility_ex_post': annual_volatility(np.r_[100, old_passive]),
               'prewindow_vol_weight': cal['weight'],
               'prewindow_vol_passive_return': float(fixed[-1]/100-1),
               'prewindow_vol_passive_volatility_ex_post': pv,
               'prewindow_vol_excess_return_diagnostic': float((strat[-1]-fixed[-1])/100),
               'prewindow_vol_volatility_ratio_ex_post': float(sv/pv) if pv>0 else None,
               'expost_exposure_weight_DIAGNOSTIC_ONLY': min(.2, post_weight),
               'expost_exposure_passive_return_DIAGNOSTIC_ONLY': float(post[-1]/100-1),
               'expost_exposure_excess_return_DIAGNOSTIC_ONLY': float((strat[-1]-post[-1])/100),
               **cal, 'eligible_for_ex_ante_diagnostic': cal['calibration_valid'],
               'strategy_approval': False, 'holdout_evaluated': False}
        rows.append(key)
    result = pd.DataFrame(rows).sort_values(['strategy','window_start_ms']).reset_index(drop=True)
    summary = {'version':'0.8.2-diagnostic', 'source_git_commit':manifest['git_commit'],
               'source_end': manifest['end_exclusive'], 'source_holdout_start':manifest['holdout_start'],
               'source_crosscheck_passed':True, 'primary_windows':len(result),
               'eligible_prewindow_calibrations':int(result.eligible_for_ex_ante_diagnostic.sum()),
               'models': {}, 'release_gate':{'passed':False,'paper_trading_authorized':False,
                           'holdout_evaluated':False,'status':'DIAGNOSTIC_ONLY'},
               'notes':[
                  'Pre-window volatility allocation fixed before each validation period; not guaranteed equal realized risk.',
                  'Calibrations with fewer than 3 preceding closed trades are INCONCLUSIVE, never evidence for superiority.',
                  'Ex-post average-exposure comparator uses validation information and is DIAGNOSTIC ONLY.',
                  'Costs match v0.8 primary baseline; no changes to risk, paper account, strategies or official admission.',
                  '90d validation windows are historical and subject to repeated-research/model-selection bias.',
                  'The final 20% holdout remains sealed and is not modeled or used for calibration.',
               ]}
    for model, group in result.groupby('strategy'):
        eligible = group[group.eligible_for_ex_ante_diagnostic]
        summary['models'][model] = {
             'windows':len(group), 'eligible':len(eligible),
             'mean_exposure_ex_post':float(group.strategy_mean_exposure_ex_post.mean()),
             'old_20pct_benchmark_mean_return':float(group.old_20pct_passive_return.mean()),
             'strategy_mean_return':float(group.strategy_return.mean()),
             'prewindow_calibrated_mean_return_eligible':float(eligible.prewindow_vol_passive_return.mean()) if len(eligible) else None,
             'positive_excess_vs_precalibrated_eligible':int((eligible.prewindow_vol_excess_return_diagnostic>0).sum()),
             'realized_vol_ratio_median_eligible':float(eligible.prewindow_vol_volatility_ratio_ex_post.dropna().median()) if eligible.prewindow_vol_volatility_ratio_ex_post.notna().any() else None,
        }
    return result, summary


def create_report(frame: pd.DataFrame, summary: dict) -> str:
    lines = ['# Atlas Trading AI v0.8.2 – Causal calibration & exposure diagnostics', '',
             '**RESEARCH ONLY. No strategy admitted; final holdout sealed.**', '',
             f"Base dataset through {summary['source_end']}; holdout starts {summary['source_holdout_start']}.",
             f"Primary windows: {summary['primary_windows']}; usable pre-window volatility calibrations: {summary['eligible_prewindow_calibrations']}.", '',
             'This update compares the fixed 20% passive benchmark against a *pre-window volatility-calibrated* passive buy-and-hold control. Its weight is determined solely from 341 pre-validation 4h candles, capped at 20%. This offers an ex-ante calibration, **not equal realized risk**. Sparse-calibration windows remain inconclusive.', '',
             '| Strategy | Windows | Eligible calibrations | Mean real exposure | Mean strategy return | Mean original 20% passive return |',
             '|---|---:|---:|---:|---:|---:|']
    for name, stats in summary['models'].items():
        lines.append(f"| {name} | {stats['windows']} | {stats['eligible']} | {stats['mean_exposure_ex_post']:.2%} | {stats['strategy_mean_return']:.2%} | {stats['old_20pct_benchmark_mean_return']:.2%} |")
    lines += ['', 'The ex-post exposure-matched comparator uses observed validation exposure and MUST NOT be interpreted as out-of-sample alpha.',
              'The bootstrap/significance/release-gate logic is unchanged. Positive values are exploratory, not a trading certificate.', '',
              '## Diagnostics limitations', '']
    lines += ['- '+note for note in summary['notes']]
    return '\n'.join(lines)+'\n'


def plot_diagnostics(df: pd.DataFrame, output: Path):
    """Descriptive graphics only: window returns and actual exposure (not alpha)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for model, group in df.groupby('strategy'):
        g = group.sort_values('window_start_ms')
        starts = pd.to_datetime(g.window_start_ms, unit='ms', utc=True).dt.strftime('%Y-%m')
        fig, ax = plt.subplots(figsize=(10, 4.5))
        x = np.arange(len(g),dtype=float)
        ax.plot(x,g.strategy_return * 100,marker='o',label='Strategy (realized)')
        ax.plot(x,g.old_20pct_passive_return*100,marker='s',label='20% passive')
        # Uses only PRE-window calibration; flagged invalid calibrations show holes.
        good = g.eligible_for_ex_ante_diagnostic.to_numpy(dtype=bool)
        y = g.prewindow_vol_passive_return.to_numpy(dtype=float)*100
        y[~good] = np.nan
        ax.plot(x,y,marker='^',label='Prewindow-vol passive (eligible only)')
        ax.axhline(0,linewidth=.7,linestyle='--')
        ax.set_xticks(x,starts,rotation=45,ha='right')
        ax.set(ylabel='90d net return (% of 100 EUR account)',
               title=f'{model} – separate validation windows; NO strategy approval')
        ax.legend(loc='best',fontsize=8)
        fig.tight_layout()
        fig.savefig(output/('v082_sma_benchmarks.png' if model=='SMA 20/50' else 'v082_ema_benchmarks.png'),dpi=140)
        plt.close(fig)


def run(source: Path, output: Path) -> dict:
    output = v05.safe_output_dir(Path(output), project=PROJECT)
    source = Path(source).resolve()
    if output == source or output in source.parents or source in output.parents or output.exists():
        raise ValueError('Separate, previously nonexistent output directory required')
    before = v05.protected_hashes(PROJECT)
    # Verify ALL inputs and compute before creating an output directory.
    df, summary = investigate(source)
    if before != v05.protected_hashes(PROJECT):
        raise ValueError('Protected account changed during diagnostics')
    output.mkdir(parents=True, exist_ok=False)
    df.to_csv(output/'prewindow_benchmark_windows.csv', index=False)
    (output/'diagnostics.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    (output/'SUMMARY_V082_DE.md').write_text(create_report(df,summary))
    plot_diagnostics(df, output)
    artifact_hashes = {p.name:sha256(p) for p in output.iterdir() if p.is_file()}
    (output/'SHA256SUMS.json').write_text(json.dumps(artifact_hashes, indent=2)+'\n')
    if before != v05.protected_hashes(PROJECT):
        raise ValueError('Protected account changed during report writing')
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True, help='Unzipped v0.8.1 atlas-v08-research folder')
    p.add_argument('--output', type=Path, default=Path('atlas-v082-diagnostics'))
    args = p.parse_args()
    result = run(args.input, args.output)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
