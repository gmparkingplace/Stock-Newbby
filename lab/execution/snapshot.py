"""PY-06: Snapshot SHA-256 verification.

Manifest all files under a run snapshots directory with sha256
partial digests, such that a rerun can be verified to match a record."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHUNK_SIZE = 8192
MANIFEST_NAME = "_snapshot_manifest.json"


def hash_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Compute the SHA-256 hex digest of a file."""
    hasher = hashlib.sha256()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    with open(p, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def snapshot_manifest(directory: Path) -> dict[str, str]:
    """Create a snapshot manifest for all files in a directory."""
    d = Path(directory)
    if not d.is_dir():
        raise NotADirectoryError(f"not a directory: {d}")
    manifest: dict[str, str] = {}
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != MANIFEST_NAME:
            rel = p.relative_to(d)
            rel_str = str(rel).replace(chr(92), "/")
            digest = hash_file(p)
            manifest[rel_str] = digest
    return manifest


def verify_snapshot(directory: Path, expected: dict[str, str]) -> list[str]:
    """Verify that current files match the expected snapshot."""
    d = Path(directory)
    mismatches: list[str] = []
    current = set(
        str(p.relative_to(d)).replace(chr(92), "/")
        for p in d.rglob("*")
        if p.is_file() and p.name != MANIFEST_NAME
    )
    expected_keys = set(expected.keys())

    for key in sorted(expected_keys):
        if key not in current:
            mismatches.append(f"missing: {key}")
        else:
            file_path = d / key
            actual = hash_file(file_path)
            if actual != expected[key]:
                mismatches.append(
                    f"hash mismatch: {key} expected={expected[key][:16]}... actual={actual[:16]}..."
                )

    for key in sorted(current - expected_keys):
        mismatches.append(f"unexpected file: {key}")

    return mismatches


def write_snapshot_manifest(directory: Path, manifest: dict[str, str], output_path: Path | None = None) -> Path:
    """Write the snapshot manifest to a JSON file."""
    if output_path is None:
        output_path = Path(directory) / MANIFEST_NAME
    data = {
        "directory": str(directory),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": manifest,
    }
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def load_snapshot_manifest(manifest_path: Path) -> dict[str, str]:
    """Load a snapshot manifest from a JSON file."""
    p = Path(manifest_path)
    if not p.exists():
        raise FileNotFoundError(f"manifest not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid manifest JSON: {e}") from e
    if "files" not in data:
        raise ValueError(f"manifest missing files key: {p}")
    return data["files"]
