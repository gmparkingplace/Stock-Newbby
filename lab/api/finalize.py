"""PY-12: Final run and maintenance.

Closing a run means exporting every result *and* proving the exports
survived the round trip; keeping it healthy means re-checking that on
demand.  :func:`finalize_run` does the former, :func:`verify_run` the
latter:

- ``finalize_run`` writes all scenario / comparison / evaluation exports,
  records ``run_summary.json`` (scenario ids + frozen study hashes), then
  reloads each exported scenario and asserts the equity curve survived
  bit-for-bit.  A reload mismatch raises — a half-written run never
  reports success.
- ``verify_run`` re-checks a closed run directory later (maintenance):
  manifest present and well-formed, exports parse, scenario calendars are
  internally consistent, evaluation reports carry their frozen hash.
  Returns a list of problems; empty means healthy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lab.api.export import (
    SCHEMA_VERSION,
    export_comparison,
    export_evaluation,
    export_scenario,
)
from lab.compare.scenario import ScenarioResult
from lab.execution.run_paths import RunPaths


def finalize_run(
    paths: RunPaths,
    scenarios: dict[str, ScenarioResult],
    table: dict[str, Any],
    period: str,
    reports: list[dict[str, Any]],
    order: list[str] | None = None,
) -> dict[str, Any]:
    """Export everything, verify the round trip, record the summary."""
    if not scenarios:
        raise ValueError("nothing to finalize")
    exported: list[str] = []
    for sid, result in scenarios.items():
        exported.append(str(export_scenario(result, paths.export_dir)))
    json_path, md_path = export_comparison(table, period, paths.export_dir, order)
    exported += [str(json_path), str(md_path)]
    for rep in reports:
        exported.append(str(export_evaluation(rep, paths.export_dir)))

    # Round-trip proof: reload each scenario export, compare equity.
    for sid, result in scenarios.items():
        raw = json.loads(
            (paths.export_dir / "scenarios" / f"{sid}.json").read_text(encoding="utf-8")
        )
        if raw["dates"] != result.dates or raw["equity"] != result.equity:
            raise ValueError(f"round-trip mismatch for scenario {sid!r}")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": paths.run_id,
        "period": period,
        "finalized_at": datetime.now(timezone.utc).isoformat(),
        "scenario_ids": list(scenarios.keys()),
        "frozen_hashes": sorted({r["frozen_hash"] for r in reports}),
        "exports": exported,
    }
    paths.results_dir.mkdir(parents=True, exist_ok=True)
    (paths.results_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def verify_run(run_dir: Path) -> list[str]:
    """Re-check a closed run directory; return problems (empty = healthy)."""
    problems: list[str] = []
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        problems.append("missing run_manifest.json")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"run_manifest.json unparsable: {e}")
        else:
            if manifest.get("run_id") != run_dir.name:
                problems.append("run_manifest run_id != directory name")

    export_dir = run_dir / "export"
    scenarios_dir = export_dir / "scenarios"
    if not scenarios_dir.is_dir():
        problems.append("missing export/scenarios/")
    else:
        for p in sorted(scenarios_dir.glob("*.json")):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                problems.append(f"{p.name} unparsable")
                continue
            if len(raw.get("dates", [])) != len(raw.get("equity", [])):
                problems.append(f"{p.name} dates/equity length mismatch")
    for name in ("comparison.json", "comparison.md"):
        if not (export_dir / name).exists():
            problems.append(f"missing export/{name}")
    eval_dir = export_dir / "evaluation"
    if eval_dir.is_dir():
        for p in sorted(eval_dir.glob("*.json")):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                problems.append(f"{p.name} unparsable")
                continue
            if not raw.get("frozen_hash"):
                problems.append(f"{p.name} missing frozen_hash")
    return problems
