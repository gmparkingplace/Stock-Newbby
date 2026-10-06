"""PY-10: Selection and evaluation phase separation.

Research-validity rule: strategy rules are *chosen* on the selection
(in-sample) segment and *reported* on the evaluation (out-of-sample,
holdout) segment.  Until now the boundary (``holdout_from`` in
``experiments/exp005`` and ``exp006``) was declarative — no code read it,
so nothing stopped evaluation numbers from leaking back into rule choice.
This module makes the separation mechanical:

- :func:`split_calendar` partitions a date calendar at the holdout
  boundary.  Comparison is by ISO date string, so a boundary that falls on
  a holiday (e.g. ``2025-01-01``) still works: evaluation starts at the
  first trading bar on or after the boundary.
- :func:`freeze_params` hashes the rule parameters; :class:`Study` records
  the hash at freeze time.
- :func:`evaluation_report` refuses to score the evaluation segment unless
  the caller presents the frozen hash — rules must be frozen *before* the
  holdout is opened.  Changing the rules requires a new freeze, which is a
  new study, not a revision of the old one.
- A round-trip belongs to the segment containing its *entry* date.
- :func:`walk_forward` generates anchored walk-forward folds for
  multi-window validation; every test fold starts strictly after its
  training fold ends.

Metric definitions are the PY-09 ones (re-based per segment, i.e. each
segment is measured as a continuous curve starting at its own first bar).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from lab.compare.performance import scenario_metrics
from lab.compare.scenario import ScenarioResult
from lab.ledger.event import clean


def freeze_params(params: dict[str, Any]) -> str:
    """Return the sha256 hex of the canonical JSON encoding of rule params.

    Key order and numpy/NaN values do not affect the hash.
    """
    canonical = json.dumps(clean(params), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def split_calendar(dates: list[str], boundary: str) -> tuple[list[str], list[str]]:
    """Split ``dates`` into (selection, evaluation) at ``boundary``.

    ``boundary`` is the first evaluation date (inclusive); it need not be
    a trading bar — evaluation starts at the first bar on or after it.
    Both segments must be non-empty.
    """
    if not dates:
        raise ValueError("dates must not be empty")
    selection = [d for d in dates if d < boundary]
    evaluation = [d for d in dates if d >= boundary]
    if not selection:
        raise ValueError(f"boundary {boundary!r} leaves selection empty")
    if not evaluation:
        raise ValueError(f"boundary {boundary!r} leaves evaluation empty")
    return selection, evaluation


@dataclass
class Study:
    """One selection/evaluation study with frozen rules."""

    study_id: str
    boundary: str
    rule_params: dict[str, Any] = field(default_factory=dict)
    frozen_hash: str = ""

    def freeze(self) -> str:
        """Freeze the current rule params; return and record the hash."""
        self.frozen_hash = freeze_params(self.rule_params)
        return self.frozen_hash

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict record of the study definition."""
        return {
            "study_id": self.study_id,
            "boundary": self.boundary,
            "rule_params": clean(self.rule_params),
            "frozen_hash": self.frozen_hash,
        }


def _segment_index(dates: list[str], boundary: str) -> int:
    selection, _ = split_calendar(dates, boundary)
    return len(selection)


def segment_metrics(result: ScenarioResult, boundary: str) -> dict[str, dict[str, float]]:
    """Return ``{"selection": ..., "evaluation": ...}`` metric dicts."""
    cut = _segment_index(result.dates, boundary)
    return {
        "selection": scenario_metrics(result.equity[:cut], result.held[:cut]),
        "evaluation": scenario_metrics(result.equity[cut:], result.held[cut:]),
    }


def _trip_stats(trips: list[dict[str, Any]], is_open: bool) -> dict[str, Any]:
    pnls = [t["pnl"] for t in trips]
    holds = [t["hold_bars"] for t in trips]
    return {
        "completed": len(trips),
        "open": 1 if is_open else 0,
        "win_rate_pct": round(sum(1 for v in pnls if v > 0) / len(pnls) * 100, 1) if pnls else "-",
        "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else "-",
        "avg_hold_bars": round(sum(holds) / len(holds), 1) if holds else "-",
    }


def segment_trades(result: ScenarioResult, boundary: str) -> dict[str, dict[str, Any]]:
    """Split round-trips by entry-date segment; ``open`` follows the curve tail."""
    cut = _segment_index(result.dates, boundary)
    sel = [t for t in result.round_trips if t["entry_date"] < boundary]
    eva = [t for t in result.round_trips if t["entry_date"] >= boundary]
    return {
        "selection": _trip_stats(sel, bool(result.held[cut - 1])),
        "evaluation": _trip_stats(eva, result.is_held),
    }


def evaluation_report(
    result: ScenarioResult,
    study: Study,
    frozen_hash: str,
) -> dict[str, Any]:
    """Score the evaluation segment; require the pre-freeze hash.

    Raises
    ------
    ValueError
        If the study was never frozen, or the presented hash does not
        match the frozen one (rules changed after freeze).
    """
    if not study.frozen_hash:
        raise ValueError(f"study {study.study_id!r} is not frozen")
    if frozen_hash != study.frozen_hash:
        raise ValueError(
            f"hash mismatch for study {study.study_id!r}: "
            "rules changed after freeze — freeze a new study instead"
        )
    metrics = segment_metrics(result, study.boundary)
    return {
        "study_id": study.study_id,
        "scenario_id": result.scenario_id,
        "boundary": study.boundary,
        "frozen_hash": study.frozen_hash,
        "metrics": metrics["evaluation"],
        "trades": segment_trades(result, study.boundary)["evaluation"],
    }


def walk_forward(
    dates: list[str],
    train_bars: int,
    test_bars: int,
    step_bars: int,
) -> Iterator[tuple[list[str], list[str]]]:
    """Yield anchored (train, test) folds over ``dates``.

    Training windows start at the first bar and grow; each test window of
    ``test_bars`` starts ``step_bars`` after the previous one and strictly
    after its training window ends.  Stops when a full test window no
    longer fits.
    """
    if train_bars < 1 or test_bars < 1 or step_bars < 1:
        raise ValueError("train/test/step sizes must be positive")
    start = 0
    while True:
        train_end = train_bars + start
        test_end = train_end + test_bars
        if test_end > len(dates):
            break
        yield dates[:train_end], dates[train_end:test_end]
        start += step_bars
