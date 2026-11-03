"""Deterministic long-only spot signals; each signal is known at candle close."""
import pandas as pd


def indicators(df):
    x = df.copy()
    x["ema20"] = x.close.ewm(span=20, adjust=False, min_periods=20).mean()
    x["ema50"] = x.close.ewm(span=50, adjust=False, min_periods=50).mean()
    x["ema200"] = x.close.ewm(span=200, adjust=False, min_periods=200).mean()
    d = x.close.diff()
    gain = d.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    x["rsi"] = 100 - 100 / (1 + rs)
    x.loc[(loss == 0) & (gain > 0), "rsi"] = 100
    x.loc[(loss == 0) & (gain == 0), "rsi"] = 50
    x["prior_high"] = x.high.rolling(20, min_periods=20).max().shift(1)
    x["prior_low"] = x.low.rolling(20, min_periods=20).min().shift(1)
    x["atr"] = pd.concat([x.high-x.low, (x.high-x.close.shift()).abs(), (x.low-x.close.shift()).abs()], axis=1).max(axis=1).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    return x


def generate_signals(df, name, params=None):
    params = params or {}
    x = indicators(df)
    if name == "EMA Trend":
        fast=int(params.get("ema_fast",20)); slow=int(params.get("ema_slow",50)); trend=int(params.get("ema_trend",200))
        fast_ema=x.close.ewm(span=fast,adjust=False,min_periods=fast).mean()
        slow_ema=x.close.ewm(span=slow,adjust=False,min_periods=slow).mean()
        trend_ema=x.close.ewm(span=trend,adjust=False,min_periods=trend).mean()
        enter = (fast_ema > slow_ema) & (fast_ema.shift(1) <= slow_ema.shift(1)) & (x.close > trend_ema)
        exit_ = fast_ema < slow_ema
        why = f"EMA{fast} kreuzt EMA{slow} nach oben, Kurs über EMA{trend}"
    elif name == "RSI Reversion":
        oversold=float(params.get("rsi_entry",30)); target=float(params.get("rsi_exit",55)); trend=int(params.get("ema_trend",200))
        trend_ema=x.close.ewm(span=trend,adjust=False,min_periods=trend).mean()
        enter = (x.rsi.shift(1) < oversold) & (x.rsi >= oversold) & (x.close > trend_ema)
        exit_ = (x.rsi >= target) | (x.close < x.ema50)
        why = f"RSI erholt sich über {oversold:g}, Kurs über EMA{trend}"
    elif name == "Breakout":
        lookback=int(params.get("lookback",20)); volume_factor=float(params.get("volume_factor",1.0))
        prior_high=x.high.rolling(lookback,min_periods=lookback).max().shift(1)
        prior_low=x.low.rolling(lookback,min_periods=lookback).min().shift(1)
        volume_avg=x.volume.rolling(lookback,min_periods=lookback).mean()
        enter = (x.close > prior_high) & (x.volume > volume_avg*volume_factor)
        exit_ = x.close < prior_low
        why = f"Schlusskurs über vorherigem {lookback}-Kerzen-Hoch mit Volumenbestätigung"
    elif name == "SMA 20/50":
        fast = x.close.rolling(20).mean()
        slow = x.close.rolling(50).mean()
        enter = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        exit_ = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        why = "SMA20 kreuzt SMA50 nach oben"
    else:
        raise ValueError(f"Unbekannte Strategie: {name}")
    return enter.fillna(False).astype(bool), exit_.fillna(False).astype(bool), x, why


STRATEGIES = ["EMA Trend", "RSI Reversion", "Breakout", "SMA 20/50"]
