"""Compare-and-swap-style durable Git ledger: normal push, never force or rebase."""
import subprocess
from pathlib import Path

FILES=('ledger.json','dashboard.html','quality.json')
BRANCH='atlas-v0.9-data'


def checkpoint(directory):
    directory=Path(directory).resolve()
    def git(*args):
        return subprocess.run(['git','-C',str(directory),*args],check=True,text=True,capture_output=True).stdout.strip()
    # Refuse a worktree with application or production files, even if misconfigured.
    tracked=set(git('ls-files').splitlines())
    if not tracked.issubset(FILES): raise ValueError('Ledger worktree contains protected/unexpected files')
    if not (directory/'ledger.json').is_file(): raise ValueError('No ledger to checkpoint')
    for filename in FILES:
        if (directory/filename).exists(): git('add','--',filename)
    if git('diff','--cached','--name-only'):
        git('-c','user.name=Atlas Shadow Research','-c','user.email=atlas-shadow@users.noreply.github.com',
            'commit','-m','Append Atlas shadow observation')
    # Even on no diff, retry an earlier unpushed commit. Rejection is a hard stop.
    git('push','origin','HEAD:refs/heads/'+BRANCH)
