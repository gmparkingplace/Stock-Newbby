"""Signal and Execution Event Ledger (PY-05).

Provides immutable, idempotent event records for the stock-signal-lab
auditable trail.  Signal events capture the *decision* to trade (signal
bar close, indicator values, market/sector context).  Execution events
capture the *realisation* of that decision (t+1 open fill, fees, stop-loss
triggering).  Together they form a complete, replayable record of every
strategy action without re-executing the strategy logic.

The ledger is append-only with idempotent dedup by ``event_id``.  All
values are sanitised (numpy → Python, NaN → None) so that the resulting
JSONL files are valid and portable.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Union

import numpy as np

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# clean() — numpy / NaN sanitisation (same pattern as journal_p2c.py)
# ---------------------------------------------------------------------------

def clean(v: Any) -> Any:
    """Recursively convert numpy types to standard Python, NaN/Inf → None.

    Mirrors the pattern in ``scripts/journal_p2c.py`` so that ledger
    records are valid JSON and independent of the numpy runtime.
    Non-finite floats (NaN, +Inf, -Inf) become ``None`` because the
    JSONL ledger must contain only strict JSON values.
    """
    if isinstance(v, np.ndarray):
        return [clean(x) for x in v.tolist()]
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


# ---------------------------------------------------------------------------
# EventRecord — base dict protocol for all ledger records
# ---------------------------------------------------------------------------

@dataclass
class EventRecord:
    """Base fields shared by every ledger event.

    All events carry a unique ``event_id`` used for idempotent append.
    ``record_type`` distinguishes signal from execution events in the
    unified ``get_event`` lookup.
    """

    event_id: str
    run_id: str
    scenario_id: str
    record_type: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return clean(asdict(self))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EventRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# SignalEvent — decision record
# ---------------------------------------------------------------------------

@dataclass
class SignalEvent(EventRecord):
    """Immutable record of a trading signal at the bar-close decision point.

    Captures the *intent* to trade: which strategy fired, on which bar,
    with which indicator values and market/sector context.  The signal
    itself does **not** change any position — that happens only when the
    corresponding execution event is appended.

    Attributes
    ----------
    symbol : str
        Ticker / instrument identifier.
    strategy : str
        Strategy label (``"A"``, ``"B"``, ``"C"``, ``"F"``).
    rule_version : str
        Rule-set version string for reproducibility.
    timeframe : str
        Bar timeframe (``"1D"``, ``"1H"``, etc.).
    signal_date : str
        ISO date of the signal bar.
    signal_time : str
        ISO datetime of the bar close (timezone-aware where possible).
    side : str
        ``"entry"`` or ``"exit"``.
    reason_code : str
        Machine-readable reason code (e.g. ``"A_ENTRY_SMA_CROSS_UP"``).
    reason_desc : str
        Human-readable reason description.
    indicator_now : dict
        Indicator values at the signal bar.
    signal_price : float
        Close price at the signal bar.
    signal_status : str
        ``"active"`` — signal is live and pending execution.
    position_before_signal : int
        0 = flat, 1 = already holding at signal time.
    repeated_signal : bool
        True if the signal is a repeat (e.g. re-entry while already holding).
    market_ref : dict | None
        Market-wide context (trend, beta, corr, r2 for market ETF).
    sector_ref : dict | None
        Sector context (trend, beta, corr, r2 for sector ETF).
    """

    symbol: str = ""
    strategy: str = ""
    rule_version: str = ""
    timeframe: str = "1D"
    signal_date: str = ""
    signal_time: str = ""
    side: str = ""
    reason_code: str = ""
    reason_desc: str = ""
    indicator_now: dict[str, Any] = field(default_factory=dict)
    signal_price: float = 0.0
    signal_status: str = "active"
    position_before_signal: int = 0
    repeated_signal: bool = False
    market_ref: dict[str, Any] | None = None
    sector_ref: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Enforce record_type for signal events
        self.record_type = "signal_event"


# ---------------------------------------------------------------------------
# ExecutionEvent — realisation record
# ---------------------------------------------------------------------------

@dataclass
class ExecutionEvent(EventRecord):
    """Immutable record of a trade execution (or unfilled order).

    Captures the *realisation* of a signal: the t+1 open fill (or stop-loss
    trigger), fees, slippage, and the resulting position change.  Links
    back to the originating signal via ``source_signal_event_id``; for
    stop-loss exits this field is ``None``.

    Attributes
    ----------
    trade_id : str
        Identifier linking this execution to the accounting trade record.
    order_id : str | None
        Optional order identifier (used for unfilled orders).
    source_signal_event_id : str | None
        ``event_id`` of the :class:`SignalEvent` that triggered this
        execution.  ``None`` for stop-loss exits and other non-signal
        triggers.
    symbol : str
        Ticker / instrument identifier.
    strategy : str
        Strategy label.
    timeframe : str
        Bar timeframe.
    signal_date : str
        Date of the signal bar (the bar that produced the trigger).
    order_date : str
        Date of the bar where the order is placed (t+1).
    fill_date : str | None
        Actual fill date.  ``None`` when the order was not executed.
    side : str
        ``"buy"`` or ``"sell"``.
    quantity : float
        Number of shares (0.0 for unfilled orders).
    signal_price : float
        The signal bar close price (for reference).
    execution_price : float | None
        Actual fill price.  ``None`` when the order was not executed.
    commission : float
        Brokerage commission charged.
    slippage : float
        Slippage cost (absolute difference from signal price to fill).
    execution_status : str
        ``"pending"`` | ``"executed"`` | ``"unfilled"`` | ``"not_applicable"``.
    exit_reason : str | None
        Reason for the exit (e.g. ``"STOP_LOSS_2ATR"``,
        ``"SIGNAL_EXIT"``, ``"NO_NEXT_BAR"``).  ``None`` for entries.
    atr_at_entry : float | None
        ATR value at the entry bar (for trailing-stop context).
    peak_close : float | None
        Peak close price since entry (for trailing-stop context).
    stop_level : float | None
        Current stop-loss level.
    stop_trigger_time : str | None
        ISO datetime when the stop was triggered.
    position_before_execution : int
        0 = flat, 1 = holding before this execution.
    position_after_execution : int
        0 = flat, 1 = holding after this execution.
    unfilled_reason : str | None
        Reason the order was not filled (e.g. ``"no_next_bar"``,
        ``"insufficient_cash"``, ``"insufficient_volume"``,
        ``"trading_halt"``).  ``None`` when execution_status != "unfilled".
    """

    trade_id: str = ""
    order_id: str | None = None
    source_signal_event_id: str | None = None
    symbol: str = ""
    strategy: str = ""
    timeframe: str = "1D"
    signal_date: str = ""
    order_date: str = ""
    fill_date: str | None = None
    side: str = ""
    quantity: float = 0.0
    signal_price: float = 0.0
    execution_price: float | None = None
    commission: float = 0.0
    slippage: float = 0.0
    execution_status: str = "pending"
    exit_reason: str | None = None
    atr_at_entry: float | None = None
    peak_close: float | None = None
    stop_level: float | None = None
    stop_trigger_time: str | None = None
    position_before_execution: int = 0
    position_after_execution: int = 0
    unfilled_reason: str | None = None

    def __post_init__(self) -> None:
        self.record_type = "execution_event"


# ---------------------------------------------------------------------------
# EventLedger — append-only, idempotent, dual-file ledger
# ---------------------------------------------------------------------------

class EventLedger:
    """Append-only, idempotent event ledger with separate signal and
    execution streams.

    Signal events are written to ``signal_path`` and execution events to
    ``execution_path``.  Both files use JSONL format.  Appending is
    idempotent: re-appending an ``event_id`` that already exists is a no-op.
    All values are sanitised via :func:`clean` before writing.

    Parameters
    ----------
    signal_path : Path
        Path to the ``signal_events.jsonl`` file.
    execution_path : Path
        Path to the ``execution_events.jsonl`` file.

    Notes
    -----  
    The ledger is designed to be the **single source of truth** for
    reconstructing the full accounting trail.  After Phase 3, all
    downstream consumers (replay engines, dashboards, verification
    scripts) must read from these JSONL files rather than re-running
    strategies.
    """

    def __init__(self, signal_path: Path, execution_path: Path) -> None:
        self.signal_path = signal_path
        self.execution_path = execution_path
        self._signal_ids: set[str] = set()
        self._execution_ids: set[str] = set()
        # Load existing IDs from disk for idempotency on restart
        self._load_existing_ids()

    # -- idempotent append ---------------------------------------------------

    def append_signal(self, event: SignalEvent) -> bool:
        """Append a signal event, deduplicating by ``event_id``.

        Returns ``True`` if the event was written, ``False`` if it was
        already present (idempotent no-op).
        """
        if event.event_id in self._signal_ids:
            return False
        d = event.to_dict()
        # allow_nan=False: never persist NaN/Infinity tokens; a leak
        # raises here instead of corrupting the JSONL ledger.
        line = json.dumps(d, ensure_ascii=False, allow_nan=False) + "\n"
        self.signal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.signal_path.open("a", encoding="utf-8") as f:
            f.write(line)
        self._signal_ids.add(event.event_id)
        return True

    def append_execution(self, event: ExecutionEvent) -> bool:
        """Append an execution event, deduplicating by ``event_id``.

        Returns ``True`` if the event was written, ``False`` if it was
        already present.
        """
        if event.event_id in self._execution_ids:
            return False
        d = event.to_dict()
        # allow_nan=False: never persist NaN/Infinity tokens; a leak
        # raises here instead of corrupting the JSONL ledger.
        line = json.dumps(d, ensure_ascii=False, allow_nan=False) + "\n"
        self.execution_path.parent.mkdir(parents=True, exist_ok=True)
        with self.execution_path.open("a", encoding="utf-8") as f:
            f.write(line)
        self._execution_ids.add(event.event_id)
        return True

    def append(self, event: Union[SignalEvent, ExecutionEvent]) -> bool:
        """Dispatch to the correct append method based on event type.

        Returns ``True`` if the event was written, ``False`` if deduped.
        """
        if isinstance(event, SignalEvent):
            return self.append_signal(event)
        elif isinstance(event, ExecutionEvent):
            return self.append_execution(event)
        else:
            raise TypeError(f"Unsupported event type: {type(event).__name__}")

    # -- read-back -----------------------------------------------------------

    def get_signals(self, run_id: str) -> list[SignalEvent]:
        """Return all signal events for a given ``run_id``.

        Reads the signal JSONL file and filters by ``run_id``.
        """
        if not self.signal_path.exists():
            return []
        out: list[SignalEvent] = []
        with self.signal_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d.get("run_id") == run_id and d.get("record_type") == "signal_event":
                    out.append(SignalEvent.from_dict(d))
        return out

    def get_executions(self, run_id: str) -> list[ExecutionEvent]:
        """Return all execution events for a given ``run_id``."""
        if not self.execution_path.exists():
            return []
        out: list[ExecutionEvent] = []
        with self.execution_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if d.get("run_id") == run_id and d.get("record_type") == "execution_event":
                    out.append(ExecutionEvent.from_dict(d))
        return out

    def get_event(self, event_id: str) -> Union[SignalEvent, ExecutionEvent, None]:
        """Look up an event by its ``event_id`` across both streams.

        Searches signal events first, then execution events.  Returns
        ``None`` if not found.
        """
        # Search signals
        if self.signal_path.exists():
            with self.signal_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("event_id") == event_id:
                        return SignalEvent.from_dict(d)
        # Search executions
        if self.execution_path.exists():
            with self.execution_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("event_id") == event_id:
                        return ExecutionEvent.from_dict(d)
        return None

    # -- trade reconstruction ------------------------------------------------

    def rebuild_trades(
        self, run_id: str
    ) -> list[dict[str, Any]]:
        """Reconstruct a trade list from execution events for a given run.

        Pairs buy/sell execution events that share the same ``trade_id``.
        Only pairs where at least one side is ``executed`` are included.
        Unfilled orders are included as trade rows with ``status="unfilled"``.

        Returns a list of dicts suitable for ``pd.DataFrame`` conversion,
        with keys matching the trade CSV schema used by the existing
        ``trades_p3.py`` output.
        """
        executions = self.get_executions(run_id)
        # Group by trade_id
        trades_by_id: dict[str, list[ExecutionEvent]] = {}
        for e in executions:
            trades_by_id.setdefault(e.trade_id, []).append(e)

        trades: list[dict[str, Any]] = []
        for trade_id, events in trades_by_id.items():
            buys = [e for e in events if e.side == "buy"]
            sells = [e for e in events if e.side == "sell"]

            # Determine trade status
            buy_exec = next((b for b in buys if b.execution_status == "executed"), None)
            sell_exec = next((s for s in sells if s.execution_status == "executed"), None)
            buy_unfilled = next((b for b in buys if b.execution_status == "unfilled"), None)
            sell_unfilled = next((s for s in sells if s.execution_status == "unfilled"), None)

            if buy_exec and sell_exec:
                status = "completed"
            elif buy_exec or sell_exec:
                status = "open"
            elif buy_unfilled or sell_unfilled:
                status = "unfilled"
            else:
                status = "pending"

            # Build trade dict
            entry_sig_date = buy_exec.signal_date if buy_exec else (
                buy_unfilled.signal_date if buy_unfilled else ""
            )
            entry_exec_date = buy_exec.order_date if buy_exec else ""
            entry_price = (
                round(buy_exec.execution_price, 4)
                if buy_exec and buy_exec.execution_price is not None
                else ""
            )
            exit_sig_date = sell_exec.signal_date if sell_exec else (
                sell_unfilled.signal_date if sell_unfilled else ""
            )
            exit_exec_date = sell_exec.order_date if sell_exec else ""
            exit_price = (
                round(sell_exec.execution_price, 4)
                if sell_exec and sell_exec.execution_price is not None
                else ""
            )
            quantity = round(buy_exec.quantity, 6) if buy_exec else 0.0

            # PnL calculation for completed trades
            if buy_exec and sell_exec:
                entry_fee = buy_exec.commission + buy_exec.slippage
                exit_fee = sell_exec.commission + sell_exec.slippage
                cost = buy_exec.execution_price * buy_exec.quantity + entry_fee
                proceeds = sell_exec.execution_price * sell_exec.quantity - exit_fee
                pnl = round(proceeds - cost, 2)
                ret_pct = round(pnl / cost * 100, 3) if cost > 0 else ""
                fees = round(entry_fee + exit_fee, 2)
            else:
                pnl = ""
                ret_pct = ""
                fees = 0.0

            trade_dict: dict[str, Any] = {
                "trade_id": trade_id,
                "run_id": run_id,
                "symbol": buy_exec.symbol if buy_exec else (
                    buy_unfilled.symbol if buy_unfilled else ""
                ),
                "strategy": buy_exec.strategy if buy_exec else (
                    buy_unfilled.strategy if buy_unfilled else ""
                ),
                "status": status,
                "entry_signal_date": entry_sig_date,
                "entry_exec_date": entry_exec_date,
                "entry_price": entry_price,
                "exit_signal_date": exit_sig_date,
                "exit_exec_date": exit_exec_date,
                "exit_price": exit_price,
                "shares": quantity,
                "pnl": pnl,
                "ret_pct": ret_pct,
                "fees": fees,
            }

            # Add exit_reason if available
            if sell_exec and sell_exec.exit_reason:
                trade_dict["exit_reason"] = sell_exec.exit_reason
            elif sell_unfilled and sell_unfilled.exit_reason:
                trade_dict["exit_reason"] = sell_unfilled.exit_reason

            # Add stop-loss context if available (check buy first, then sell)
            for e in (buy_exec, sell_exec):
                if e is not None and e.atr_at_entry is not None:
                    trade_dict["atr_at_entry"] = e.atr_at_entry
                if e is not None and e.stop_level is not None:
                    trade_dict["stop_level"] = e.stop_level

            trades.append(trade_dict)

        return trades

    # -- internal ----------------------------------------------------------

    def _load_existing_ids(self) -> None:
        """Load existing event IDs from disk for idempotent append."""
        for path, ids in (
            (self.signal_path, self._signal_ids),
            (self.execution_path, self._execution_ids),
        ):
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            d = json.loads(line)
                            eid = d.get("event_id")
                            if eid:
                                ids.add(eid)
