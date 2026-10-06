"""lab.execution — run isolation and snapshot integrity."""

from __future__ import annotations

from lab.execution.run_paths import RunPaths, create_run, validate_run_paths, write_run_manifest
from lab.execution.snapshot import (
    hash_file,
    load_snapshot_manifest,
    snapshot_manifest,
    verify_snapshot,
    write_snapshot_manifest,
)

__all__ = [
    "RunPaths",
    "create_run",
    "validate_run_paths",
    "write_run_manifest",
    "hash_file",
    "load_snapshot_manifest",
    "snapshot_manifest",
    "verify_snapshot",
    "write_snapshot_manifest",
]
