#!/usr/bin/env python3
"""Verify files included in the packaged baseline; local environments are excluded.

Checks (manifest = PACKAGE-MANIFEST.json):
1. listed files exist with matching sha256 (original check),
2. manifest paths cannot escape the root (absolute or `..`),
3. forbidden local/secret files are not listed in the manifest,
4. every packaged file on disk is listed (ignore rules mirror build-package.py).
"""
from pathlib import Path
import hashlib
import json
import sys

# tools/build-package.py의 제외 규칙과 동일하게 유지한다.
IGNORED_PARTS = {'.venv', '__pycache__', '.pytest_cache', '.git', 'logs', 'shots', 'work'}
SKIPPED_NAMES = {'.local.json', 'PACKAGE-MANIFEST.json', 'Open API.txt'}
FORBIDDEN_NAMES = {'.local.json', 'Open API.txt'}


def _is_forbidden(name: str) -> bool:
    return name in FORBIDDEN_NAMES or (name == '.env' or (name.startswith('.env.') and name != '.env.example'))


def manifest_rows(manifest: dict) -> list:
    return manifest.get('files', [])


def check_traversal(rows: list) -> list:
    """Manifest 경로 이탈 항목."""
    bad = []
    for row in rows:
        p = row.get('path', '')
        path = Path(p)
        if path.is_absolute() or '..' in path.parts:
            bad.append(f'traversal: {p}')
    return bad


def check_hashes(root: Path, rows: list) -> list:
    """목록 파일 해시 불일치·누락."""
    bad = []
    for row in rows:
        p = root / row['path']
        if (not p.is_file()
                or hashlib.sha256(p.read_bytes()).hexdigest() != row['sha256']):
            bad.append(row['path'])
    return bad


def check_forbidden(rows: list) -> list:
    """매니페스트에 금지 파일이 목록으로 들어갔는지 검사.

    작업 트리의 .local.json 등은 정상(패키징 제외·Git 무시)이라
    디스크 기준으로 판단하지 않는다.
    """
    return [f"forbidden: {row['path']}" for row in rows
            if _is_forbidden(Path(row.get('path', '')).name)]


def check_unlisted(root: Path, rows: list) -> list:
    """매니페스트에 없는 패키징 대상 파일."""
    listed = {row['path'] for row in rows}
    bad = []
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in IGNORED_PARTS for part in rel.parts):
            continue
        if p.name in SKIPPED_NAMES or _is_forbidden(p.name):
            continue
        if str(rel) not in listed:
            bad.append(f'unlisted: {rel}')
    return bad


def check(root: Path) -> list:
    manifest = json.loads((root / 'PACKAGE-MANIFEST.json').read_text())
    rows = manifest_rows(manifest)
    return (check_traversal(rows) + check_hashes(root, rows)
            + check_forbidden(rows) + check_unlisted(root, rows))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    bad = check(root)
    rows = manifest_rows(json.loads((root / 'PACKAGE-MANIFEST.json').read_text()))
    print(f"검사 {len(rows)}개 / 불일치 {len(bad)}개")
    for p in bad:
        print(p)
    return bool(bad)


if __name__ == '__main__':
    sys.exit(main())
