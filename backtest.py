"""Conservative, reproducible, long-only spot backtester."""
from __future__ import annotations
import math
import pandas as pd
from strategies import generate_signals


def backtest(df, strategy, initial_cash=1000.0, fee_rate=0.001, slippage=0.0005,
             risk_fraction=0.005, max_allocation=0.20, stop_atr=2.0, take_atr=4.0,
             start_index=0, end_index=None, timeframe="15m", strategy_params=None):
    if not all(math.isfinite(v) for v in (initial_cash, fee_rate, slippage, risk_fraction, max_allocation, stop_atr, take_atr)) or initial_cash <= 0 or not 0 <= fee_rate < .1 or not 0 <= slippage < .1:
        raise ValueError("Ungültige Kapital-, Gebühren- oder Slippage-Einstellung")
    if not 0 < risk_fraction <= .20 or not 0 < max_allocation <= .20 or min(stop_atr, take_atr) <= 0:
        raise ValueError("Ungültige Risikoparameter")
    end_index = len(df) if end_index is None else int(end_index)
    if not 0 <= int(start_index) < end_index <= len(df):
        raise ValueError("Ungültige Testgrenzen")
    entries, exits, x, entry_reason = generate_signals(df, strategy, strategy_params)
    cash = float(initial_cash); qty = 0.0; entry_fee = 0.0; entry_value = 0.0
    entry_fill = stop = take = 0.0; entry_time = None; entry_signal_time = None
    trades, equity, diagnostics = [], [], {"candles_evaluated": 0, "entry_conditions": int(entries.iloc[int(start_index):end_index].sum()), "exit_conditions": int(exits.iloc[int(start_index):end_index].sum()), "risk_rejections": 0, "stop_hits": 0, "take_hits": 0}
    for i in range(int(start_index), end_index):
        bar = df.iloc[i]; diagnostics["candles_evaluated"] += 1
        o,h,l,c = map(float, (bar.open,bar.high,bar.low,bar.close))
        exited_this_bar = False
        if not all(math.isfinite(v) for v in (o,h,l,c)) or min(o,h,l,c) <= 0 or h < max(o,l,c) or l > min(o,c):
            raise ValueError(f"Ungültiger OHLC-Wert in Zeile {i}")
        # Position exits at the next bar open when a close-based exit was known.
        if qty > 0 and i > 0 and bool(exits.iloc[i-1]):
            fill = o * (1-slippage); gross = qty * fill; fee = gross*fee_rate; pnl = gross-fee-entry_value-entry_fee
            cash += gross-fee
            trades.append(_trade(strategy, df, entry_signal_time, entry_time, i, entry_fill, fill, qty, entry_value, entry_fee, fee, pnl, "Strategie-Ausgang", entry_reason))
            qty=entry_fee=entry_value=0.0
            exited_this_bar = True
        # Signal at prior close, fill no earlier than this bar's open.
        if qty == 0 and not exited_this_bar and i > int(start_index) and bool(entries.iloc[i-1]):
            atr=float(x.atr.iloc[i-1]) if pd.notna(x.atr.iloc[i-1]) else 0
            fill=o*(1+slippage); stop_distance=max(atr*stop_atr, fill*.01)
            planned_risk=cash*risk_fraction; risk_qty=planned_risk/stop_distance
            cap_qty=cash*max_allocation/(fill*(1+fee_rate)); qty=min(risk_qty,cap_qty)
            cost=qty*fill; fee=cost*fee_rate; total=cost+fee
            if not math.isfinite(qty) or qty <= 0 or total > cash:
                diagnostics["risk_rejections"]+=1; qty=0
            else:
                cash-=total; entry_fill=fill; entry_value=cost; entry_fee=fee; stop=fill-stop_distance; take=fill+atr*take_atr if atr>0 else fill+2*stop_distance
                entry_time=bar.timestamp; entry_signal_time=df.iloc[i-1].timestamp
        # Stop/take are active on every bar after entry. If both hit, stop wins.
        if qty > 0:
            exit_price = reason = None
            if l <= stop and h >= take:
                exit_price,reason=(o if o <= stop else stop),"Stop-Loss (Stop und Take in derselben Kerze; konservativ)"
            elif o <= stop: exit_price,reason=o,"Stop-Loss-Kurslücke"
            elif o >= take: exit_price,reason=take,"Take-Profit (konservativ bei Kurslücke)"
            elif l <= stop: exit_price,reason=stop,"Stop-Loss"
            elif h >= take: exit_price,reason=take,"Take-Profit"
            if exit_price is not None:
                fill=exit_price*(1-slippage); gross=qty*fill; fee=gross*fee_rate; pnl=gross-fee-entry_value-entry_fee; cash += gross-fee
                diagnostics["stop_hits" if "Stop" in reason else "take_hits"] += 1
                trades.append(_trade(strategy,df,entry_signal_time,entry_time,i,entry_fill,fill,qty,entry_value,entry_fee,fee,pnl,reason,entry_reason))
                qty=entry_fee=entry_value=0.0
        marked=cash+(qty*c*(1-fee_rate-slippage) if qty else 0)
        equity.append({"timestamp":bar.timestamp,"equity":marked})
    if qty>0:
        last=df.iloc[end_index-1]; fill=float(last.close)*(1-slippage); gross=qty*fill; fee=gross*fee_rate; pnl=gross-fee-entry_value-entry_fee
        trades.append(_trade(strategy,df,entry_signal_time,entry_time,end_index-1,entry_fill,fill,qty,entry_value,entry_fee,fee,pnl,"Testende (Liquidation angenommen)",entry_reason))
        cash += gross-fee
        equity[-1]["equity"]=cash
    return metrics(pd.DataFrame(equity),pd.DataFrame(trades),initial_cash, timeframe, df.iloc[int(start_index):end_index],fee_rate,slippage), pd.DataFrame(trades), pd.DataFrame(equity), diagnostics


def _trade(strategy,df,signal_time,entry_time,exit_i,entry,exit,qty,entry_value,entry_fee,exit_fee,pnl,reason,why):
    return {"strategy":strategy,"market":"","signal_time":signal_time,"entry_time":entry_time,"exit_time":df.iloc[exit_i].timestamp,"side":"BUY/SELL","entry_price":entry,"exit_price":exit,"quantity":qty,"stop_loss":None,"take_profit":None,"entry_fee":entry_fee,"exit_fee":exit_fee,"fees":entry_fee+exit_fee,"slippage_assumption":"per fill","net_pnl":pnl,"exit_reason":reason,"decision_reason":why}


def metrics(curve,trades,initial_cash,timeframe,segment,fee_rate,slippage):
    vals=curve.equity.astype(float) if not curve.empty else pd.Series([initial_cash],dtype=float)
    ret=float(vals.iloc[-1]/initial_cash-1)
    dd=float((pd.concat([pd.Series([float(initial_cash)]),vals.reset_index(drop=True)]) /
              pd.concat([pd.Series([float(initial_cash)]),vals.reset_index(drop=True)]).cummax()-1).min())
    pnl=trades.net_pnl.astype(float) if not trades.empty else pd.Series(dtype=float)
    wins=pnl[pnl>0]; losses=pnl[pnl<0]; gross_win=float(wins.sum()); gross_loss=float(-losses.sum())
    annual_periods={"5m":105120,"15m":35040,"1h":8760,"4h":2190,"1d":365}.get(timeframe,35040)
    rets=vals.pct_change().dropna(); sharpe=float((rets.mean()/rets.std()*math.sqrt(annual_periods)) if len(rets)>1 and rets.std()>0 else 0)
    downside=rets[rets<0]; sortino=float((rets.mean()/downside.std()*math.sqrt(annual_periods)) if len(downside)>1 and downside.std()>0 else 0)
    bh=float((segment.iloc[-1].close*(1-slippage)*(1-fee_rate))/(segment.iloc[0].open*(1+slippage)*(1+fee_rate))-1)*100 if len(segment) else 0
    return {"initial_cash":initial_cash,"final_equity":float(vals.iloc[-1]),"net_pnl":float(vals.iloc[-1]-initial_cash),"return_pct":ret*100,"max_drawdown_pct":dd*100,"trades":len(pnl),"wins":len(wins),"losses":len(losses),"win_rate_pct":len(wins)/len(pnl)*100 if len(pnl) else 0,"avg_win":float(wins.mean()) if len(wins) else 0,"avg_loss":float(losses.mean()) if len(losses) else 0,"profit_factor":gross_win/gross_loss if gross_loss else (99.0 if gross_win else 0.0),"expectancy":float(pnl.mean()) if len(pnl) else 0,"sharpe":sharpe,"sortino":sortino,"buy_hold_return_pct":bh}
