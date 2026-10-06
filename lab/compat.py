"""Compatibility layer between legacy ``scripts/`` artifacts and ``lab/``.

Old ``scripts/*.py`` files are frozen: this module only *reads* what they
produced (trades CSVs, OHLCV snapshots, indicator tables, equity curves)
and adapts it to lab types — never the reverse direction, and never by
importing script code (``scripts/`` is not a package and some modules need
uninstalled third-party dependencies).

- :func:`events_from_trade_rows` / :func:`events_from_trades_csv`:
  ``trades_{S}.csv`` rows → ``run_scenario`` event map.  Empty dates
  (``unfilled`` / open legs) are skipped; when two legs land on the same
  date the later row wins — the same dict-overwrite rule the legacy
  ``backtest_p4.py`` uses.
- :func:`bars_from_snapshot`: ``ohlcv.csv`` rows for one symbol, restricted
  to the evaluation calendar → ``(dates, opens, closes)`` with snapshot
  precision (not the rounded indicator CSV values).
- :func:`equity_frame`: lab result → legacy ``equity_{S}.csv`` row shape
  (``{date, equity}``, 2dp) so lab curves diff directly against published
  files.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Mapping

from lab.compare.scenario import ScenarioResult


def events_from_trade_rows(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, float]]:
    """Build a scenario event map from legacy trade rows."""
    events: dict[str, tuple[str, float]] = {}
    for r in rows:
        entry_date = str(r.get("entry_exec_date") or "")
        exit_date = str(r.get("exit_exec_date") or "")
        if entry_date:
            events[entry_date] = ("buy", float(r["entry_price"]))
        if exit_date:
            events[exit_date] = ("sell", float(r["exit_price"]))
    return events


def events_from_trades_csv(path: Path) -> dict[str, tuple[str, float]]:
    """Read a legacy ``trades_*.csv`` file into a scenario event map."""
    with open(path, newline="", encoding="utf-8") as f:
        return events_from_trade_rows(csv.DictReader(f))


def bars_from_snapshot(
    ohlcv_path: Path,
    symbol: str,
    eval_dates: list[str],
) -> tuple[list[str], list[float], list[float]]:
    """Return ``(dates, opens, closes)`` for ``symbol`` on ``eval_dates``.

    Bars follow the snapshot row order filtered to the calendar (both are
    chronological in practice).  Missing bars raise ``ValueError``.
    """
    wanted = set(eval_dates)
    by_date: dict[str, tuple[float, float]] = {}
    with open(ohlcv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["symbol"] == symbol and r["date"] in wanted:
                by_date[r["date"]] = (float(r["open"]), float(r["close"]))
    missing = [d for d in eval_dates if d not in by_date]
    if missing:
        raise ValueError(f"{symbol}: {len(missing)} bars missing, e.g. {missing[:3]}")
    dates = [d for d in eval_dates if d in by_date]
    opens = [by_date[d][0] for d in dates]
    closes = [by_date[d][1] for d in dates]
    return dates, opens, closes


def eval_dates_from_indicators(indicators_path: Path) -> list[str]:
    """Return the ``in_eval`` date list from a legacy indicators CSV."""
    with open(indicators_path, newline="", encoding="utf-8") as f:
        return [r["date"] for r in csv.DictReader(f)
                if str(r.get("in_eval")).strip().lower() == "true"]


def equity_frame(result: ScenarioResult) -> list[dict[str, Any]]:
    """Return legacy ``equity_{S}.csv`` rows (2dp) for a lab result."""
    return [{"date": d, "equity": round(v, 2)}
            for d, v in zip(result.dates, result.equity)]
