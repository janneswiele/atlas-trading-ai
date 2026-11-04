"""Public read-only market endpoints; raw responses are content-addressed."""
from datetime import datetime, timezone
import hashlib
import json
import time
from pathlib import Path
import requests
import pandas as pd
from atlas09.core import STEP, WARMUP, WARMUP_START, validated_frame


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class PublicMarket:
    def __init__(self, archive, clock=time.time):
        self.archive=Path(archive); self.archive.mkdir(parents=True, exist_ok=True)
        self.clock=clock

    def get(self, url, params=None):
        # GET-only, fixed official public URLs. No trading credentials or private endpoints.
        response=requests.get(url, params=params, timeout=(10,30), headers={'User-Agent':'Atlas-Shadow-Research/0.9'})
        response.raise_for_status()
        body=response.content
        sha=hashlib.sha256(body).hexdigest()
        path=self.archive/(sha+'.json')
        if not path.exists():
            with path.open('xb') as f: f.write(body)
        metadata=dict(url=response.url, received_at=self.clock(), sha256=sha)
        with (self.archive/'requests.jsonl').open('a') as f:
            f.write(json.dumps(metadata)+'\n')
        return response.json()

    def candles(self, now, require_fresh=True):
        end=int(now//STEP)*STEP
        start=max(WARMUP_START,end-WARMUP*STEP)
        if start>=end: raise ValueError('No post-holdout closed candles')
        hours={}
        for left in range(start,end,250*3600):
            right=min(end,left+250*3600)
            data=self.get('https://api.exchange.coinbase.com/products/BTC-EUR/candles',
                          dict(start=iso(left),end=iso(right),granularity=3600))
            if not isinstance(data,list): raise ValueError('Malformed Coinbase response')
            for row in data:
                if len(row)!=6: raise ValueError('Malformed Coinbase candle')
                t,low,high,op,close,volume=row
                if not left<=t<right: continue
                normalized=[t,op,high,low,close,volume]
                from atlas_v06 import check_hour
                check_hour(normalized,left,right)
                if t in hours and hours[t]!=normalized: raise ValueError('Conflicting Coinbase duplicates')
                hours[t]=normalized
        rows=[]
        for t in range(start,end,STEP):
            keys=[t+i*3600 for i in range(4)]
            if not all(k in hours for k in keys): raise ValueError('Incomplete four-hour candle')
            sub=[hours[k] for k in keys]
            rows.append([t*1000,sub[0][1],max(r[2] for r in sub),min(r[3] for r in sub),sub[-1][4],sum(r[5] for r in sub)])
        frame=pd.DataFrame(rows,columns=['timestamp','open','high','low','close','volume'])
        if require_fresh:
            validated_frame(frame,now)
        else:
            from atlas_v06 import validate_4h_rows
            validate_4h_rows(frame,now=int(now))
        kr=self.get('https://api.kraken.com/0/public/OHLC',dict(pair='XBTEUR',interval=240,since=start))
        if kr.get('error'): raise ValueError('Kraken API error')
        series=[v for k,v in kr['result'].items() if k!='last']
        if len(series)!=1: raise ValueError('Ambiguous Kraken pair')
        control=[]; seen=set()
        for row in series[0]:
            t=int(row[0])
            if not start<=t<end: continue
            if t in seen: raise ValueError('Duplicate Kraken candle')
            seen.add(t)
            control.append([t*1000,*map(float,row[1:5]),float(row[6])])
        other=pd.DataFrame(sorted(control),columns=frame.columns)
        if require_fresh:
            validated_frame(other,now)
        else:
            validate_4h_rows(other,now=int(now))
        if frame.timestamp.tolist()!=other.timestamp.tolist(): raise ValueError('Coinbase/Kraken alignment failed')
        differences=2*(frame.close-other.close).abs()/(frame.close+other.close)
        if differences.max()>.015 or differences.median()>.0025:
            raise ValueError('Cross-exchange price anomaly')
        return frame, dict(status='PASS',bars=len(frame),start=start,end=end,
                           median_close_difference=float(differences.median()),max_close_difference=float(differences.max()),
                           candle_age_seconds=now-end, execution_eligible=now-end<=3600 and len(frame)>=WARMUP,
                           scope='Forward rolling-window cross-check; not full historical validation')

    def quote(self):
        data=self.get('https://api.exchange.coinbase.com/products/BTC-EUR/ticker')
        stamp=datetime.fromisoformat(data['time'].replace('Z','+00:00'))
        if stamp.tzinfo is None: raise ValueError('Quote timestamp lacks timezone')
        return dict(bid=float(data['bid']),ask=float(data['ask']),
                    exchange_time=stamp.timestamp(),
                    observed_at=self.clock(), source='Coinbase BTC-EUR public ticker')
