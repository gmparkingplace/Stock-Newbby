#!/usr/bin/env python3
"""Install the packaged chart skill into the current user's Codex skill directory."""
import argparse,os,shutil
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--update',action='store_true',help='replace an existing chart-assistant skill')
a=p.parse_args()
source=Path(__file__).resolve().parents[1]/'skills/chart-assistant'
target=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'skills/chart-assistant'
if target.exists() and not a.update:p.error('skill exists; use --update only to replace this skill')
shutil.copytree(source,target,dirs_exist_ok=a.update,ignore=shutil.ignore_patterns('__pycache__'))
print('Installed chart-assistant skill:',target)
