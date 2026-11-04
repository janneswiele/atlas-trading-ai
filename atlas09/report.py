"""Static read-only dashboard. It never executes a trading engine."""
import html
import json
from pathlib import Path
from datetime import datetime, timezone


def render(state, target):
    esc=lambda x: html.escape(str(x))
    rows=[]
    for name,a in state['accounts'].items():
        pf=a['gross_profit']/a['gross_loss'] if a['gross_loss'] else None
        rows.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in (
            name, f"€{a['equity']:.2f}",f"€{a['cash']:.2f}",f"{a['quantity']:.8f}",
            f"{a['equity']-100:+.2f}%", f"{a['drawdown']:.2%}", a['closed'],
            '—' if pf is None else f'{pf:.2f}', f"€{a['fees']:.3f}",
            a.get('last_decision','WARMUP'), 'GESPERRT' if a['halted'] else 'Forschung – keine Freigabe'))+'</tr>')
    events=state['events']
    last=events[-1]
    status='CIRCUIT BREAKER' if state['circuit'] else last['kind']
    valuations=[e for e in events if e['kind']=='VALUATION']
    curves=''
    if valuations:
        colors=['#67e8f9','#c4b5fd','#fbbf24','#86efac']
        allvalues=[e['payload']['accounts'][m]['equity'] for e in valuations for m in state['accounts']]
        low, high=min(allvalues)-.1,max(allvalues)+.1
        for color,m in zip(colors,state['accounts']):
            points=' '.join(f'{20+i*760/max(1,len(valuations)-1):.1f},{210-(e["payload"]["accounts"][m]["equity"]-low)/(high-low)*190:.1f}' for i,e in enumerate(valuations))
            curves+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/><text x="20" y="{235+colors.index(color)*20}" fill="{color}">{esc(m)}</text>'
        curves=f'<svg viewBox="0 0 800 325" role="img" aria-label="Equity in Beobachtungsreihenfolge">{curves}</svg>'
    else: curves='<p>Noch keine gültigen Forward-Bewertungen. Keine erfundene Performancekurve.</p>'
    recent=''.join('<tr>'+''.join(f'<td>{esc(x)}</td>' for x in (datetime.fromtimestamp(e['time'],timezone.utc).isoformat(), e['kind'], e['payload'].get('model',''), e['payload'].get('reason',e['payload'].get('error',''))))+'</tr>' for e in events[-50:][::-1])
    stamp=datetime.fromtimestamp(last['time'],timezone.utc).isoformat()
    document=f'''<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Atlas 0.9 Forschung</title>
<style>body{{background:#0b1220;color:#e2e8f0;font:16px system-ui;margin:0;padding:24px}}main{{max-width:1200px;margin:auto}}section{{background:#172238;border-radius:16px;padding:20px;margin:18px 0}}h1{{color:#67e8f9}}table{{border-collapse:collapse;white-space:nowrap;width:100%}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #334155}}.scroll{{overflow:auto}}.warn{{color:#fbbf24}}svg{{width:100%}}</style>
<main><h1>Atlas 0.9 · Shadow Research</h1><p>BTC/EUR · 4h UTC · ausschließlich virtuelle Forschung</p>
<section><h2>{esc(status)}</h2><p>Letztes Ereignis: {esc(stamp)}</p><p id="age" class="warn"></p><p>Finaler historischer Holdout: versiegelt. Keine Strategie freigegeben.</p></section>
<section><h2>Unabhängige Konten · je 100 € Startkapital</h2><div class="scroll"><table><tr>{''.join('<th>'+h+'</th>' for h in ['Strategie','Equity','Cash','BTC','Rendite','Max. DD','Geschlossene Trades','PF','Gebühren','Entscheidung','Status'])}</tr>{''.join(rows)}</table></div></section>
<section><h2>Tatsächlich protokollierte Forward-Bewertungen</h2>{curves}<p>Kurven zeigen gespeicherte Prüfzeitpunkte, keine intrabar überwachten Kurse.</p></section>
<section><h2>Letzte Ereignisse</h2><div class="scroll"><table>{recent}</table></div></section>
<p class="warn">Statische Momentaufnahme. Dieses Dashboard führt keinen Python-Code aus. Stops werden nur bei gültigen Prüfungen verarbeitet und garantieren keinen Verkaufspreis.</p></main>
<script>const age=(Date.now()/1000-{last['time']})/3600;document.getElementById('age').textContent=age>5?'VERALTET: seit '+age.toFixed(1)+' Stunden kein neues Ereignis.':'Momentaufnahme – Alter: '+age.toFixed(1)+' Stunden';</script></html>'''
    Path(target).write_text(document,encoding='utf-8')
