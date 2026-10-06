"""Unit checks for tools/verify-package.py new guards. Offline, tmp dirs only."""
import hashlib
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'verify_package', Path(__file__).resolve().parents[1] / 'tools/verify-package.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def _tree(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    return tmp_path


def _manifest(rows):
    return {'files': [{'path': p, 'bytes': len(c),
                       'sha256': hashlib.sha256(c).hexdigest()}
                      for p, c in rows.items()]}


def _write_manifest(root, rows):
    (root / 'PACKAGE-MANIFEST.json').write_text(
        json.dumps(_manifest(rows), ensure_ascii=False))


def test_clean_tree_passes(tmp_path):
    files = {'a.py': b'x = 1\n', 'sub/b.js': b'// ok\n'}
    _tree(tmp_path, files)
    _write_manifest(tmp_path, files)
    assert m.check(tmp_path) == []


def test_hash_mismatch_and_missing_flagged(tmp_path):
    files = {'a.py': b'x = 1\n'}
    _tree(tmp_path, files)
    _write_manifest(tmp_path, {'a.py': b'x = 2\n', 'gone.py': b'?\n'})
    bad = m.check(tmp_path)
    assert 'a.py' in bad and 'gone.py' in bad


def test_traversal_entry_flagged(tmp_path):
    files = {'a.py': b'x\n'}
    _tree(tmp_path, files)
    rows = dict(files)
    _write_manifest(tmp_path, rows)
    manifest = json.loads((tmp_path / 'PACKAGE-MANIFEST.json').read_text())
    manifest['files'].append({'path': '../evil.py', 'bytes': 1, 'sha256': '0' * 64})
    manifest['files'].append({'path': '/abs.py', 'bytes': 1, 'sha256': '0' * 64})
    (tmp_path / 'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest))
    bad = m.check(tmp_path)
    assert 'traversal: ../evil.py' in bad and 'traversal: /abs.py' in bad


def test_forbidden_listed_flagged(tmp_path):
    files = {'a.py': b'x\n', '.local.json': b'{}\n'}
    _tree(tmp_path, files)
    rows = {'a.py': b'x\n', '.local.json': b'{}\n'}
    _write_manifest(tmp_path, rows)
    bad = m.check(tmp_path)
    assert 'forbidden: .local.json' in bad


def test_local_files_on_disk_not_flagged_when_unlisted(tmp_path):
    files = {'a.py': b'x\n', '.local.json': b'{}\n', '.env': b'K=1\n'}
    _tree(tmp_path, files)
    _write_manifest(tmp_path, {'a.py': b'x\n'})
    assert m.check(tmp_path) == []


def test_unlisted_packaged_file_flagged(tmp_path):
    files = {'a.py': b'x\n', 'new_mod.py': b'y\n'}
    _tree(tmp_path, files)
    _write_manifest(tmp_path, {'a.py': b'x\n'})
    assert m.check(tmp_path) == ['unlisted: new_mod.py']


def test_ignored_dirs_not_flagged(tmp_path):
    files = {'a.py': b'x\n', '.venv/lib/x.py': b'y\n', 'logs/out.log': b'z\n'}
    _tree(tmp_path, files)
    _write_manifest(tmp_path, {'a.py': b'x\n'})
    assert m.check(tmp_path) == []
