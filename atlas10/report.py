"""A self-contained read-only iPad HTML snapshot of verified virtual accounts.

Never embeds tokens or makes browser network requests; a snapshot is intentionally
NOT a continuously updating trading interface.
"""
from __future__ import annotations
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from .monitor import verify_ledger


def snapshot(ledger_path:Path, output:Path, research_path:Path|None = None)->Path:
    ledger=json.loads(Path(ledger_path).read_text(encoding='utf-8'))
    status=verify_ledger(ledger)
    research=None
    if research_path is not None:
        research=json.loads(Path(research_path).read_text(encoding='utf-8'))
        if research.get('schema')!='atlas-research-v1.0' or research.get('execution_permission') is not False:
            raise ValueError('Research report cannot be safely displayed')
    cells=[]
    for name,account in status['accounts'].items():
        cells.append('<tr><td>'+escape(name)+'</td><td>'+f"{account['cash_eur']:.2f} €"+'</td><td>'+
                     f"{account['equity_eur']:.2f} €"+'</td><td>'+str(account['closed_trades'])+'</td><td>'+
                     ('Halt' if account['risk_halted'] else 'Research')+'</td></tr>')
    risk = status['circuit'] or status['failures'] > 0
    research_html=''
    if research:
        agg=research['aggregate_validation']
        research_html=(f'<section><h2>Autonome Offline-Forschung · {escape(research["data_source_type"])}</h2>'
                       f'<p>Walk-forward-Folds: {research["walk_forward"]["folds"]}; '
                       f'geprüfte Varianten: {research["candidate_pool_size"]}; '
                       f'geschlossene OOS-Trades: {agg["closed_trades"]}. '
                       f'<b>Keine Handelsfreigabe.</b></p></section>')
    html='''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas Trading AI v1.0 – Sicherer Forschungs-Snapshot</title>
<style>
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color-scheme:light dark}
body{margin:0;background:#0b1421;color:#e8edf5;font-size:16px}main{max-width:940px;margin:0 auto;padding:24px 16px 54px}
header{padding:20px 0}h1{font-size:clamp(1.6rem,5vw,2.3rem);margin:0 0 6px}.sub{color:#a8bdd0}
.notice{background:#213047;border:1px solid #476280;border-radius:13px;padding:14px;margin:15px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px}.metric,section{background:#142235;border:1px solid #29415b;border-radius:14px;padding:18px;margin:14px 0}
.metric strong{display:block;font-size:1.55rem;margin-top:9px}.metric span,small{color:#acc0d3}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{padding:12px 10px;text-align:left;border-bottom:1px solid #344b60}th{color:#add4e4}
a{color:#75d2ff}details{margin-top:16px}summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}
@media(prefers-color-scheme:light){body{background:#f4f7fa;color:#173047}.metric,section{background:#fff;border-color:#ccd9e3}.notice{background:#eaf2f8;border-color:#bdcedc}small,.sub,.metric span{color:#4d6379}th,td{border-color:#e2e8ef}}
</style></head><body><main><header><h1>Atlas Trading AI</h1><div class="sub">v1.0 · Verifizierte virtuelle Forschung · iPad-Snapshot</div></header>
<div class="notice"><b>Keine Echtgeld-Trades.</b> Diese Datei ist eine <b>statische Momentaufnahme</b> – kein Live-Dashboard und keine Handelsfreigabe.</div>
'''
    html += '<div class="grid">'
    for label,value in [('Virtuelle Konten',str(len(status['accounts']))),('Ledger-Ereignisse',str(status['events'])),
                        ('Letztes Ereignis',status['last_event']),('Sicherheitsstatus','ACHTUNG' if risk else 'Kein aktiver Fehler')]:
        html+='<div class="metric"><span>'+escape(label)+'</span><strong>'+escape(value)+'</strong></div>'
    html+='</div><section><h2>Kontenvergleich</h2><div class="tablewrap"><table><thead><tr><th>Strategie</th><th>Cash</th><th>Equity</th><th>Trades</th><th>Status</th></tr></thead><tbody>'
    html+=''.join(cells)+'</tbody></table></div></section>'
    html+=research_html
    html+='<section><h2>Prüfung und Zeitpunkt</h2><p>Letztes Ledger-Ereignis UTC: '+escape(status['last_event_utc'])+'</p>'
    html+='<p>Event-Chain/Seal: '+escape(status['integrity'])+'</p>'
    html+='<small>Quellcode-Hash und aktuelle GitHub-Actions-Ausführung müssen separat geprüft werden.</small></section>'
    html+='<p><a href="https://github.com/janneswiele/atlas-trading-ai/actions">GitHub Actions ansehen</a></p>'
    html+='</main></body></html>'
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(html,encoding='utf-8')
    return output
