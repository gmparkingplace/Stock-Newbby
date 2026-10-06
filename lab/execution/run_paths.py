"""PY-01: Run path and artifact isolation.

Creates an isolated run directory tree under ``runs/`` so that new
experiments never collide with historical results under ``results/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_VERSION = "2.0"


@dataclass
class RunPaths:
    """Resolved directory layout for a single experiment run."""

    run_id: str
    snapshots_dir: Path
    artifacts_dir: Path
    results_dir: Path
    ledger_dir: Path
    events_dir: Path
    export_dir: Path
    run_manifest_path: Path

    @property
    def root(self) -> Path:
        """Top-level run directory: runs/{run_id}/."""
        return self.runs_root

    @property
    def runs_root(self) -> Path:
        return ROOT / "runs" / self.run_id


def create_run(profile: str, stamp: str | None = None) -> RunPaths:
    """Create an isolated run directory under runs/{run_id}/."""

    if stamp is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{profile}_{stamp}"
    run_root = ROOT / "runs" / run_id

    if run_root.exists():
        raise FileExistsError(f"run directory already exists: {run_root}")

    run_root.mkdir(parents=True, exist_ok=False)
    for sub in ("snapshots", "artifacts", "results", "ledgers", "events", "export"):
        (run_root / sub).mkdir()

    run_manifest_path = run_root / "run_manifest.json"

    return RunPaths(
        run_id=run_id,
        snapshots_dir=run_root / "snapshots",
        artifacts_dir=run_root / "artifacts",
        results_dir=run_root / "results",
        ledger_dir=run_root / "ledgers",
        events_dir=run_root / "events",
        export_dir=run_root / "export",
        run_manifest_path=run_manifest_path,
    )


def write_run_manifest(run_paths: RunPaths, meta: dict[str, Any] | None = None) -> Path:
    """Write the run manifest JSON."""
    meta = meta or {}
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_paths.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": meta.get("profile", ""),
        "inputs": meta.get("inputs", []),
        "params": meta.get("params", {}),
    }
    run_paths.run_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_paths.run_manifest_path


def validate_run_paths(run_paths: RunPaths) -> None:
    """Validate that all required directories exist and are consistent."""
    required = [
        ("snapshots", run_paths.snapshots_dir),
        ("artifacts", run_paths.artifacts_dir),
        ("results", run_paths.results_dir),
        ("ledgers", run_paths.ledger_dir),
        ("events", run_paths.events_dir),
        ("export", run_paths.export_dir),
        ("manifest", run_paths.run_manifest_path),
    ]
    run_root = run_paths.runs_root
    if not run_root.is_dir():
        raise RuntimeError(f"run directory does not exist: {run_root}")
    for name, p in required:
        if name == "manifest":
            continue
        if not p.is_dir():
            raise ValueError(f"missing required directory: {name} at {p}")
