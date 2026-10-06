"""Smoke tests for lab.ledger.event — Signal & Execution Event Ledger (PY-05).

Run: ``cd ~/Desktop/stock-signal-lab && python -m pytest tests/test_event_ledger.py -v``
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lab.ledger.event import EventLedger, ExecutionEvent, SignalEvent, clean


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path: Path) -> EventLedger:
    """Create an EventLedger backed by temp files."""
    sig_path = tmp_path / "events" / "signal_events.jsonl"
    exec_path = tmp_path / "events" / "execution_events.jsonl"
    return EventLedger(signal_path=sig_path, execution_path=exec_path)


@pytest.fixture
def sig_event() -> SignalEvent:
    """A sample signal event for strategy A entry."""
    return SignalEvent(
        event_id="run_001|A|005930|2026-01-15|entry",
        run_id="run_001",
        scenario_id="S01",
        symbol="005930",
        strategy="A",
        rule_version="exp002",
        timeframe="1D",
        signal_date="2026-01-15",
        signal_time="2026-01-15T15:30:00+09:00",
        side="entry",
        reason_code="A_ENTRY_SMA_CROSS_UP",
        reason_desc="SMA(20) crossed above SMA(60)",
        indicator_now={"sma_20": 102.5, "sma_60": 99.8, "rsi_14": 62.3},
        signal_price=100.0,
        signal_status="active",
        position_before_signal=0,
        repeated_signal=False,
        market_ref={"trend": "up", "beta": 0.85, "corr_1d": 0.72, "r2": 0.55},
        sector_ref={"trend": "up", "beta": 0.90, "corr_1d": 0.81, "r2": 0.62},
    )


@pytest.fixture
def exec_event(sig_event: SignalEvent) -> ExecutionEvent:
    """A sample execution event linked to the signal event."""
    return ExecutionEvent(
        event_id="run_001|A|005930|2026-01-16|fill",
        run_id="run_001",
        scenario_id="S01",
        trade_id="T001",
        source_signal_event_id=sig_event.event_id,
        symbol="005930",
        strategy="A",
        timeframe="1D",
        signal_date="2026-01-15",
        order_date="2026-01-16",
        fill_date="2026-01-16",
        side="buy",
        quantity=100.0,
        signal_price=100.0,
        execution_price=100.5,
        commission=5.025,
        slippage=50.0,
        execution_status="executed",
        position_before_execution=0,
        position_after_execution=1,
    )


@pytest.fixture
def stop_event() -> ExecutionEvent:
    """A stop-loss execution event with no source signal."""
    return ExecutionEvent(
        event_id="run_001|A|005930|2026-01-20|stop",
        run_id="run_001",
        scenario_id="S01",
        trade_id="T001",
        source_signal_event_id=None,
        symbol="005930",
        strategy="A",
        timeframe="1D",
        signal_date="2026-01-20",
        order_date="2026-01-21",
        fill_date="2026-01-21",
        side="sell",
        quantity=100.0,
        signal_price=98.0,
        execution_price=95.0,
        commission=4.75,
        slippage=30.0,
        execution_status="executed",
        exit_reason="STOP_LOSS_2ATR",
        atr_at_entry=4.5,
        peak_close=103.0,
        stop_level=94.0,
        stop_trigger_time="2026-01-20T15:30:00+09:00",
        position_before_execution=1,
        position_after_execution=0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSignalEvent:
    def test_creation(self, sig_event: SignalEvent) -> None:
        assert sig_event.event_id == "run_001|A|005930|2026-01-15|entry"
        assert sig_event.record_type == "signal_event"
        assert sig_event.signal_status == "active"
        assert sig_event.side == "entry"
        assert sig_event.reason_code == "A_ENTRY_SMA_CROSS_UP"
        assert sig_event.position_before_signal == 0
        assert sig_event.indicator_now["rsi_14"] == 62.3
        assert sig_event.market_ref["beta"] == 0.85

    def test_to_dict_clean(self, sig_event: SignalEvent) -> None:
        d = sig_event.to_dict()
        assert d["record_type"] == "signal_event"
        assert d["event_id"] == sig_event.event_id
        # indicator_now should be plain Python types
        assert isinstance(d["indicator_now"]["rsi_14"], (int, float))

    def test_from_dict_roundtrip(self, sig_event: SignalEvent) -> None:
        d = sig_event.to_dict()
        restored = SignalEvent.from_dict(d)
        assert restored.event_id == sig_event.event_id
        assert restored.record_type == "signal_event"
        assert restored.side == sig_event.side
        assert restored.indicator_now == sig_event.indicator_now


class TestExecutionEvent:
    def test_creation(self, exec_event: ExecutionEvent) -> None:
        assert exec_event.event_id == "run_001|A|005930|2026-01-16|fill"
        assert exec_event.record_type == "execution_event"
        assert exec_event.execution_status == "executed"
        assert exec_event.source_signal_event_id is not None
        assert exec_event.position_before_execution == 0
        assert exec_event.position_after_execution == 1

    def test_stop_event(self, stop_event: ExecutionEvent) -> None:
        assert stop_event.source_signal_event_id is None
        assert stop_event.exit_reason == "STOP_LOSS_2ATR"
        assert stop_event.atr_at_entry == 4.5
        assert stop_event.peak_close == 103.0
        assert stop_event.stop_level == 94.0

    def test_to_dict_clean(self, exec_event: ExecutionEvent) -> None:
        d = exec_event.to_dict()
        assert d["record_type"] == "execution_event"
        assert d["execution_status"] == "executed"
        assert d["source_signal_event_id"] is not None

    def test_from_dict_roundtrip(self, exec_event: ExecutionEvent) -> None:
        d = exec_event.to_dict()
        restored = ExecutionEvent.from_dict(d)
        assert restored.event_id == exec_event.event_id
        assert restored.record_type == "execution_event"
        assert restored.execution_status == exec_event.execution_status
        assert restored.source_signal_event_id == exec_event.source_signal_event_id


class TestEventLedger:
    def test_append_signal(self, ledger: EventLedger, sig_event: SignalEvent) -> None:
        result = ledger.append_signal(sig_event)
        assert result is True
        # Verify file was written
        assert ledger.signal_path.exists()
        # Verify event is recoverable
        signals = ledger.get_signals("run_001")
        assert len(signals) == 1
        assert signals[0].event_id == sig_event.event_id

    def test_append_execution(self, ledger: EventLedger, sig_event: SignalEvent,
                             exec_event: ExecutionEvent) -> None:
        ledger.append_signal(sig_event)
        result = ledger.append_execution(exec_event)
        assert result is True
        # Verify file was written
        assert ledger.execution_path.exists()
        # Verify event is recoverable
        execs = ledger.get_executions("run_001")
        assert len(execs) == 1
        assert execs[0].event_id == exec_event.event_id

    def test_append_dispatch(self, ledger: EventLedger, sig_event: SignalEvent,
                            exec_event: ExecutionEvent) -> None:
        r1 = ledger.append(sig_event)
        r2 = ledger.append(exec_event)
        assert r1 is True
        assert r2 is True

    def test_idempotent_append(self, ledger: EventLedger, sig_event: SignalEvent,
                              exec_event: ExecutionEvent) -> None:
        ledger.append_signal(sig_event)
        ledger.append_execution(exec_event)
        # Re-append same events
        r1 = ledger.append_signal(sig_event)
        r2 = ledger.append_execution(exec_event)
        assert r1 is False  # already present
        assert r2 is False  # already present
        # Verify no duplicates on disk
        assert len(ledger.get_signals("run_001")) == 1
        assert len(ledger.get_executions("run_001")) == 1

    def test_get_event_by_id(self, ledger: EventLedger, sig_event: SignalEvent,
                            exec_event: ExecutionEvent) -> None:
        ledger.append(sig_event)
        ledger.append(exec_event)
        # Look up signal event
        e = ledger.get_event(sig_event.event_id)
        assert e is not None
        assert isinstance(e, SignalEvent)
        assert e.event_id == sig_event.event_id
        # Look up execution event
        e = ledger.get_event(exec_event.event_id)
        assert e is not None
        assert isinstance(e, ExecutionEvent)
        assert e.event_id == exec_event.event_id
        # Look up non-existent
        assert ledger.get_event("nonexistent") is None

    def test_rebuild_trades_completed(self, ledger: EventLedger, sig_event: SignalEvent,
                                     exec_event: ExecutionEvent, stop_event: ExecutionEvent) -> None:
        ledger.append(sig_event)
        ledger.append(exec_event)
        ledger.append(stop_event)
        # Both buy and sell executed → completed trade
        trades = ledger.rebuild_trades("run_001")
        assert len(trades) == 1
        t = trades[0]
        assert t["trade_id"] == "T001"
        assert t["status"] == "completed"
        assert t["entry_signal_date"] == "2026-01-15"
        assert t["entry_exec_date"] == "2026-01-16"
        assert t["exit_signal_date"] == "2026-01-20"
        assert t["exit_exec_date"] == "2026-01-21"
        assert t["shares"] == 100.0
        assert t["exit_reason"] == "STOP_LOSS_2ATR"
        assert t["atr_at_entry"] == 4.5
        assert t["stop_level"] == 94.0

    def test_rebuild_trades_unfilled(self, ledger: EventLedger) -> None:
        # Create an unfilled execution event
        unfilled = ExecutionEvent(
            event_id="run_001|A|005930|2026-01-15|unfilled",
            run_id="run_001",
            scenario_id="S01",
            trade_id="T002",
            source_signal_event_id=None,
            symbol="005930",
            strategy="A",
            timeframe="1D",
            signal_date="2026-01-15",
            order_date="2026-01-16",
            fill_date=None,
            side="buy",
            quantity=0.0,
            signal_price=100.0,
            execution_price=None,
            commission=0.0,
            slippage=0.0,
            execution_status="unfilled",
            exit_reason=None,
            position_before_execution=0,
            position_after_execution=0,
            unfilled_reason="no_next_bar",
        )
        ledger.append(unfilled)
        trades = ledger.rebuild_trades("run_001")
        assert len(trades) == 1
        t = trades[0]
        assert t["trade_id"] == "T002"
        assert t["status"] == "unfilled"
        assert t["entry_exec_date"] == ""
        assert t["entry_price"] == ""
        assert t["pnl"] == ""


class TestCleanFunction:
    def test_numpy_scalar(self) -> None:
        import numpy as np
        assert clean(np.float64(1.5)) == 1.5
        assert clean(np.int64(42)) == 42

    def test_nan_to_none(self) -> None:
        import numpy as np
        assert clean(float("nan")) is None
        assert clean(np.nan) is None

    def test_dict(self) -> None:
        import numpy as np
        d = {"a": np.float64(1.0), "b": float("nan"), "c": 3}
        result = clean(d)
        assert result["a"] == 1.0
        assert result["b"] is None
        assert result["c"] == 3

    def test_list(self) -> None:
        import numpy as np
        v = clean([np.float64(1.0), np.nan, 3])
        assert v[0] == 1.0
        assert v[1] is None
        assert v[2] == 3

    def test_passthrough(self) -> None:
        assert clean("hello") == "hello"
        assert clean(None) is None
        assert clean(True) is True
