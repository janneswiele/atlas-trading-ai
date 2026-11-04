"""Read-only Streamlit companion. Deploy this file on atlas-v0.9, not main."""
from pathlib import Path
import json
import tempfile
import requests
import streamlit as st
import streamlit.components.v1 as components
from atlas09.core import validate_state, source_hash
from atlas09.report import render

ROOT=Path(__file__).resolve().parent

@st.cache_data(ttl=300)
def read_ledger():
    response=requests.get('https://raw.githubusercontent.com/janneswiele/atlas-trading-ai/atlas-v0.9-data/ledger.json',timeout=20)
    response.raise_for_status()
    return response.json()


def main():
    st.set_page_config(page_title='Atlas 0.9 Research',layout='wide')
    st.title('Atlas 0.9 · Forschung und Shadow-Paper')
    st.caption('Keine Echtgeldorders · keine Strategie freigegeben · historischer Holdout versiegelt')
    forward,historical=st.tabs(['Neue Forward-Beobachtungen','Historische Gebührenanalyse'])
    with forward:
        try:
            state=read_ledger()
            validate_state(state,json.loads((ROOT/'atlas_v09_config.json').read_text()),source_hash(ROOT))
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'dashboard.html';render(state,path)
                components.html(path.read_text(),height=1250,scrolling=True)
        except Exception as exc:
            st.warning('Keine verifizierten Forward-Daten verfügbar. Nach Installation zuerst separat aktivieren. Fehler: '+str(exc))
    with historical:
        st.warning('Bereits untersuchte historische Entwicklungsdaten. Keine neuen unabhängigen Testergebnisse.')
        import pandas as pd
        path=ROOT/'research_evidence/v085/historical_fee_scenarios.csv'
        if path.exists():
            data=pd.read_csv(path)
            st.dataframe(data.groupby(['strategy','fee_per_fill'])[['net_return','alpha_vs_same_cost_passive20','trades']].mean(),use_container_width=True)
            st.caption('Renditen als Dezimalwerte; Trades = Mittelwert je historischem Fenster. Slippage zusätzlich 0,05 % je Fill.')
        else: st.info('Historische Berichtdatei fehlt.')

if __name__=='__main__': main()
