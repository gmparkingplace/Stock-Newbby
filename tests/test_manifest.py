"""Smoke tests for lab.ledger.manifest — Manifest, SnapshotRegistry, Change Detection (PY-06).

Run: ``cd ~/Desktop/stock-signal-lab && python -m pytest tests/test_manifest.py -v``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab.ledger.manifest import (
    Manifest,
    SnapshotRegistry,
    SymbolProfile,
    change_detection,
    code_hash,
    load_manifest,
    write_manifest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_manifest() -> Manifest:
    """A manifest with per-symbol metadata."""
    sp = SymbolProfile(
        symbol="005930",
        market="KRX",
        currency="KRW",
        timezone="Asia/Seoul",
        observation_end="2026-01-20",
        price_adjustment_policy={"type": "split-adjusted", "volume": "raw"},
        volume_adjustment_policy={"type": "raw"},
        corporate_actions=[{"date": "2025-06-15", "split_ratio": 2.0, "type": "stock_split"}],
        library_versions={"numpy": "2.5.2", "pandas": "2.2.0"},
    )
    sp2 = SymbolProfile(
        symbol="SATL",
        market="NASDAQ",
        currency="USD",
        timezone="America/New_York",
        observation_end="2026-01-20",
        price_adjustment_policy={"type": "adjusted-close", "volume": "unadjusted"},
        volume_adjustment_policy={"type": "unadjusted"},
        corporate_actions=[],
        library_versions={"numpy": "2.5.2"},
    )
    return Manifest(
        run_id="run_001",
        snapshot_id="snap_001",
        created_at="2026-01-21T00:00:00+00:00",
        schema_version="2.0",
        data_hash="abc123def456",
        config_hash="cfg789ghi012",
        code_hash="ch345jkl678",
        symbols={"005930": sp, "SATL": sp2},
    )


@pytest.fixture
def registry(tmp_path: Path) -> SnapshotRegistry:
    """SnapshotRegistry rooted in a temp directory."""
    return SnapshotRegistry(snapshots_root=tmp_path / "snapshots")


@pytest.fixture
def snapshot_dir_a(tmp_path: Path) -> Path:
    """Old snapshot directory with sample JSONL data."""
    d = tmp_path / "snap_a"
    d.mkdir(parents=True, exist_ok=True)
    # Symbol 005930
    data = [
        {"timestamp": "2026-01-15", "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000},
        {"timestamp": "2026-01-16", "open": 103.0, "high": 106.0, "low": 102.0, "close": 104.0, "volume": 1200},
    ]
    (d / "005930.jsonl").write_text("\n".join(json.dumps(r) for r in data) + "\n", encoding="utf-8")
    # Symbol SATL
    data2 = [
        {"timestamp": "2026-01-15", "open": 50.0, "high": 52.0, "low": 49.0, "close": 51.0, "volume": 500},
    ]
    (d / "SATL.jsonl").write_text("\n".join(json.dumps(r) for r in data2) + "\n", encoding="utf-8")
    return d


@pytest.fixture
def snapshot_dir_b(snapshot_dir_a: Path, tmp_path: Path) -> Path:
    """New snapshot directory with some changes vs snapshot_dir_a."""
    d = tmp_path / "snap_b"
    d.mkdir(parents=True, exist_ok=True)
    # 005930: modified close on 2026-01-15, removed 2026-01-16, added 2026-01-17
    data = [
        {"timestamp": "2026-01-15", "open": 100.0, "high": 105.0, "low": 99.0, "close": 107.0, "volume": 1000},
        {"timestamp": "2026-01-17", "open": 104.0, "high": 108.0, "low": 103.0, "close": 106.0, "volume": 900},
    ]
    (d / "005930.jsonl").write_text("\n".join(json.dumps(r) for r in data) + "\n", encoding="utf-8")
    # SATL: unchanged
    data2 = [
        {"timestamp": "2026-01-15", "open": 50.0, "high": 52.0, "low": 49.0, "close": 51.0, "volume": 500},
    ]
    (d / "SATL.jsonl").write_text("\n".join(json.dumps(r) for r in data2) + "\n", encoding="utf-8")
    return d


@pytest.fixture
def snapshot_dir_identical(snapshot_dir_a: Path, tmp_path: Path) -> Path:
    """A copy of snapshot_dir_a (identical)."""
    d = tmp_path / "snap_a_copy"
    d.mkdir(parents=True, exist_ok=True)
    for f in snapshot_dir_a.glob("*.jsonl"):
        (d / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Tests: Manifest
# ---------------------------------------------------------------------------

class TestManifest:
    def test_creation(self, sample_manifest: Manifest) -> None:
        assert sample_manifest.run_id == "run_001"
        assert sample_manifest.snapshot_id == "snap_001"
        assert sample_manifest.schema_version == "2.0"
        assert sample_manifest.data_hash == "abc123def456"
        assert "005930" in sample_manifest.symbols
        assert "SATL" in sample_manifest.symbols

    def test_to_dict_roundtrip(self, sample_manifest: Manifest) -> None:
        d = sample_manifest.to_dict()
        assert d["run_id"] == "run_001"
        assert d["snapshot_id"] == "snap_001"
        assert d["schema_version"] == "2.0"
        assert isinstance(d["symbols"], dict)
        assert d["symbols"]["005930"]["market"] == "KRX"
        assert d["symbols"]["SATL"]["currency"] == "USD"

        # Restore from dict
        m = Manifest.from_dict(d)
        assert m.run_id == "run_001"
        assert m.symbols["005930"].market == "KRX"
        assert m.symbols["SATL"].observation_end == "2026-01-20"
        assert m.symbols["005930"].corporate_actions[0]["split_ratio"] == 2.0

    def test_write_load_manifest(self, sample_manifest: Manifest, tmp_path: Path) -> None:
        p = write_manifest(sample_manifest, tmp_path / "manifest.json")
        assert p.exists()
        m = load_manifest(p)
        assert m.run_id == "run_001"
        assert m.snapshot_id == "snap_001"
        assert m.code_hash == "ch345jkl678"
        assert m.symbols["005930"].market == "KRX"

    def test_load_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "nonexistent.json")

    def test_symbol_profile_fields(self, sample_manifest: Manifest) -> None:
        sp = sample_manifest.symbols["005930"]
        assert sp.symbol == "005930"
        assert sp.market == "KRX"
        assert sp.currency == "KRW"
        assert sp.timezone == "Asia/Seoul"
        assert sp.observation_end == "2026-01-20"
        assert sp.price_adjustment_policy["type"] == "split-adjusted"
        assert sp.volume_adjustment_policy["type"] == "raw"
        assert len(sp.corporate_actions) == 1
        assert sp.library_versions["numpy"] == "2.5.2"


# ---------------------------------------------------------------------------
# Tests: code_hash
# ---------------------------------------------------------------------------

class TestCodeHash:
    def test_determinism(self) -> None:
        """Same dirs + deps → same hash."""
        ROOT = Path(__file__).resolve().parent.parent
        h1 = code_hash(dirs=[ROOT / "lab"], deps={"numpy": "2.5.2"})
        h2 = code_hash(dirs=[ROOT / "lab"], deps={"numpy": "2.5.2"})
        assert h1 == h2
        assert len(h1) == 12

    def test_includes_dependencies(self) -> None:
        """Changing deps changes the hash."""
        ROOT = Path(__file__).resolve().parent.parent
        h1 = code_hash(dirs=[ROOT / "lab"], deps={"numpy": "2.5.2"})
        h2 = code_hash(dirs=[ROOT / "lab"], deps={"numpy": "9.9.9"})
        assert h1 != h2

    def test_includes_source_files(self) -> None:
        """Changing source files changes the hash."""
        ROOT = Path(__file__).resolve().parent.parent
        h1 = code_hash(dirs=[ROOT / "lab"], deps={"numpy": "2.5.2"})
        # Use a different directory (empty) → different hash
        h2 = code_hash(dirs=[ROOT / "tests"], deps={"numpy": "2.5.2"})
        assert h1 != h2

    def test_truncated_to_12_chars(self) -> None:
        h = code_hash(dirs=[], deps={})
        assert len(h) == 12
        # Should be valid hex
        int(h, 16)


# ---------------------------------------------------------------------------
# Tests: SnapshotRegistry
# ---------------------------------------------------------------------------

class TestSnapshotRegistry:
    def test_register_and_get(self, registry: SnapshotRegistry, snapshot_dir_a: Path) -> None:
        dst = registry.register("snap_a", snapshot_dir_a)
        assert dst.exists()
        assert (dst / "005930.jsonl").exists()
        # get resolves back
        resolved = registry.get("snap_a")
        assert resolved == dst
        assert (resolved / "SATL.jsonl").exists()

    def test_register_duplicate_raises(self, registry: SnapshotRegistry, snapshot_dir_a: Path) -> None:
        registry.register("snap_a", snapshot_dir_a)
        with pytest.raises(FileExistsError):
            registry.register("snap_a", snapshot_dir_a)

    def test_register_invalid_dir(self, registry: SnapshotRegistry, tmp_path: Path) -> None:
        with pytest.raises(NotADirectoryError):
            registry.register("snap_bad", tmp_path / "nonexistent")

    def test_list_snapshots(self, registry: SnapshotRegistry, snapshot_dir_a: Path, tmp_path: Path) -> None:
        registry.register("snap_a", snapshot_dir_a)
        # Create another source dir
        d2 = tmp_path / "snap_b_src"
        d2.mkdir(parents=True, exist_ok=True)
        (d2 / "TEST.jsonl").write_text('{"timestamp": "2026-01-15", "close": 99.0}\n', encoding="utf-8")
        registry.register("snap_b", d2)
        ids = registry.list_snapshots()
        assert ids == ["snap_a", "snap_b"]

    def test_latest_healthy(self, registry: SnapshotRegistry, snapshot_dir_a: Path, tmp_path: Path) -> None:
        # Register an unhealthy snapshot first
        d_unhealthy = tmp_path / "unhealthy_src"
        d_unhealthy.mkdir(parents=True, exist_ok=True)
        (d_unhealthy / "BAD.jsonl").write_text("", encoding="utf-8")
        registry.register("snap_bad", d_unhealthy, healthy=False)
        assert registry.latest_healthy() is None

        # Now register a healthy one
        dst = registry.register("snap_good", snapshot_dir_a, healthy=True)
        assert registry.latest_healthy() == "snap_good"

    def test_get_missing(self, registry: SnapshotRegistry) -> None:
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_original_preserved(self, registry: SnapshotRegistry, snapshot_dir_a: Path) -> None:
        """register() must copy, not move — original must still exist."""
        dst = registry.register("snap_a", snapshot_dir_a)
        # Original still intact
        assert (snapshot_dir_a / "005930.jsonl").exists()
        # Copy also intact
        assert (dst / "005930.jsonl").exists()


# ---------------------------------------------------------------------------
# Tests: change_detection
# ---------------------------------------------------------------------------

class TestChangeDetection:
    def test_identical_snapshots(self, snapshot_dir_a: Path, snapshot_dir_identical: Path) -> None:
        changes = change_detection(snapshot_dir_a, snapshot_dir_identical)
        assert changes == []

    def test_modified_field(self, snapshot_dir_a: Path, snapshot_dir_b: Path) -> None:
        """close changed on 005930@2026-01-15 (103.0 → 107.0)."""
        changes = change_detection(snapshot_dir_a, snapshot_dir_b)
        mods = [c for c in changes if c["action"] == "modified"]
        assert len(mods) == 1
        m = mods[0]
        assert m["symbol"] == "005930"
        assert m["timestamp"] == "2026-01-15"
        assert m["field"] == "close"
        assert m["old_value"] == 103.0
        assert m["new_value"] == 107.0

    def test_removed_row(self, snapshot_dir_a: Path, snapshot_dir_b: Path) -> None:
        """2026-01-16 was removed from 005930."""
        changes = change_detection(snapshot_dir_a, snapshot_dir_b)
        removed = [c for c in changes if c["action"] == "removed" and c["symbol"] == "005930"]
        # Should have removed entries for all fields of the 01-16 record
        assert any(c["timestamp"] == "2026-01-16" for c in removed)
        # Check specific field
        close_removed = next(
            c for c in removed if c["timestamp"] == "2026-01-16" and c["field"] == "close"
        )
        assert close_removed["old_value"] == 104.0
        assert close_removed["new_value"] is None

    def test_added_row(self, snapshot_dir_a: Path, snapshot_dir_b: Path) -> None:
        """2026-01-17 was added to 005930."""
        changes = change_detection(snapshot_dir_a, snapshot_dir_b)
        added = [c for c in changes if c["action"] == "added" and c["symbol"] == "005930"]
        assert any(c["timestamp"] == "2026-01-17" for c in added)
        close_added = next(
            c for c in added if c["timestamp"] == "2026-01-17" and c["field"] == "close"
        )
        assert close_added["old_value"] is None
        assert close_added["new_value"] == 106.0

    def test_unchanged_symbol(self, snapshot_dir_a: Path, snapshot_dir_b: Path) -> None:
        """SATL should have no changes."""
        changes = change_detection(snapshot_dir_a, snapshot_dir_b)
        satl_changes = [c for c in changes if c["symbol"] == "SATL"]
        assert satl_changes == []

    def test_missing_old_dir(self, tmp_path: Path, snapshot_dir_b: Path) -> None:
        """If old dir doesn't exist, all records in new are added."""
        changes = change_detection(tmp_path / "nonexistent", snapshot_dir_b)
        added = [c for c in changes if c["action"] == "added"]
        # Should have added entries for all fields
        assert len(added) > 0

    def test_field_granularity(self, tmp_path: Path) -> None:
        """Only changed fields are reported, not all fields."""
        old = tmp_path / "old_snap"
        old.mkdir(parents=True, exist_ok=True)
        new = tmp_path / "new_snap"
        new.mkdir(parents=True, exist_ok=True)

        old_data = [{"timestamp": "2026-01-15", "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000}]
        new_data = [{"timestamp": "2026-01-15", "open": 100.0, "high": 105.0, "low": 99.0, "close": 108.0, "volume": 1000}]

        (old / "SYM.jsonl").write_text("\n".join(json.dumps(r) for r in old_data) + "\n", encoding="utf-8")
        (new / "SYM.jsonl").write_text("\n".join(json.dumps(r) for r in new_data) + "\n", encoding="utf-8")

        changes = change_detection(old, new)
        # Only close should be modified, not open/high/low/volume
        assert len(changes) == 1
        assert changes[0]["field"] == "close"
        assert changes[0]["old_value"] == 103.0
        assert changes[0]["new_value"] == 108.0
