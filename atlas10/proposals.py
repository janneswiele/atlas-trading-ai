"""Auditable deterministic hypothesis proposals; no self-editing or AI API calls."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path


def propose(report:dict) ->dict:
    if report.get('schema')!='atlas-research-v1.0' or report.get('execution_permission') is not False:
        raise ValueError('Not an isolated v1.0 research report')
    oos=report['aggregate_validation']
    hypotheses=[]
    if oos['folds_not_outperforming']:
        hypotheses.append({'hypothesis':'Additional trend regime filter may reduce weak-market false entries',
                           'allowed_test':'Compare predefined vol_limit values on a fresh, approved training window',
                           'warning':'Do not tune against a sealed or previously inspected holdout'})
    if oos['closed_trades']<8:
        hypotheses.append({'hypothesis':'Sample size is insufficient to establish trading robustness',
                           'allowed_test':'Collect more forward observations; do not lower statistical or risk gates',
                           'warning':'Avoid extrapolation from few trades'})
    if oos['worst_fold_drawdown'] < -.05:
        hypotheses.append({'hypothesis':'Validation fold losses may be regime-dependent',
                           'allowed_test':'Pre-register a stress test with higher fee/slippage and the frozen allocation',
                           'warning':'Never modify v0.9 risk thresholds'})
    if not hypotheses:
        hypotheses.append({'hypothesis':'Preliminary validation needs replication',
                           'allowed_test':'Run the exact registered grid on a separately approved, later forward period',
                           'warning':'Do not interpret training fit as live performance'})
    return {'schema':'atlas-v1.0-research-proposals','source_report_sha256':None,
            'status':'PROPOSALS_REQUIRE_HUMAN_REVIEW','auto_merge':False,
            'auto_change_risk':False,'auto_trade':False,
            'suggestions':hypotheses}


def write_proposals(report_file:Path, output_dir:Path)->Path:
    report_file=Path(report_file)
    data=json.loads(report_file.read_text(encoding='utf-8'))
    result=propose(data)
    from .policy import sha_file
    result['source_report_sha256']=sha_file(report_file)
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    target=output_dir/'proposals.json'
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    lines=['# Atlas v1.0 – research-only improvement proposals','',
           'No self-modification, code push, new Champion, or real trading is authorized.','',
           f"Source report SHA256: `{result['source_report_sha256']}`",'']
    for i,p in enumerate(result['suggestions'],1):
        lines.extend([f'## Experiment {i}',f"Hypothesis: {p['hypothesis']}",
                      f"Test: {p['allowed_test']}",f"Guardrail: {p['warning']}",''])
    (output_dir/'PROPOSALS_FOR_REVIEW.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return target
