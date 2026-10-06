#!/usr/bin/env python3
"""Export current code with blank credentials and synthetic data, not user records."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ('run.py', 'setup.py', 'start.sh', 'start.bat', 'index.html',
              'requirements.txt', 'requirements-lock.txt', 'requirements-dev.txt', 'SECURITY.md', 'LICENSE')
TREES = {'scripts': {'.py'}, 'lab': {'.py'}, 'skills': {'.md', '.py', '.yaml'},
         'tests': {'.py', '.js', '.json'}, 'tools': {'.py', '.js'},
         'distribution': {'.md'}, '.github': {'.yml', '.yaml'}}
EXCLUDED_PARTS = {'__pycache__', '.pytest_cache', '.venv', 'shots', 'logs', 'work'}


def credentials(source):
    """Read only to reject accidental key copies; never authenticate or print values."""
    config = source / '.local.json'
    path = os.environ.get('TOSS_CREDENTIALS_FILE')
    if not path and config.is_file():
        path = json.loads(config.read_text()).get('tossCredentialsFile')
    if not path:
        return []
    key_file = Path(path).expanduser()
    if not key_file.is_file():
        raise ValueError('Configured key file unavailable; cannot check credential leakage')
    found = re.findall(r'^\s*Client\s+(?:Id|Secret)\s*[:=]?\s*(\S+)\s*$',
                       key_file.read_text(encoding='utf-8-sig'), re.I | re.M)
    return [value.encode() for value in found]


def portable_text(text, source):
    # Remove machine paths in skill examples and old test docstrings only.
    text = text.replace(str(source), '/path/to/Stock-Newbby')
    text = re.sub(r'/home/[A-Za-z0-9_.-]+/', '~/', text)
    text = re.sub(r'/run/media/[A-Za-z0-9_.-]+/[^\s`\"\']+', '/path/to/Stock-Newbby', text)
    return text


def audit(folder, secret_values=()):
    problems = []
    for p in folder.rglob('*'):
        rel = p.relative_to(folder)
        if '.git' in rel.parts or not p.is_file():
            continue
        if p.is_symlink():
            problems.append(f'symlink: {rel}')
            continue
        raw = p.read_bytes()
        if any(value and value in raw for value in secret_values):
            problems.append(f'credential value: {rel}')
        if re.search(rb'/(?:home|run/media)/[A-Za-z0-9_.-]+/', raw):
            problems.append(f'machine path: {rel}')
        if p.name in {'.local.json', '.env', 'Open API.txt'} or p.suffix in {'.sqlite3', '.sqlite', '.db', '.log', '.png', '.patch'}:
            problems.append(f'private artifact: {rel}')
    return problems


def demo_data(source):
    """Deterministic synthetic OHLCV; calculate with the same production engine."""
    sys.path.insert(0, str(source / 'scripts'))
    import pandas as pd
    from signals import frame, to_weekly, to_monthly
    rows = []
    for i, day in enumerate(pd.bdate_range('2024-01-01', periods=540)):
        close = round(60000 + i * 12 + 2300 * math.sin(i / 13) + 900 * math.sin(i / 5), 2)
        op = round(close + 220 * math.sin(i / 3), 2)
        rows.append(dict(t=str(day.date()), open=op, high=max(op, close) + 400,
                         low=min(op, close) - 400, close=close, volume=1000000 + i % 11 * 70000))
    daily = pd.DataFrame(rows)
    month, _ = to_monthly(daily)
    result = frame(daily, False)
    result.update(symbol='005930.KS', name='삼성전자 · 합성 예시(실제 시세 아님)',
                  source='synthetic-demo', demo=True, confirmed=True,
                  lastConfirmedTime=rows[-1]['t'], strats=['A', 'B', 'C', 'F'], trades={},
                  weekly=frame(to_weekly(daily), False), monthly=frame(month, False))
    for key in ('weekly', 'monthly'):
        result[key].update(source='synthetic-demo', demo=True, confirmed=True,
                           lastConfirmedTime=result[key]['candles'][-1]['time'])
    return {'exps': [dict(id='synthetic-demo', label='합성 예시 · 실제 시세 아님',
                          symbols={'005930.KS': result})]}


def build(source, output, version='0.6.2'):
    source, output = source.resolve(), output.resolve()
    if output == source or source in output.parents:
        raise ValueError('Output must be outside the development project')
    if output.exists() and any(p.name != '.git' for p in output.iterdir()):
        raise ValueError('Output must be empty (an unused Git checkout is allowed)')
    keys = credentials(source)
    output.mkdir(parents=True, exist_ok=True)
    selected = [source / name for name in ROOT_FILES]
    for tree, extensions in TREES.items():
        selected.extend(p for p in (source / tree).rglob('*')
                        if p.is_file() and p.suffix in extensions
                        and not EXCLUDED_PARTS.intersection(p.relative_to(source).parts)
                        and p.name != 'test_compat.py')
    dash = source / 'results/dashboard'
    selected.extend(p for p in dash.iterdir() if p.is_file() and
                    (p.suffix == '.js' and p.name != 'data.js' or
                     p.name in {'chart-first.html', 'index.html'}))
    selected.extend((dash / 'lib').glob('*'))
    for p in selected:
        if p.is_symlink():
            raise ValueError('Source symlink refused: ' + str(p.relative_to(source)))
        dest = output / p.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = portable_text(p.read_text(encoding='utf-8'), source)
        if p.name == 'chartctl.py':
            text = text.replace("'http://127.0.0.1:8735'", "'http://127.0.0.1:8734'")
        if p.name == 'SKILL.md':
            text = re.sub(r'Current project:.*?\n\n',
                          'Project: the cloned Stock-Newbby folder. Packaged skill: `skills/chart-assistant`. '
                          'After edits, update the installed skill with `python3 tools/install-chart-skill.py --update`.\n\n',
                          text, flags=re.S)
            text = text.replace('section14', 'the low-entry section')
            text = text.replace('docs/LOW-ENTRY-DESIGN-20261006.md', 'docs/FEATURES.md')
            text = text.replace('Default URL is `http://127.0.0.1:8735`', 'Default URL is `http://127.0.0.1:8734`')
        dest.write_text(text, encoding='utf-8')
        shutil.copymode(p, dest)
    for name, target in [('README.md', 'README.md'), ('TOSS.md', 'docs/TOSS.md'), ('FEATURES.md', 'docs/FEATURES.md')]:
        dest = output / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((source / 'distribution' / name).read_text(), encoding='utf-8')
    (output / 'AGENTS.md').write_text('# Development\n\nRead README.md and docs/FEATURES.md. '
        'Current UI: results/dashboard/chart-first.html. Never commit .local.json, keys, logs or user records. '
        'Keep synthetic examples distinct from live data. Run npm test and pytest for changes.\n')
    package = json.loads((source / 'package.json').read_text())
    package.update(version=version, description='배포용 초보자 차트 보조기')
    commands = package['scripts']
    commands['test'] = ' && '.join(part for part in commands['test'].split(' && ') if 'prototype/' not in part)
    for name in list(commands):
        if 'prototype/' in commands[name]:
            del commands[name]
    (output / 'package.json').write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
    (output / '.gitignore').write_text((source / '.gitignore').read_text() +
        '\n*.sqlite\n*.sqlite3\n*.sqlite3-*\n*.db\nOpen API.txt\n*credentials*.txt\n!toss-credentials.example.txt\n')
    config = dict(tossCredentialsFile='', sharedMarketCache=True, horizontalPatterns=True,
                  flagPatterns=True, serverMonitor=True, trianglePatterns=True)
    (output / '.local.example.json').write_text(json.dumps(config, indent=2) + '\n')
    (output / 'toss-credentials.example.txt').write_text('Client Id:\nClient Secret:\n')
    demo = json.dumps(demo_data(source), ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    (output / 'results/dashboard').mkdir(parents=True, exist_ok=True)
    (output / 'results/dashboard/data.js').write_text('const DASHBOARD_DATA = ' + demo + ';\n')
    (output / 'results/dashboard/data.json').write_text(demo + '\n')
    problems = audit(output, keys)
    if problems:
        raise ValueError('\n'.join(problems))
    files = [dict(path=str(p.relative_to(output)), bytes=p.stat().st_size,
                  sha256=hashlib.sha256(p.read_bytes()).hexdigest())
             for p in sorted(output.rglob('*')) if p.is_file() and '.git' not in p.relative_to(output).parts]
    manifest = dict(name='chart-assistant', version=version, entry='run.py', files=files)
    (output / 'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return len(files) + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', default='0.6.2')
    args = parser.parse_args()
    print(f'Public release: {build(ROOT, args.output, args.version)} files; no personal data or key values')


if __name__ == '__main__':
    main()
