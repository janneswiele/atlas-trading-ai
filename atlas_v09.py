"""Atlas 0.9 CLI. Separate shadow ledger; never changes production account files."""
import argparse
import json
import time
from pathlib import Path
from paper import atomic_json, locked
from atlas09.core import config_check, source_hash, new_state, validate_state, prepare, settle, failed
from atlas09.market import PublicMarket
from atlas09.report import render

ROOT=Path(__file__).resolve().parent


def run(directory, activate=False, git_ledger=False):
    directory=Path(directory).resolve()
    if directory==ROOT or ROOT.is_relative_to(directory):
        raise ValueError('Use an isolated shadow directory')
    directory.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/'atlas_v09_config.json').read_text())
    production=json.loads((ROOT/'paper_config.json').read_text())
    config_check(config,production)
    if not config['enabled']:
        print('DISABLED: no orders, no state reset'); return
    code=source_hash(ROOT)
    path=directory/'ledger.json'
    def save(state):
        atomic_json(path,state)
        if git_ledger:
            from atlas09.persist import checkpoint
            checkpoint(directory)
    with locked(path):
        if path.exists():
            state=json.loads(path.read_text()); validate_state(state,config,code)
            if activate: raise ValueError('Already activated; reset forbidden')
        elif activate:
            state=new_state(config,time.time(),code); save(state)
        else:
            raise ValueError('Missing state: explicit first activation required, never auto-reset')
        market=PublicMarket(directory/'raw')
        try:
            frame,quality=market.candles(time.time())
            state=prepare(state,frame,config,time.time())
            save(state)  # decision durable before quote retrieval
            atomic_json(directory/'quality.json',quality)
            if state['pending']:
                quote=market.quote()
                for _ in range(2):
                    if quote['exchange_time'] >= state['pending']['at']: break
                    time.sleep(2)
                    quote=market.quote()
                state=settle(state,quote,config,time.time())
                save(state)
        except Exception as exc:
            state=failed(state,time.time(),exc); save(state)
            render(state,directory/'dashboard.html')
            raise
        render(state,directory/'dashboard.html')
        print(json.dumps(dict(status=state['events'][-1]['kind'],events=len(state['events']),approved=False)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',default='atlas-shadow-data')
    parser.add_argument('--activate',action='store_true',help='First activation only, requires enabled=true')
    parser.add_argument('--git-ledger',action='store_true',help='Checkpoint decisions remotely before requesting execution quotes')
    args=parser.parse_args()
    run(args.directory,args.activate,args.git_ledger)


if __name__=='__main__': main()
