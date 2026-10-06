"""PY-06: Immutable Snapshots + Change Detection + Manifest.

Provides run-level metadata (Manifest, SymbolProfile), a snapshot
registry for versioned data directories, deterministic code hashing,
and field-level change detection between two snapshot directories.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lab.ledger.event import clean

SCHEMA_VERSION = "2.0"


# ---------------------------------------------------------------------------
# SymbolProfile — per-symbol market / adjustment metadata
# ---------------------------------------------------------------------------

@dataclass
class SymbolProfile:
    """Per-symbol metadata for reproducibility and auditability."""

    symbol: str
    market: str
    currency: str
    timezone: str
    observation_end: str
    price_adjustment_policy: dict[str, Any] = field(default_factory=dict)
    volume_adjustment_policy: dict[str, Any] = field(default_factory=dict)
    corporate_actions: list[dict[str, Any]] = field(default_factory=list)
    library_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SymbolProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Manifest — run-level metadata
# ---------------------------------------------------------------------------

@dataclass
class Manifest:
    """Run manifest recording all metadata needed for full reproducibility.

    Attributes
    ----------
    run_id : str
        Identifier for the experiment run.
    snapshot_id : str
        Identifier for the data snapshot used by this run.
    created_at : str
        ISO datetime when the manifest was created.
    schema_version : str
        Schema version for forward compatibility.
    data_hash : str
        SHA-256 of all data files in the snapshot directory.
    config_hash : str
        SHA-256 of the normalised configuration.
    code_hash : str
        SHA-256 of all related Python source files + dependency versions.
    symbols : dict[str, SymbolProfile]
        Per-symbol metadata keyed by symbol string.
    """

    run_id: str
    snapshot_id: str
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    data_hash: str = ""
    config_hash: str = ""
    code_hash: str = ""
    symbols: dict[str, SymbolProfile] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert SymbolProfile values to plain dicts
        d["symbols"] = {k: v.to_dict() for k, v in self.symbols.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        symbols = {k: SymbolProfile.from_dict(v) for k, v in d.get("symbols", {}).items()}
        kwargs = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "symbols"}
        return cls(symbols=symbols, **kwargs)


def write_manifest(manifest: Manifest, path: Path) -> Path:
    """Write manifest to JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d = manifest.to_dict()
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_manifest(path: Path) -> Manifest:
    """Load a Manifest from a JSON file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"manifest not found: {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    return Manifest.from_dict(d)


# ---------------------------------------------------------------------------
# code_hash() — deterministic hash of source files + dependencies
# ---------------------------------------------------------------------------

def code_hash(
    dirs: list[Path] | None = None,
    deps: dict[str, str] | None = None,
) -> str:
    """Deterministic SHA-256 hash of all Python source files and dependency versions.

    Parameters
    ----------
    dirs : list[Path], optional
        Directories to scan for ``.py`` files.  If ``None``, defaults to
        ``lab/`` and ``scripts/`` under the project root.
    deps : dict[str, str], optional
        Dependency versions to include (e.g. ``{"numpy": "2.5.2"}``).
        If ``None``, a minimal set is derived from the current environment.

    Returns
    -------
    str
        First 12 hex characters of the SHA-256 digest.
    """
    if dirs is None:
        ROOT = Path(__file__).resolve().parent.parent.parent
        dirs = [ROOT / "lab", ROOT / "scripts"]

    if deps is None:
        # Derive from current environment if not provided
        deps = {}
        for lib in ("numpy", "pandas", "pytest"):
            try:
                mod = __import__(lib)
                deps[lib] = getattr(mod, "__version__", "?")
            except ImportError:
                deps[lib] = "unavailable"

    h = hashlib.sha256()
    # Hash all .py files in sorted order.  Only paths relative to each
    # scanned directory are hashed (never absolute paths), so the digest
    # is stable when the repository is moved or checked out elsewhere.
    for d in sorted((Path(x) for x in dirs), key=str):
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.py"), key=str):
            # Anchor at the scanned directory's parent so that sibling
            # trees (e.g. lab/ vs scripts/) stay distinguishable.
            rel = p.relative_to(d.parent)
            h.update(str(rel).encode("utf-8"))
            h.update(p.read_bytes())

    # Include dependency versions
    h.update("|DEPS|".encode("utf-8"))
    for k in sorted(deps):
        h.update(f"{k}={deps[k]}".encode("utf-8"))

    return h.hexdigest()[:12]


# ---------------------------------------------------------------------------
# SnapshotRegistry — versioned snapshot management
# ---------------------------------------------------------------------------

class SnapshotRegistry:
    """Registry for immutable snapshot directories.

    Maintains a JSON index of registered snapshots under the snapshots root.
    Snapshots are copied (not moved) into the registry directory so that the
    original source is never modified.  Only read-only access is provided to
    registered snapshots.

    Parameters
    ----------
    snapshots_root : Path
        Root directory containing snapshot subdirectories and the registry index.
    """

    _INDEX_NAME = "_registry_index.json"
    _HEALTH_POINTER = "_latest_healthy.txt"

    def __init__(self, snapshots_root: Path) -> None:
        self.root = Path(snapshots_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / self._INDEX_NAME
        self._health_path = self.root / self._HEALTH_POINTER

    # -- internal helpers --------------------------------------------------

    def _load_index(self) -> dict[str, Any]:
        if self._index_path.exists():
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        return {"snapshots": {}}

    def _save_index(self, index: dict[str, Any]) -> None:
        self._index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # -- public API --------------------------------------------------------

    def register(
        self,
        snapshot_id: str,
        directory: Path,
        healthy: bool = True,
    ) -> Path:
        """Register a snapshot directory by copying it into the registry.

        Parameters
        ----------
        snapshot_id : str
            Unique identifier for this snapshot.
        directory : Path
            Source directory to copy.
        healthy : bool
            Whether this snapshot is considered healthy (passed quality checks).

        Returns
        -------
        Path
            Path to the registered snapshot in the registry.

        Raises
        ------
        FileExistsError
            If ``snapshot_id`` is already registered.
        """
        src = Path(directory)
        if not src.is_dir():
            raise NotADirectoryError(f"not a directory: {src}")

        dst = self.root / snapshot_id
        if dst.exists():
            raise FileExistsError(f"snapshot already registered: {snapshot_id}")

        # Copy directory (not move) to preserve original
        shutil.copytree(src, dst)

        index = self._load_index()
        index["snapshots"][snapshot_id] = {
            "path": str(dst),
            "healthy": healthy,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_index(index)

        # Update latest healthy pointer if this is healthy
        if healthy:
            self._health_path.write_text(snapshot_id, encoding="utf-8")

        return dst

    def get(self, snapshot_id: str) -> Path:
        """Resolve a registered snapshot directory.

        Returns the path to the registered snapshot.  Raises if not found.
        """
        index = self._load_index()
        entry = index["snapshots"].get(snapshot_id)
        if entry is None:
            raise KeyError(f"snapshot not registered: {snapshot_id}")
        p = Path(entry["path"])
        if not p.is_dir():
            raise RuntimeError(f"registered snapshot directory missing: {p}")
        return p

    def list_snapshots(self) -> list[str]:
        """List all registered snapshot IDs."""
        index = self._load_index()
        return sorted(index["snapshots"].keys())

    def latest_healthy(self) -> str | None:
        """Return the ID of the last successfully completed (healthy) snapshot.

        Returns ``None`` if no healthy snapshots exist.
        """
        if self._health_path.exists():
            sid = self._health_path.read_text(encoding="utf-8").strip()
            if sid:
                return sid
        # Fallback: search index for the last healthy entry
        index = self._load_index()
        for sid, entry in reversed(list(index["snapshots"].items())):
            if entry.get("healthy", False):
                return sid
        return None


# ---------------------------------------------------------------------------
# change_detection() — field-level diff between two snapshot directories
# ---------------------------------------------------------------------------

def change_detection(
    old_snapshot_dir: Path,
    new_snapshot_dir: Path,
) -> list[dict[str, Any]]:
    """Compare two snapshot directories at ``(symbol, timestamp, field)`` level.

    Scans ``{symbol}.jsonl`` files in both directories.  Each line is a JSON
    record expected to contain at least ``timestamp`` and OHLCV fields
    (``open``, ``high``, ``low``, ``close``, ``volume``).

    Parameters
    ----------
    old_snapshot_dir : Path
        Directory containing the previous snapshot data.
    new_snapshot_dir : Path
        Directory containing the new snapshot data.

    Returns
    -------
    list[dict]
        Change records, each with keys:
        ``action`` (``"added"|"removed"|"modified"``),
        ``symbol``, ``timestamp``, ``field``, ``old_value``, ``new_value``.
        ``old_value`` is ``None`` for additions; ``new_value`` is ``None`` for
        removals.  Only fields whose values actually differ are reported for
        ``"modified"`` changes.
    """
    old_dir = Path(old_snapshot_dir)
    new_dir = Path(new_snapshot_dir)

    # Load records indexed by (symbol, timestamp) → record dict
    def _load_records(directory: Path) -> dict[tuple[str, str], dict[str, Any]]:
        records: dict[tuple[str, str], dict[str, Any]] = {}
        if not directory.is_dir():
            return records
        for f in sorted(directory.glob("*.jsonl")):
            symbol = f.stem
            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    ts = d.get("timestamp", "")
                    records[(symbol, ts)] = d
        return records

    old_records = _load_records(old_dir)
    new_records = _load_records(new_dir)

    old_keys = set(old_records.keys())
    new_keys = set(new_records.keys())

    changes: list[dict[str, Any]] = []

    # Added records (in new, not in old)
    for key in sorted(new_keys - old_keys):
        symbol, ts = key
        d = new_records[key]
        # Report all fields as added
        for k, v in d.items():
            if k == "timestamp":
                continue
            changes.append({
                "action": "added",
                "symbol": symbol,
                "timestamp": ts,
                "field": k,
                "old_value": None,
                "new_value": v,
            })

    # Removed records (in old, not in new)
    for key in sorted(old_keys - new_keys):
        symbol, ts = key
        d = old_records[key]
        for k, v in d.items():
            if k == "timestamp":
                continue
            changes.append({
                "action": "removed",
                "symbol": symbol,
                "timestamp": ts,
                "field": k,
                "old_value": v,
                "new_value": None,
            })

    # Modified records (in both, with different values)
    for key in sorted(old_keys & new_keys):
        symbol, ts = key
        old_d = old_records[key]
        new_d = new_records[key]
        # Compare field by field (skip timestamp itself)
        all_fields = set(old_d.keys()) | set(new_d.keys())
        for k in sorted(all_fields):
            if k == "timestamp":
                continue
            old_val = old_d.get(k)
            new_val = new_d.get(k)
            # Use clean() for comparison (numpy → Python, NaN/Inf → None)
            old_clean = clean(old_val)
            new_clean = clean(new_val)
            if old_clean != new_clean:
                changes.append({
                    "action": "modified",
                    "symbol": symbol,
                    "timestamp": ts,
                    "field": k,
                    "old_value": old_clean,
                    "new_value": new_clean,
                })

    return changes
