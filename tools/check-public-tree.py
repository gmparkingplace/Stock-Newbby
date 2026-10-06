#!/usr/bin/env python3
"""Fail publication if tracked files contain private artifacts or machine paths."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'.git', '.venv', '__pycache__', '.pytest_cache', 'logs', 'work',
                 'private-backups', 'shots', 'archive', 'history'}
PRIVATE_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.log', '.patch', '.pem', '.p12', '.pfx'}
MACHINE_PATH = re.compile(rb'/(?:home|run/media)/[A-Za-z0-9_.-]+/')


def problems(path, raw):
    issues = []
    if (PRIVATE_PARTS.intersection(path.parts) or path.suffix in PRIVATE_SUFFIXES
            or path.name == '.local.json' or path.name == '.env'
            or (path.name.startswith('.env.') and path.name != '.env.example')
            or ('credentials' in path.name.lower() and path.suffix == '.txt'
                and path.name != 'toss-credentials.example.txt')):
        issues.append('private artifact')
    if MACHINE_PATH.search(raw):
        issues.append('machine path')
    if b'-----BEGIN ' + b'PRIVATE KEY-----' in raw or b'-----BEGIN ' + b'RSA PRIVATE KEY-----' in raw:
        issues.append('private key')
    return issues


def main():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0')
    found = []
    for raw_path in filter(None, paths):
        rel = Path(raw_path.decode())
        file = ROOT / rel
        if file.is_symlink():
            found.append((str(rel), 'symlink'))
            continue
        if not file.is_file():
            found.append((str(rel), 'missing tracked file'))
            continue
        for issue in problems(rel, file.read_bytes()):
            found.append((str(rel), issue))
    for rel, issue in found:
        print(f'{issue}: {rel}', file=sys.stderr)
    print(f'Public tree: {len(list(filter(None, paths)))} files; {len(found)} violations')
    return bool(found)


if __name__ == '__main__':
    sys.exit(main())
