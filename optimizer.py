"""Small, explicit parameter sweeps with expanding-window walk-forward scoring."""
from __future__ import annotations
from itertools import product
import pandas as pd
from .backtest import backtest
from .strategies import STRATEGIES


def candidates(strategy):
    if strategy == "EMA Trend":
        return [{"ema_fast": f, "ema_slow": s, "ema_trend": t}
                for f,s,t in product((10,20,30),(40,50),(100,200)) if f < s < t]
    if strategy == "RSI Reversion":
        return [{"rsi_entry": e, "rsi_exit": x, "ema_trend": t}
                for e,x,t in product((25,30,35),(50,55,60),(100,200)) if e < x]
    if strategy == "Breakout":
        return [{"lookback": n, "volume_factor": v}
                for n,v in product((15,20,30),(0.8,1.0,1.2))]
    raise ValueError(f"Unbekannte Strategie: {strategy}")


def run_walk_forward(df, strategy, initial_cash=1000.0, fee_rate=0.001,
                     slippage=0.0005, timeframe="15m", folds=4, min_train_trades=8):
    """Tune each fold only on its earlier training slice, then score the next slice.

    The selected configuration for a fold is never evaluated on the same rows
    used to rank it. This is a research diagnostic, not a guarantee of edge.
    """
    if strategy not in STRATEGIES or not 2 <= folds <= 6:
        raise ValueError("Strategie unbekannt oder Fold-Anzahl außerhalb 2–6")
    n=len(df)
    if n < 600:
        raise ValueError("Walk-forward benötigt mindestens 600 Kerzen für Warm-up und getrennte Zeitfenster")
    test_size=max(100,n//(2*folds))
    configs=candidates(strategy); reports=[]
    for fold in range(folds):
        train_end=n-test_size*(folds-fold)
        test_end=min(train_end+test_size,n)
        ranked=[]
        for params in configs:
            m,_,_,_=backtest(df,strategy,initial_cash,fee_rate,slippage,
                              start_index=0,end_index=train_end,timeframe=timeframe,
                              strategy_params=params)
            if m["trades"] < min_train_trades:
                score=float("-inf")
            else:
                score=m["return_pct"]-max(0,abs(m["max_drawdown_pct"])-10)*0.25
            ranked.append((score,params,m))
        score,params,train_metrics=max(ranked,key=lambda item:item[0])
        if score == float("-inf"):
            reports.append({"fold":fold+1,"status":"Keine Konfiguration erreichte die Mindestzahl an Trainingstrades",
                            "train_start":int(df.timestamp.iloc[0]),"train_end":int(df.timestamp.iloc[train_end-1]),
                            "test_start":int(df.timestamp.iloc[train_end]),"test_end":int(df.timestamp.iloc[test_end-1]),
                            "params":None,"train_trades":train_metrics["trades"],"test_trades":0,
                            "test_return_pct":0.0,"test_drawdown_pct":0.0})
            continue
        test_metrics,_,_,_=backtest(df,strategy,initial_cash,fee_rate,slippage,
                                    start_index=train_end,end_index=test_end,timeframe=timeframe,
                                    strategy_params=params)
        reports.append({"fold":fold+1,"status":"Ausgewertet",
                        "train_start":int(df.timestamp.iloc[0]),"train_end":int(df.timestamp.iloc[train_end-1]),
                        "test_start":int(df.timestamp.iloc[train_end]),"test_end":int(df.timestamp.iloc[test_end-1]),
                        "params":params,"train_trades":train_metrics["trades"],
                        "test_trades":test_metrics["trades"],"test_return_pct":test_metrics["return_pct"],
                        "test_drawdown_pct":test_metrics["max_drawdown_pct"]})
    valid=[r for r in reports if r["status"]=="Ausgewertet"]
    summary={"strategy":strategy,"folds_requested":folds,"folds_evaluated":len(valid),
             "mean_oos_return_pct":sum(r["test_return_pct"] for r in valid)/len(valid) if valid else None,
             "worst_oos_drawdown_pct":min((r["test_drawdown_pct"] for r in valid),default=None),
             "total_oos_trades":sum(r["test_trades"] for r in valid),
             "selection_rule":"Trainingrendite nach Kosten minus Drawdown-Strafe; nur Trainingdaten je Fold",
             "fold_results":reports}
    return summary
