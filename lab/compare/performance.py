"""PY-09: Same-condition performance comparison.

Compares scenario results that share one evaluation calendar.  Metric
definitions mirror the legacy ``scripts/backtest_p4.py`` contract so that
lab-native results stay directly comparable with the published
``performance_p4.md`` tables:

- ``net_ret_pct``: ``(equity[-1] / equity[0] - 1) * 100``, rounded to 2dp.
- ``mdd_pct``: ``min(v / peak - 1) * 100`` over the curve, rounded to 2dp.
- ``exposure_pct``: ``sum(held) / n * 100``, rounded to 1dp.
- Halves: split at ``n // 2``; the second half is measured from its own
  start (``equity[mid]``), i.e. a continuous curve rebased at the split —
  identical to the legacy ``seg_metrics(eq[mid:], ...)``.
- Trade stats: completed round-trips paired by the scenario runner;
  ``"-"`` placeholders when there are no completed trips (B&H convention).

Same-condition enforcement: every result in one comparison must carry the
identical date list (same start, same end, same bar count — the invariant
``scripts/verify_p4.py`` checks per curve).  A mismatch raises
``ValueError`` instead of producing a misleading table.
"""

from __future__ import annotations

from typing import Any

from lab.compare.scenario import ScenarioResult


def max_drawdown(equity: list[float]) -> float:
    """Return the maximum drawdown as a fraction (<= 0)."""
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd


def scenario_metrics(equity: list[float], held: list[int]) -> dict[str, float]:
    """Return net-return / MDD / exposure metrics for one curve segment."""
    n = len(equity)
    return {
        "net_ret_pct": round((equity[-1] / equity[0] - 1) * 100, 2),
        "mdd_pct": round(max_drawdown(equity) * 100, 2),
        "exposure_pct": round(sum(held) / n * 100, 1),
    }


def trade_stats(result: ScenarioResult) -> dict[str, Any]:
    """Return completed-trade statistics for one scenario result."""
    trips = result.round_trips
    pnls = [t["pnl"] for t in trips]
    holds = [t["hold_bars"] for t in trips]
    return {
        "completed": len(trips),
        "open": 1 if result.is_held else 0,
        "win_rate_pct": round(sum(1 for v in pnls if v > 0) / len(pnls) * 100, 1) if pnls else "-",
        "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else "-",
        "avg_hold_bars": round(sum(holds) / len(holds), 1) if holds else "-",
    }


def compare(results: dict[str, ScenarioResult]) -> dict[str, Any]:
    """Compare scenarios run on the same evaluation calendar.

    Returns ``{scenario_id: {"full": ..., "h1": ..., "h2": ..., "trades": ...}}``.
    """
    if not results:
        raise ValueError("nothing to compare")
    ref = next(iter(results.values())).dates
    for sid, r in results.items():
        if r.dates != ref:
            raise ValueError(
                f"scenario {sid!r} calendar differs: "
                f"{r.dates[0] if r.dates else '?'}..{r.dates[-1] if r.dates else '?'} "
                f"({len(r.dates)} bars) vs {ref[0]}..{ref[-1]} ({len(ref)} bars)"
            )

    n = len(ref)
    mid = n // 2
    table: dict[str, Any] = {}
    for sid, r in results.items():
        table[sid] = {
            "full": scenario_metrics(r.equity, r.held),
            "h1": scenario_metrics(r.equity[:mid], r.held[:mid]),
            "h2": scenario_metrics(r.equity[mid:], r.held[mid:]),
            "trades": trade_stats(r),
        }
    return table


def to_markdown(
    table: dict[str, Any],
    period: str,
    order: list[str] | None = None,
) -> str:
    """Render a comparison table in the legacy ``performance_p4.md`` shape."""
    keys = order or list(table.keys())
    lines = [
        f"# Performance comparison ({period})",
        "",
        "- Same conditions: identical calendar, capital, and execution model "
        "(t+1 reference prices, FeeLedger + PositionTracker costs).",
        "",
        "| strategy | net_ret% | mdd% | exposure% | done | open | win% | avg_pnl | avg_hold |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for sid in keys:
        f, t = table[sid]["full"], table[sid]["trades"]
        lines.append(
            f"| {sid} | {f['net_ret_pct']} | {f['mdd_pct']} | {f['exposure_pct']} | "
            f"{t['completed']} | {t['open']} | {t['win_rate_pct']} | "
            f"{t['avg_pnl']} | {t['avg_hold_bars']} |"
        )
    lines += [
        "",
        "| strategy | h1_net% | h1_mdd% | h2_net% | h2_mdd% |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for sid in keys:
        h1, h2 = table[sid]["h1"], table[sid]["h2"]
        lines.append(
            f"| {sid} | {h1['net_ret_pct']} | {h1['mdd_pct']} | "
            f"{h2['net_ret_pct']} | {h2['mdd_pct']} |"
        )
    return "\n".join(lines) + "\n"
