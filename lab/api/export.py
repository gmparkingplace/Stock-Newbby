"""PY-11: Server and export compatibility.

Two consumers read research output, and both have a fixed payload contract:

- File mode: ``results/dashboard/index.html`` reads
  ``DASHBOARD_DATA.exps[].symbols[sym]`` from ``data.js`` (built by
  ``scripts/build_dashboard.py``).  Per-strategy entry/exit overlays are
  ``marks[strat] = [{time, side, info}]``; the chart keeps only the first
  entry while flat and the first exit while holding.
- Server mode: ``scripts/serve_dashboard.py`` serves ``frame()`` payloads
  on ``/api/lookup`` / ``/api/intraday`` and ``backtest()`` payloads on
  ``/api/backtest``.

This module is the lab-native side of that contract:

- :func:`scenario_marks` converts scenario fills to the dashboard
  ``marks`` shape (entry/exit with fill-price info).
- :func:`export_scenario` / :func:`export_comparison` /
  :func:`export_evaluation` persist lab results under a run's ``export/``
  directory as strict JSON plus the legacy markdown table.
- ``check_*`` validators assert the consumer-facing key contracts, so a
  future payload change fails loudly instead of rendering a silent empty
  chart.  The key sets mirror ``frame()`` / ``lookup()`` / ``backtest()``
  in ``scripts/serve_dashboard.py`` (read 2026-09-05).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from lab.compare.performance import to_markdown
from lab.compare.scenario import ScenarioResult
from lab.ledger.event import clean

SCHEMA_VERSION = "1.0"

# scripts/serve_dashboard.py::frame() return keys.
FRAME_KEYS = frozenset({"candles", "lines", "marks", "state", "fib", "levels"})
# lookup()/intraday() add these on top of frame().
LOOKUP_KEYS = FRAME_KEYS | frozenset({"symbol", "name", "strats", "trades", "weekly"})
# backtest() return keys; per[strategy] metric keys.
BACKTEST_KEYS = frozenset({"symbol", "name", "per", "trades", "bh", "note"})
BACKTEST_PER_KEYS = frozenset({"ret", "mdd", "exposure", "completed", "winrate"})
# Dashboard file-mode mark entry keys (build_dashboard.sym_data / frame()).
MARK_KEYS = frozenset({"time", "side", "info"})


def scenario_marks(result: ScenarioResult) -> dict[str, list[dict[str, str]]]:
    """Return ``{scenario_id: [{time, side, info}]}`` for chart overlays.

    Buys map to ``"entry"``, sells to ``"exit"`` — the only two sides the
    dashboard mark filter keeps.
    """
    marks = []
    for f in result.fills:
        side = "entry" if f.side == "buy" else "exit"
        marks.append({
            "time": f.date,
            "side": side,
            "info": f"{result.scenario_id} {f.side} {f.quantity:.4f} @ {f.price}",
        })
    return {result.scenario_id: marks}


def check_marks(marks: dict[str, Any]) -> list[str]:
    """Validate a dashboard ``marks`` mapping; return problems (empty = ok)."""
    problems = []
    if not isinstance(marks, dict):
        return ["marks must be a mapping"]
    for strat, entries in marks.items():
        if not isinstance(entries, list):
            problems.append(f"marks[{strat}] must be a list")
            continue
        for i, m in enumerate(entries):
            if not isinstance(m, dict) or set(m) != MARK_KEYS:
                problems.append(f"marks[{strat}][{i}] keys must be {sorted(MARK_KEYS)}")
            elif m["side"] not in ("entry", "exit"):
                problems.append(f"marks[{strat}][{i}] bad side {m['side']!r}")
    return problems


def check_frame(payload: dict[str, Any]) -> list[str]:
    """Validate an ``/api/lookup`` frame payload; return problems."""
    problems = []
    missing = FRAME_KEYS - set(payload)
    if missing:
        problems.append(f"frame missing keys: {sorted(missing)}")
    for c in payload.get("candles", []):
        if set(c) != {"time", "open", "high", "low", "close", "volume"}:
            problems.append(f"bad candle keys: {sorted(set(c))}")
            break
    problems.extend(check_marks(payload.get("marks", {})))
    return problems


def check_backtest(payload: dict[str, Any]) -> list[str]:
    """Validate an ``/api/backtest`` payload; return problems."""
    problems = []
    missing = BACKTEST_KEYS - set(payload)
    if missing:
        problems.append(f"backtest missing keys: {sorted(missing)}")
    for strat, per in (payload.get("per") or {}).items():
        if BACKTEST_PER_KEYS - set(per):
            problems.append(f"backtest per[{strat}] missing keys")
    return problems


def check_dashboard_data(data: dict[str, Any]) -> list[str]:
    """Validate a ``DASHBOARD_DATA`` (data.js) payload; return problems."""
    problems = []
    exps = data.get("exps")
    if not exps:
        return ["no exps"]
    for exp in exps:
        for sym, body in (exp.get("symbols") or {}).items():
            if "marks" in body:
                problems.extend(
                    f"{exp.get('id')}/{sym}: {p}" for p in check_marks(body["marks"])
                )
            if "candles" in body and not body["candles"]:
                problems.append(f"{exp.get('id')}/{sym}: empty candles")
    return problems


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def export_scenario(result: ScenarioResult, export_dir: Path) -> Path:
    """Write ``scenarios/{scenario_id}.json``; return the path."""
    return _write_json(export_dir / "scenarios" / f"{result.scenario_id}.json", {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": result.scenario_id,
        "config": asdict(result.config),
        "dates": result.dates,
        "equity": result.equity,
        "held": result.held,
        "fills": [asdict(f) for f in result.fills],
        "cost_summary": result.cost_summary,
        "round_trips": result.round_trips,
        "marks": scenario_marks(result),
    })


def export_comparison(
    table: dict[str, Any],
    period: str,
    export_dir: Path,
    order: list[str] | None = None,
) -> tuple[Path, Path]:
    """Write ``comparison.json`` + ``comparison.md``; return both paths."""
    payload = {"schema_version": SCHEMA_VERSION, "period": period,
               "order": order or list(table.keys()), "table": table}
    json_path = _write_json(export_dir / "comparison.json", payload)
    md_path = export_dir / "comparison.md"
    md_path.write_text(to_markdown(table, period, order), encoding="utf-8")
    return json_path, md_path


def export_evaluation(report: dict[str, Any], export_dir: Path) -> Path:
    """Write ``evaluation/{study_id}_{scenario_id}.json``; return the path."""
    name = f"{report['study_id']}_{report['scenario_id']}.json"
    return _write_json(export_dir / "evaluation" / name,
                       {"schema_version": SCHEMA_VERSION, **report})
