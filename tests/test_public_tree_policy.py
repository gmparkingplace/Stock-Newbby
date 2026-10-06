import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('public_tree',
    Path(__file__).resolve().parents[1] / 'tools/check-public-tree.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def test_reject_credentials_local_artifacts_and_machine_paths():
    for name in ('.local.json', '.env.prod', 'logs/cache.json', 'user-credentials.txt',
                 'private-backups/repository.bundle', 'cache.sqlite3', 'docs/history/note.md'):
        assert policy.problems(Path(name), b'')
    # Build a path at runtime so this regression fixture itself is portable.
    assert policy.problems(Path('README.md'), b'/' + b'home' + b'/example/private.txt')
    assert policy.problems(Path('key.txt'), b'-----BEGIN ' + b'PRIVATE KEY-----')


def test_allow_empty_templates_and_portable_code():
    for name in ('toss-credentials.example.txt', '.local.example.json',
                 'scripts/local_http.py', 'SECURITY.md', 'tests/test_public_release.py'):
        assert not policy.problems(Path(name), b'Client Id:\nClient Secret:\n')
