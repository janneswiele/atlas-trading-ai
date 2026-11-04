"""iPad responsive, read-only Streamlit dashboard. No trade or write controls."""
from __future__ import annotations
import json
from pathlib import Path
from .monitor import status


def main() -> None:
    import streamlit as st
    import pandas as pd
    st.set_page_config(page_title='Atlas Trading AI · v1.0',page_icon='📊',layout='wide')
    st.title('Atlas Trading AI')
    st.caption('v1.0 Forschungs-Dashboard · Nur virtuelle Konten · Keine Echtgeld-Order-Schnittstelle')
    st.warning('Strategien sind NICHT zum Echtgeldhandel zugelassen. Forschung ≠ Profitabilitätsnachweis.')
    @st.cache_data(ttl=90, show_spinner=False)
    def cached_status():
        return status()
    try:
        s=cached_status()
    except Exception as exc:
        st.error('Aktuelles Forschungsledger konnte nicht sicher geladen/verifiziert werden.')
        st.code(f'{type(exc).__name__}: {exc}')
        st.stop()
    a,b,c=st.columns(3)
    a.metric('Virtuelle Forschungskonten',len(s['accounts']))
    b.metric('Ledger-Ereignisse',s['events'])
    c.metric('Letztes Ereignis',s['last_event'])
    st.caption('Letzter Eintrag (UTC): '+s['last_event_utc'])
    if s['circuit'] or s['failures']:
        st.error(f"Sicherheitsmeldung: Circuit={s['circuit']}, Fehler={s['failures']}")
    else:
        st.success('Kein aktiver Circuit und keine gezählten Datenfehler')
    st.subheader('Getrennte virtuelle Konten')
    frame=pd.DataFrame([{'Strategie':k,**v} for k,v in s['accounts'].items()])
    st.dataframe(frame,use_container_width=True,hide_index=True)
    st.caption('Kontostände stammen aus dem unveränderten Forschungsbranch atlas-v0.9-data. Keine Umschreibefunktion.')
    st.subheader('Forschungsstand')
    st.info('v1.0 trennt Strategieforschung und v0.9-Forward-Test. Noch kein Champion automatisch freigegeben.')
    report_file=Path('atlas-v10-results/research.json')
    if report_file.exists():
        report=json.loads(report_file.read_text(encoding='utf-8'))
        if report.get('schema')=='atlas-research-v1.0':
            summ=report['aggregate_validation']
            d,e,f=st.columns(3)
            d.metric('Walk-forward-Folds',report['walk_forward']['folds'])
            e.metric('Validierte Trades',summ['closed_trades'])
            f.metric('Summe Netto-Alpha',f"{summ['sum_net_alpha']:.2%}")
            st.caption('Nur Forschungsergebnisse – keine Freigabe, keine nachgewiesene Profitabilität.')
            rows=[]
            for fold in report['fold_results']:
                rows.append({'Kandidat':fold['winner_id'],**fold['validation']})
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
    else:
        st.caption('Noch kein freigegebener research.json-Datensatz bereitgestellt.')
    st.subheader('Workflow-Überwachung')
    st.markdown('[GitHub Actions für Atlas v0.9](https://github.com/janneswiele/atlas-trading-ai/actions)')
    st.caption('GitHub Zeitpläne sind best effort: verspätete oder ausgelassene Ausführungen sind möglich.')
    st.code(s['integrity'])

if __name__ == '__main__':
    main()
