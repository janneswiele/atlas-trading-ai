# Atlas Trading AI v1.0 — isolated research and read-only monitoring

This package adds **no real trading** and never changes any `atlas09/`, v0.9 source, `main`, `paper_state.json`, or the `atlas-v0.9-data` ledger.

- `policy.py`: frozen risk assumptions and SHA-bound dataset approval; observed research samples after 2026-10-01 are blocked, as is any unapproved / incomplete dataset.
- `signals.py`: 30 pre-registered deterministic SMA, EMA, momentum, Donchian and ATR candidates; causal end-of-bar signals.
- `backtest.py`: next-bar-open, spot-only, cost-adjusted research simulation with frozen 20% allocation and drawdown/daily-loss halts.
- `research.py`: two or more walk-forward folds; 480-bar training context includes 205 warm-up bars; **selection by training-only**; out-of-sample diagnostics are not used to pick the winner in the same fold. Research results NEVER grant a trading permission.
- `monitor.py`: read-only SHA256 event-chain and ledger-seal verification of the existing v0.9 data branch, separately from its immutable code hash.
- `dashboard.py`: responsive Streamlit research monitoring UI; no mutation or trading controls. Hosting is not yet provisioned.
- `proposals.py`: deterministic research suggestions for human review. No code writes, API tokens or paid AI calls.

**Existing v0.9 forward simulator** remains the only execution implementation; it is activated but has not yet completed an eligible forward cycle. The scheduler for recurring runs is staged under `STAGED_ONLY/`, not installed on `main`, pending the owner's explicit approval.

## Commands

```bash
python -m pytest -q test_atlas_v10.py
python atlas_v10.py research --csv examples/atlas10/SYNTHETIC_4h.csv --approval examples/atlas10/SYNTHETIC_4h.approval.json --out atlas-v10-results
python atlas_v10.py propose --report atlas-v10-results/research.json --out atlas-v10-results
python atlas_v10.py status --ledger <local v0.9 ledger.json>
streamlit run atlas10/dashboard.py
```

The supplied synthetic dataset is **only for code verification**, not real financial results. To research actual historical data, obtain a separately approved training-only OHLCV CSV and SHA256 approval manifest. Sealed holdout samples must not be repurposed. No real exchange trading API or secret is required.
