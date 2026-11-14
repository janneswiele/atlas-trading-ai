"""Atlas Trading AI v1.0 CLI. NO live order functionality.

Usage: python atlas_v10.py research --csv DATA --approval MANIFEST --out RESULTS
       python atlas_v10.py propose --report RESULTS/research.json --out RESULTS
       python atlas_v10.py status [--ledger LOCAL_LEDGER]
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from atlas10.research import run_file
from atlas10.proposals import write_proposals
from atlas10.monitor import status


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    research=sub.add_parser('research',help='Offline research on an explicitly approved, SHA-pinned dataset')
    research.add_argument('--csv',required=True,type=Path)
    research.add_argument('--approval',required=True,type=Path)
    research.add_argument('--out',required=True,type=Path)
    research.add_argument('--fee-multiplier',default=1.0,type=float)
    propose=sub.add_parser('propose',help='Create research-only improvement proposals for human review')
    propose.add_argument('--report',required=True,type=Path)
    propose.add_argument('--out',required=True,type=Path)
    snap=sub.add_parser('snapshot',help='Build a read-only self-contained HTML page from a local verified ledger')
    snap.add_argument('--ledger',required=True,type=Path)
    snap.add_argument('--out',required=True,type=Path)
    snap.add_argument('--research',type=Path)
    view=sub.add_parser('status',help='Read and verify the separate v0.9 paper ledger (never write)')
    view.add_argument('--ledger',type=Path)
    args=p.parse_args(argv)
    if args.command=='research':
        path=run_file(args.csv,args.approval,args.out,fee_multiplier=args.fee_multiplier)
        print(json.dumps({'status':'RESEARCH_ONLY_NOT_APPROVED','report':str(path),'real_orders':False}))
    elif args.command=='propose':
        path=write_proposals(args.report,args.out)
        print(json.dumps({'status':'REVIEW_REQUIRED','proposals':str(path),'auto_merge':False}))
    elif args.command=='snapshot':
        from atlas10.report import snapshot
        path=snapshot(args.ledger,args.out,args.research)
        print(json.dumps({'status':'STATIC_READ_ONLY_SNAPSHOT','file':str(path),'live':False}))
    elif args.command=='status':
        print(json.dumps(status(args.ledger),ensure_ascii=False,indent=2))

if __name__ == '__main__': main()
