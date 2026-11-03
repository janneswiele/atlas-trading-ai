"""Atlas v0.8 research stage: full-history audit and sealed-holdout diagnostics.

No production writes, strategy admission, final holdout evaluation, or SPA claim.
Extends v0.6 validation and existing strategy signals; not a trading engine.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import platform
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

import numpy as np
import pandas as pd
import atlas_v05 as v05
import atlas_v06 as v06
from strategies import generate_signals

PROJECT = Path(__file__).resolve().parent
STEP = 14_400
MODELS = ('SMA 20/50', 'EMA Trend')
NEIGHBORS = ((18, 45), (18, 55), (22, 45), (22, 55))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    v06._atomic_text(Path(path), json.dumps(value, indent=2, allow_nan=False) + '\n')


def endpoint(end=None):
    if end is None:
        return int(time.time()) // STEP * STEP
    value = pd.Timestamp(end)
    if value.tzinfo is None:
        raise ValueError('--end requires a timezone')
    seconds = value.timestamp()
    if seconds != int(seconds) or int(seconds) % STEP or seconds > time.time():
        raise ValueError('--end must be a past, closed UTC 4h boundary')
    return int(seconds)


def get_raw(url, path, opener=urlopen):
    """Archive the exact response body before interpreting it; bounded retries."""
    for attempt in range(3):
        try:
            with opener(Request(url, headers={'User-Agent': 'AtlasResearch/0.8'}), timeout=30) as response:
                body = response.read()
            path.write_bytes(body)
            save_json(path.with_suffix('.meta.json'), {'url': url, 'retrieved_at': v06.iso(int(time.time())),
                                                     'sha256': digest(path)})
            return json.loads(body)
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def coinbase_history(start, end, raw, fetch=get_raw):
    """Use native 1h candles; only four complete native hours make a 4h bar."""
    rows = []
    for left in range(start, end, 250 * 3600):
        right = min(end, left + 250 * 3600)
        url = ('https://api.exchange.coinbase.com/products/BTC-EUR/candles'
               f'?granularity=3600&start={v06.iso(left)}&end={v06.iso(right)}')
        payload = fetch(url, raw / f'coinbase-{left}.json')
        if not isinstance(payload, list):
            raise ValueError('Invalid Coinbase response')
        seen = set()
        for item in payload:
            if not isinstance(item, list) or len(item) != 6:
                raise ValueError('Invalid Coinbase candle')
            ts, low, high, op, close, volume = item
            if not isinstance(ts, (int, float)) or not math.isfinite(ts) or int(ts) != ts:
                raise ValueError('Invalid Coinbase timestamp')
            if not left <= ts < right:
                continue
            if ts in seen:
                raise ValueError('Duplicate Coinbase candle')
            seen.add(ts)
            rows.append((ts, op, high, low, close, volume))
        time.sleep(.12)
    frame, gaps = v06.aggregate_verified_4h(pd.DataFrame(rows, columns=v06.COLUMNS), start, end)
    return frame, gaps


def kraken_archive(path, start, end):
    """Official BTC/EUR 240-minute CSV: epoch seconds,O,H,L,C,V,trades, no header.

    The operator must supply the BTC/EUR file, not another market's archive.
    Content hashes preserve identity, not authenticate the market/source.
    """
    frame = pd.read_csv(path, header=None, names=[*v06.COLUMNS, 'trades'])
    frame.timestamp = pd.to_numeric(frame.timestamp, errors='raise') * 1000
    frame = frame[(frame.timestamp >= start * 1000) & (frame.timestamp < end * 1000)]
    frame = frame[v06.COLUMNS].reset_index(drop=True)
    v06.validate_4h_rows(frame, end)
    return frame


def crosscheck(coinbase, kraken, start, end):
    """Coverage denominator is the REQUESTED grid, never the available subset."""
    if start % STEP or end % STEP or start >= end:
        raise ValueError('Invalid audit bounds')
    for frame in (coinbase, kraken):
        v06.validate_4h_rows(frame, end)
        if (frame.timestamp < start * 1000).any():
            raise ValueError('Source outside requested grid')
    grid = pd.DataFrame({'timestamp': np.arange(start, end, STEP, dtype=np.int64) * 1000})
    merged = grid.merge(coinbase, on='timestamp', how='left').merge(
        kraken, on='timestamp', how='left', suffixes=('_coinbase', '_kraken'))
    matched = merged.close_coinbase.notna() & merged.close_kraken.notna()
    for field in ('open', 'high', 'low', 'close'):
        a, b = merged[field + '_coinbase'], merged[field + '_kraken']
        merged[field + '_difference'] = 2 * (a-b).abs() / (a+b)
    diff = merged.loc[matched, 'close_difference']
    # Grid rows remain present: diff cannot bridge missing bars.
    a, b = np.log(merged.close_coinbase).diff(), np.log(merged.close_kraken).diff()
    corr = a.corr(b)
    result = {'expected_bars': len(grid), 'aligned_bars': int(matched.sum()),
              'coverage': float(matched.mean()), 'median_close_difference': float(diff.median()) if len(diff) else None,
              'p99_close_difference': float(diff.quantile(.99)) if len(diff) else None,
              'outlier_fraction': float((diff > .015).mean()) if len(diff) else None,
              'return_correlation': float(corr) if np.isfinite(corr) else None}
    checks = {'coverage': result['coverage'] >= .995,
              'median': len(diff) > 0 and result['median_close_difference'] <= .0025,
              'p99': len(diff) > 0 and result['p99_close_difference'] <= .01,
              'outliers': len(diff) > 0 and result['outlier_fraction'] <= .001,
              'correlation': np.isfinite(corr) and corr >= .995}
    result.update(checks={k: bool(v) for k,v in checks.items()}, passed=bool(all(checks.values())))
    anomalies = merged[~matched | (merged.close_difference > .015)].copy()
    return result, merged, anomalies


def stationary_bootstrap(values, repetitions=10000, block=42, seed=804):
    """Diagnostic percentile CI of mean paired excess return; centered one-sided null.

    Not SPA. Bootstrap assumes weak stationarity and is no release certificate.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x) < 3 or not np.isfinite(x).all() or repetitions < 100 or block < 1:
        raise ValueError('Invalid bootstrap input')
    rng = np.random.default_rng(seed)
    means = np.empty(repetitions)
    for lo in range(0, repetitions, 128):
        size = min(128, repetitions - lo)
        indices = rng.integers(0, len(x), size=size)
        total = x[indices].copy()
        for _ in range(1, len(x)):
            restart = rng.random(size) < 1 / block
            indices = np.where(restart, rng.integers(0, len(x), size=size), (indices + 1) % len(x))
            total += x[indices]
        means[lo:lo+size] = total / len(x)
    mean = float(x.mean())
    return {'mean_excess_return': mean, 'ci_low': float(np.quantile(means, .025)),
            'ci_high': float(np.quantile(means, .975)),
            'p_one_sided': float((1 + np.count_nonzero(means - mean >= mean)) / (repetitions + 1)),
            'block_bars': block, 'repetitions': repetitions, 'seed': seed}


def holm(pvalues):
    p = np.asarray(pvalues, dtype=float)
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError('Invalid p-values')
    order = np.argsort(p); adjusted = np.empty(len(p)); previous = 0.
    for rank, index in enumerate(order):
        previous = max(previous, min(1., (len(p)-rank) * p[index]))
        adjusted[index] = previous
    return adjusted.tolist()


def signals(frame, model, pair=None):
    if model not in MODELS:
        raise ValueError('Unregistered strategy')
    if pair is None:
        enter, leave, _, _ = generate_signals(frame, model)
        return enter.to_numpy(), leave.to_numpy()
    fast, slow = pair
    if model == 'EMA Trend':
        enter, leave, _, _ = generate_signals(frame, model, {'ema_fast': fast, 'ema_slow': slow})
    else:
        f, s = frame.close.rolling(fast).mean(), frame.close.rolling(slow).mean()
        enter = (f > s) & (f.shift() <= s.shift())
        leave = (f < s) & (f.shift() >= s.shift())
    return enter.fillna(False).to_numpy(), leave.fillna(False).to_numpy()


def simulate(frame, lo, hi, model, cfg, allocation=.2, fee=.006, slip=.0005, pair=None):
    """v0.7 sampled-open risk model; no forced terminal trades or intrabar fills."""
    v06.verify_unchanged_config(cfg)
    if not 200 <= lo < hi <= len(frame) or allocation not in (.1, .2, .5):
        raise ValueError('Invalid simulation bounds/allocation')
    if not all(math.isfinite(x) and 0 <= x < .1 for x in (fee, slip)):
        raise ValueError('Invalid costs')
    data = frame.iloc[:hi].reset_index(drop=True)
    v06.validate_4h_rows(data)
    if (data.timestamp.diff().dropna() != STEP * 1000).any():
        raise ValueError('Simulation cannot cross a gap')
    enter, leave = signals(data, model, pair)
    cash, qty, cost, entry, peak = 100., 0., 0., 0., 100.
    halted = False; day = None; day_value = 100.; trades = []; curve = []; fees = 0.; turnover = 0.
    start_open = float(data.open.iloc[lo])
    bqty = 100 * allocation / (start_open * (1+slip) * (1+fee))
    for i in range(lo, hi):
        row = data.iloc[i]; price = float(row.open); value = cash + qty * price
        peak = max(peak, value)
        if int(row.timestamp) // 86400000 != day:
            day, day_value = int(row.timestamp) // 86400000, value
        daily = value <= day_value * (1-cfg['daily_loss_limit'])
        halted = halted or value <= peak * (1-cfg['max_drawdown'])
        if qty and (leave[i-1] or price <= entry*(1-cfg['stop_loss']) or price >= entry*(1+cfg['take_profit']) or halted or daily):
            gross = qty * price * (1-slip); proceeds = gross*(1-fee)
            fees += gross*fee; turnover += gross
            trades.append({'entry_time': entry_time, 'exit_time': int(row.timestamp), 'net_pnl': proceeds-cost})
            cash += proceeds; qty = 0.
        elif not qty and i > lo and enter[i-1] and not halted and not daily and cash >= 10:
            cost = cash*allocation; entry = price*(1+slip)
            qty = cost/(entry*(1+fee)); cash -= cost
            fees += cost*fee/(1+fee); turnover += cost/(1+fee); entry_time = int(row.timestamp)
        marked = cash + qty*float(row.close)*(1-slip)*(1-fee)
        curve.append({'timestamp': int(row.timestamp), 'equity': marked,
                      'benchmark': 100*(1-allocation) + bqty*float(row.close)*(1-slip)*(1-fee),
                      'exposure': qty*float(row.close)/marked})
    curve = pd.DataFrame(curve)
    rets = np.diff(np.log(np.r_[100., curve.equity]))
    simple = np.diff(np.r_[100., curve.equity]) / np.r_[100., curve.equity.to_numpy()[:-1]]
    brets = np.diff(np.r_[100., curve.benchmark]) / np.r_[100., curve.benchmark.to_numpy()[:-1]]
    centered = rets - rets.mean(); n = len(rets); lag = min(42, n-1)
    variance = float(centered @ centered / n)
    hac = variance + 2*sum((1-k/(lag+1)) * float(centered[k:] @ centered[:-k])/n for k in range(1, lag+1))
    pnl = np.array([t['net_pnl'] for t in trades]); gains = pnl[pnl>0].sum(); losses = -pnl[pnl<0].sum()
    dd = lambda values: float(np.min(values / np.maximum.accumulate(values)-1))
    m = {'return': float(curve.equity.iloc[-1]/100-1), 'benchmark_return': float(curve.benchmark.iloc[-1]/100-1),
         'alpha': float((curve.equity.iloc[-1]-curve.benchmark.iloc[-1])/100),
         'max_drawdown': dd(np.r_[100., curve.equity]), 'benchmark_drawdown': dd(np.r_[100., curve.benchmark]),
         'trades': len(trades), 'win_rate': float((pnl>0).mean()) if len(pnl) else None,
         'profit_factor': float(gains/losses) if losses else None,
         'profit_factor_no_losses': bool(not losses and gains > 0),
         'annual_volatility': float(np.sqrt(variance*2190)),
         'hac_sharpe': float(rets.mean()*np.sqrt(2190/hac)) if hac > 0 else None,
         'exposure': float(curve.exposure.mean()), 'turnover': turnover/100,
         'paid_fees': fees, 'open_at_end': bool(qty), 'halted': bool(halted)}
    return m, curve, trades, simple-brets


def research(frame, cfg, fee, slip, repetitions):
    """Global calendar holdout boundary, never recalculated per continuous segment."""
    boundary = int(frame.attrs['holdout_start'])
    rows, trades, curves, boot = [], [], [], []
    for segment_id, segment in enumerate(v06.contiguous_segments(frame[frame.timestamp < boundary]), 1):
        for days in (60, 90, 180):
            width = days*6
            for lo in range(541, len(segment)-width+1, width):
                hi = lo+width
                trailing = float(segment.close.iloc[lo-1]/segment.close.iloc[lo-541]-1)
                for model in MODELS:
                    for allocation in (.1, .2, .5):
                        for factor in (1, 2, 3):
                            m, curve, ts, excess = simulate(segment, lo, hi, model, cfg, allocation, fee*factor, slip*factor)
                            key = {'strategy': model, 'segment': segment_id, 'days': days, 'start': int(segment.timestamp.iloc[lo]),
                                   'end_exclusive': int(segment.timestamp.iloc[hi-1])+STEP*1000,
                                   'allocation': allocation, 'cost_factor': factor, 'parameters': 'baseline',
                                   'regime': 'bull' if trailing>.1 else 'bear' if trailing<-.1 else 'sideways'}
                            rows.append({**key, **m})
                            if days == 90 and allocation == .2 and factor == 1:
                                trades.extend({**key, **t} for t in ts)
                                curves.append(curve.assign(strategy=model, window_start=key['start']))
                                for block in (18, 42, 84):
                                    boot.append({**key, **stationary_bootstrap(excess, repetitions, block)})
                                for pair in NEIGHBORS:
                                    for stress in (1,2,3):
                                        pm, _, _, _ = simulate(segment, lo, hi, model, cfg, .2, fee*stress, slip*stress, pair)
                                        rows.append({**key, 'parameters': f'{pair[0]}/{pair[1]}', 'cost_factor': stress, **pm})
    if boot:
        for result, corrected in zip(boot, holm([b['p_one_sided'] for b in boot])):
            result['holm_p_all_reported_bootstrap_tests'] = corrected
    return pd.DataFrame(rows), pd.DataFrame(trades), pd.concat(curves, ignore_index=True) if curves else pd.DataFrame(), pd.DataFrame(boot)


def run(output, *, days=1095, end=None, coinbase_csv=None, kraken_csv=None, fee=.006, slip=.0005, repetitions=10000):
    if not 730 <= days <= 1095 or repetitions < 100:
        raise ValueError('Require 730..1095 days and at least 100 bootstrap replicates')
    if not all(math.isfinite(x) and 0 <= x < .03 for x in (fee, slip)):
        raise ValueError('Costs must be finite and remain below 10% at 3x stress')
    end = endpoint(end); start = end-days*86400
    output = v05.safe_output_dir(Path(output), project=PROJECT)
    # Never overwrite another research run or any existing directory.
    output.mkdir(parents=True, exist_ok=False); raw = output/'raw'; raw.mkdir()
    before = v05.protected_hashes(PROJECT)
    cfg = json.loads((PROJECT/'paper_config.json').read_text()); v06.verify_unchanged_config(cfg)
    manifest = {'version': '0.8.0-research', 'start': v06.iso(start), 'end_exclusive': v06.iso(end),
                'holdout_start': v06.iso(start+(days*6*4//5)*STEP), 'python': platform.python_version(),
                'fee_rate_assumption': fee, 'slippage_assumption': slip, 'bootstrap_repetitions': repetitions,
                'risk_config': cfg, 'risk_sha256': digest(PROJECT/'paper_config.json'),
                'source_hashes': {p.name: digest(p) for p in PROJECT.glob('*.py')},
                'requirements_sha256': digest(PROJECT/'requirements-v08.txt'),
                'git_commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=PROJECT, text=True).strip(),
                'protocol': {'models': list(MODELS), 'neighbors': list(NEIGHBORS),
                             'window_days': [60,90,180], 'primary_days': 90,
                             'allocations': [.1,.2,.5], 'primary_allocation': .2,
                             'cost_factors': [1,2,3], 'bootstrap_blocks': [18,42,84], 'seed':804,
                             'regime_lookback_bars':540, 'regime_threshold':.1,
                             'holdout_fraction':.2, 'multiple_test':'Holm, diagnostic only'},
                'holdout_evaluated': False, 'paper_trading_authorized': False,
                'cost_note': 'Explicit research model; verify venue/account tier before final preregistration.'}
    (output/'environment-freeze.txt').write_text(subprocess.check_output([__import__('sys').executable,'-m','pip','freeze'],text=True))
    save_json(output/'manifest.json', manifest)
    gate = {'passed': False, 'paper_trading_authorized': False, 'status': 'BLOCKED',
            'reasons': ['Final holdout remains sealed; final release evaluation is not implemented in this research stage.']}
    try:
        if coinbase_csv:
            (raw/'coinbase-input.csv').write_bytes(Path(coinbase_csv).read_bytes())
            cb = pd.read_csv(raw/'coinbase-input.csv')
            cb = cb[(cb.timestamp >= start*1000)&(cb.timestamp < end*1000)].reset_index(drop=True)
        else:
            cb, gaps = coinbase_history(start,end,raw)
            save_json(output/'coinbase_gaps.json', gaps)
        v06.validate_4h_rows(cb, end)
        cb.to_csv(output/'coinbase_btc_eur_4h.csv', index=False)
        if not kraken_csv:
            raise ValueError('Full BTC/EUR Kraken 240m archive required; recent REST data cannot verify 1095 days')
        (raw/'kraken-input.csv').write_bytes(Path(kraken_csv).read_bytes())
        kr = kraken_archive(raw/'kraken-input.csv',start,end)
        kr.to_csv(output/'kraken_btc_eur_4h.csv', index=False)
        audit, aligned, anomalies = crosscheck(cb,kr,start,end)
        save_json(output/'data_quality_report.json',audit)
        aligned.to_csv(output/'aligned_crosscheck.csv',index=False)
        anomalies.to_csv(output/'data_quality_anomalies.csv',index=False)
        if not audit['passed']:
            raise ValueError('Full-history cross-exchange quality gate failed')
        cb.attrs['holdout_start'] = (start+(days*6*4//5)*STEP)*1000
        results, trades, curves, boot = research(cb,cfg,fee,slip,repetitions)
        for name, frame in [('per_window_results',results),('trades',trades),('equity_windows',curves),('bootstrap_results',boot)]:
            frame.to_csv(output/(name+'.csv'),index=False)
        gate['status'] = 'RESEARCH_COMPLETE_HOLDOUT_SEALED'
        gate['research_rows'] = len(results)
        if results.empty:
            raise ValueError('No complete research windows after gaps and warmup')
        results[results.parameters != 'baseline'].to_csv(output/'parameter_sensitivity.csv',index=False)
        results[results.parameters == 'baseline'].to_csv(output/'cost_sensitivity.csv',index=False)
        primary = results[(results.days==90)&(results.allocation==.2)&(results.cost_factor==1)&(results.parameters=='baseline')]
        primary.groupby(['strategy','regime']).agg(windows=('alpha','size'),mean_alpha=('alpha','mean'),trades=('trades','sum')).to_csv(output/'regime_results.csv')
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        for model in MODELS:
            fig, ax = plt.subplots()
            for _, window in curves[curves.strategy==model].groupby('window_start'):
                dates = pd.to_datetime(window.timestamp,unit='ms',utc=True)
                ax.plot(dates,window.equity,color='navy'); ax.plot(dates,window.benchmark,color='gray')
            ax.set(title=f'{model}: separate 90d windows (reset EUR100)', ylabel='EUR; navy=strategy, gray=passive')
            fig.autofmt_xdate(); fig.savefig(output/('equity_sma.png' if model==MODELS[0] else 'equity_ema.png')); plt.close(fig)
    except Exception as exc:
        gate['status'] = 'BLOCKED'; gate['reasons'].append(f'{type(exc).__name__}: {exc}')
    finally:
        if before != v05.protected_hashes(PROJECT):
            gate['status'] = 'BLOCKED'; gate['reasons'].append('Production integrity mismatch')
        manifest['artifacts_sha256'] = {str(p.relative_to(output)): digest(p) for p in output.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        save_json(output/'release_gate.json',gate)
        (output/'atlas_v08_report.md').write_text('# Atlas v0.8 research\n\n'+gate['status']+'\n\n'+ '\n'.join('- '+r for r in gate['reasons'])+'\n\nNo strategy approval. No final-holdout results. Holm correction is not SPA.\n')
        manifest['artifacts_sha256'].update({n: digest(output/n) for n in ('release_gate.json','atlas_v08_report.md')})
        save_json(output/'manifest.json',manifest)
    return gate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--days',type=int,default=1095); p.add_argument('--end')
    p.add_argument('--output',type=Path,default=Path('atlas-research-output'))
    p.add_argument('--coinbase-csv',type=Path); p.add_argument('--kraken-csv',type=Path)
    p.add_argument('--fee-rate',type=float,default=.006); p.add_argument('--slippage',type=float,default=.0005)
    p.add_argument('--bootstrap',type=int,default=10000)
    a = p.parse_args()
    result = run(a.output,days=a.days,end=a.end,coinbase_csv=a.coinbase_csv,kraken_csv=a.kraken_csv,
                 fee=a.fee_rate,slip=a.slippage,repetitions=a.bootstrap)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='RESEARCH_COMPLETE_HOLDOUT_SEALED' else 2

if __name__ == '__main__':
    raise SystemExit(main())
