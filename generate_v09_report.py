"""Rebuild figures from verified archived results. Never runs a trading strategy."""
import hashlib
import json
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    root=Path(__file__).resolve().parent
    source=root/'research_evidence/v085'
    for name,expected in json.loads((source/'SHA256SUMS.json').read_text()).items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=expected: raise ValueError('Archived evidence changed')
    data=pd.read_csv(source/'historical_fee_scenarios.csv')
    out=root/'research_evidence/v09';out.mkdir(exist_ok=True)
    plt.style.use('dark_background')
    fig,ax=plt.subplots(figsize=(11,6))
    labels={'SMA 20/50':'SMA 20/50','EMA Trend':'EMA Trend','Donchian30_Chandelier22_ATR14x2p5':'Donchian 30','TSMOM60_Vol30_180x1p5':'Momentum 60'}
    for model,group in data.groupby('strategy'):
        summary=group.groupby('fee_per_fill').net_return.mean()*100
        ax.plot(summary.index*100,summary.values,marker='o',label=labels[model])
    ax.axhline(0,color='gray',linestyle='--')
    ax.set(xlabel='Fee per fill (%) + 0.05% slippage',ylabel='Mean net return per 90-day window (%)',title='Archived v0.8.5: seven reused historical windows\nExploratory evidence — not new forward results')
    ax.legend();fig.tight_layout();fig.savefig(out/'historical_fee_sensitivity.png',dpi=150);plt.close(fig)
    prices=pd.read_csv(out/'coinbase_post_holdout_4h.csv')
    fig,ax=plt.subplots(figsize=(11,5))
    ax.plot(pd.to_datetime(prices.timestamp,unit='ms',utc=True),prices.close,color='#67e8f9')
    ax.set(title='Actual Coinbase BTC/EUR closed 4h candles\nRead-only post-holdout data validation; no simulated trades',ylabel='EUR')
    fig.autofmt_xdate();fig.tight_layout();fig.savefig(out/'observed_market.png',dpi=150);plt.close(fig)

if __name__=='__main__': main()
