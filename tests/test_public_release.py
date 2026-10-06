"""Public exports never read the old example/records and reject leaked credentials."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_release', ROOT / 'tools/build-public-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_export_excludes_records_and_uses_empty_credentials(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    for name in release.ROOT_FILES:
        (source / name).write_text('')
    (source / '.gitignore').write_text('logs/\n.local.json\n')
    (source / 'package.json').write_text(json.dumps({'scripts': {'test': 'node tests/x.js && node prototype/fixture/check.js'}}))
    for name in ['README.md', 'TOSS.md', 'FEATURES.md']:
        p = source / 'distribution' / name
        p.parent.mkdir(exist_ok=True)
        p.write_text('public documentation')
    dash = source / 'results/dashboard'
    dash.mkdir(parents=True)
    sentinels = (b'fixture-private-old-data-4d71', b'fixture-private-record-9ac2')
    (dash / 'data.js').write_bytes(sentinels[0])
    (dash / 'data.json').write_bytes(sentinels[0])
    for rel in ['logs/user.sqlite3', 'docs/WORKLOG.md', 'docs/verification/user.png', 'data/account.json']:
        p = source / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(sentinels[1])
    monkeypatch.delenv('TOSS_CREDENTIALS_FILE', raising=False)
    monkeypatch.setattr(release, 'demo_data', lambda _: {'exps': [{'id': 'synthetic-demo'}]})
    dest = tmp_path / 'release'
    release.build(source, dest)
    for p in dest.rglob('*'):
        if p.is_file():
            assert not any(value in p.read_bytes() for value in sentinels)
    assert (dest / 'toss-credentials.example.txt').read_text() == 'Client Id:\nClient Secret:\n'
    assert json.loads((dest / '.local.example.json').read_text())['tossCredentialsFile'] == ''
    assert not (dest / '.local.json').exists()
    assert 'synthetic-demo' in (dest / 'results/dashboard/data.js').read_text()
    assert json.loads((dest / 'package.json').read_text())['scripts']['test'] == 'node tests/x.js'
    with pytest.raises(ValueError, match='empty'):
        release.build(source, dest)


def test_export_audit_reports_paths_without_revealing_secret(tmp_path):
    value = b'test-sensitive-value'
    (tmp_path / 'x.py').write_bytes(value)
    problems = release.audit(tmp_path, [value])
    assert problems == ['credential value: x.py']
    assert value.decode() not in '\n'.join(problems)


def test_portable_examples_and_symlinks(tmp_path):
    text = release.portable_text('python3 ~/.codex/skills/chart-assistant/scripts/chartctl.py', tmp_path)
    assert text == 'python3 ~/.codex/skills/chart-assistant/scripts/chartctl.py'
    (tmp_path / 'target.txt').write_text('safe')
    (tmp_path / 'link.txt').symlink_to(tmp_path / 'target.txt')
    assert release.audit(tmp_path) == ['symlink: link.txt']
