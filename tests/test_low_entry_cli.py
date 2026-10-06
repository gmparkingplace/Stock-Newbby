"""Readonly cache/headless parity tests; no provider or running chart server."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/audit-low-entry.js'
CLI = ROOT / 'skills/chart-assistant/scripts/chartctl.py'


def invoke(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)


@pytest.fixture
def frame():
    proc = invoke(['node', '-e', "const {sample,day}=require('./tests/low_entry_sample');console.log(JSON.stringify({symbol:'TEST',tf:'D',candles:sample('H'),source:'toss',fetchedAt:'2026-02-13T20:00:00Z',marketSession:{state:'closed'},lastConfirmedTime:day(43),confirmed:true}));"])
    assert proc.returncode == 0
    return json.loads(proc.stdout)


def test_offline_cache_and_input_use_same_engine_without_db_writes(tmp_path, frame):
    cache = tmp_path / 'market.sqlite3'
    conn = sqlite3.connect(cache)
    conn.execute('CREATE TABLE entries (key TEXT PRIMARY KEY, value TEXT)')
    conn.execute('INSERT INTO entries VALUES (?,?)', ('toss|TEST|D|800', json.dumps(frame)))
    conn.commit()
    conn.close()
    before = hashlib.sha256(cache.read_bytes()).hexdigest()
    inp = tmp_path / 'frame.json'
    inp.write_text(json.dumps(frame))
    params = ['--symbol', 'TEST', '--tf', 'D', '--as-of', '2026-01-27']
    cached = invoke([sys.executable, str(CLI), 'low', '--cache', str(cache), *params])
    direct = invoke(['node', str(TOOL), '--input', str(inp), *params])
    assert cached.returncode == direct.returncode == 0, (cached.stderr, direct.stderr)
    assert json.loads(cached.stdout) == json.loads(direct.stdout)
    result = json.loads(cached.stdout)[0]
    assert result['decision']['code'] == 'historical'
    assert result['decision']['setupDecision']['code'] == 'candidate'
    assert result['lowStructures']['current']['H']['signalAt'] == '2026-01-27'
    assert result['version'] == 'low-entry-v1'
    assert hashlib.sha256(cache.read_bytes()).hexdigest() == before
    assert not (tmp_path / 'market.sqlite3-wal').exists()


def test_audit_predefined_profiles_have_causal_signals_and_fixed_risk(tmp_path, frame):
    inp = tmp_path / 'frame.json'
    inp.write_text(json.dumps(frame))
    proc = invoke(['node', str(TOOL), '--input', str(inp), '--audit', 'true'])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert len(result['profiles']) == 7
    assert result['causalSignalChecks'] >= 5
    profile = result['samples'][0]['profiles']['baseline']
    assert profile['phases']['ready'] == 1
    signal = profile['signals'][0]
    assert signal['confirmationDelay'] == 2
    assert signal['invalidation'] < signal['trigger'] < signal['chase']
    assert signal['paths'][0]['complete'] is True
    assert signal['paths'][-1]['complete'] is False


def test_missing_cache_asof_and_overwrite_fail_without_creating_data(tmp_path, frame):
    absent = tmp_path / 'absent.sqlite3'
    proc = invoke(['node', str(TOOL), '--cache', str(absent), '--symbol', 'TEST'])
    assert proc.returncode == 2
    assert not absent.exists()
    inp = tmp_path / 'frame.json'
    raw = json.dumps(frame)
    inp.write_text(raw)
    for args in [['--as-of', '2040-01-01'], ['--out', str(inp)]]:
        proc = invoke(['node', str(TOOL), '--input', str(inp), *args])
        assert proc.returncode == 2
        assert inp.read_text() == raw


def test_repo_skill_copies_have_same_offline_command():
    assert CLI.read_text() == (ROOT / 'skills/toss-api-skill/scripts/chartctl.py').read_text()


def test_default_cache_and_symlink_output_cannot_overwrite_source(tmp_path, frame):
    proc = invoke(['node', str(TOOL), '--out', str(ROOT / 'logs/market-cache.sqlite3')])
    assert proc.returncode == 2
    assert '덮어쓰기 금지' in proc.stderr
    inp = tmp_path / 'frame.json'
    inp.write_text(json.dumps(frame))
    link = tmp_path / 'same.json'
    link.symlink_to(inp)
    before = inp.read_bytes()
    proc = invoke(['node', str(TOOL), '--input', str(inp), '--out', str(link)])
    assert proc.returncode == 2
    assert inp.read_bytes() == before
