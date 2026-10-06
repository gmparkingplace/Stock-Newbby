"""Smoke tests for lab.engine.adjustments — PY-07: Price/Volume Adjustment + Context.

Run: ``cd ~/Desktop/stock-signal-lab && python -m pytest tests/test_adjustments.py -v``
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from lab.engine.adjustments import (
    AdjustmentPolicy,
    beta_corr,
    split_adjust,
    validate_continuity,
    validate_volume_adjustment,
)


# ---------------------------------------------------------------------------
# Tests: AdjustmentPolicy
# ---------------------------------------------------------------------------

class TestAdjustmentPolicy:
    def test_valid_combinations(self) -> None:
        """All valid price/volume policy combinations work."""
        for pp in ("split", "split_dividend", "none"):
            for vp in ("adjusted", "unadjusted", "raw"):
                policy = AdjustmentPolicy(price_policy=pp, volume_policy=vp)
                assert policy.price_policy == pp
                assert policy.volume_policy == vp

    def test_invalid_price_policy(self) -> None:
        with pytest.raises(ValueError, match="invalid price_policy"):
            AdjustmentPolicy(price_policy="invalid", volume_policy="adjusted")

    def test_invalid_volume_policy(self) -> None:
        with pytest.raises(ValueError, match="invalid volume_policy"):
            AdjustmentPolicy(price_policy="split", volume_policy="bogus")

    def test_to_dict(self) -> None:
        policy = AdjustmentPolicy(price_policy="split_dividend", volume_policy="adjusted")
        d = policy.to_dict()
        assert d == {"price": "split_dividend", "volume": "adjusted"}


# ---------------------------------------------------------------------------
# Tests: split_adjust
# ---------------------------------------------------------------------------

class TestSplitAdjust:
    @staticmethod
    def _make_data(dates: list[str], prices: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
        """Build a DataFrame from dates and (open, high, low, close, volume) tuples."""
        return pd.DataFrame({
            "date": dates,
            "open": [p[0] for p in prices],
            "high": [p[1] for p in prices],
            "low": [p[2] for p in prices],
            "close": [p[3] for p in prices],
            "volume": [p[4] for p in prices],
        })

    def test_no_splits(self) -> None:
        """Without splits, data is unchanged."""
        data = self._make_data(
            ["2025-01-01", "2025-01-02"],
            [(100, 105, 98, 103, 1000), (103, 106, 101, 104, 1200)],
        )
        result = split_adjust(data, splits=[], price_policy="split")
        pd.testing.assert_frame_equal(result, data)

    def test_2_for_1_split(self) -> None:
        """2-for-1 split: prices before split are halved."""
        data = self._make_data(
            ["2025-01-01", "2025-01-02", "2025-06-15", "2025-06-16"],
            [(100, 105, 98, 103, 1000),
             (103, 106, 101, 104, 1200),
             (50, 55, 48, 52, 2400),   # After 2:1 split, price is halved
             (52, 56, 50, 53, 2500)],
        )
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        result = split_adjust(data, splits, price_policy="split")

        # Pre-split prices should be halved (divided by 2)
        assert result.iloc[0]["close"] == pytest.approx(103 / 2.0)
        assert result.iloc[1]["close"] == pytest.approx(104 / 2.0)
        # Post-split prices unchanged
        assert result.iloc[2]["close"] == pytest.approx(52.0)
        assert result.iloc[3]["close"] == pytest.approx(53.0)

    def test_split_adjust_opens(self) -> None:
        """Open/high/low are also adjusted for splits."""
        data = self._make_data(
            ["2025-01-01", "2025-06-15"],
            [(100, 105, 98, 103, 1000),
             (50, 55, 48, 52, 2400)],
        )
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        result = split_adjust(data, splits, price_policy="split")
        assert result.iloc[0]["open"] == pytest.approx(100 / 2.0)
        assert result.iloc[0]["high"] == pytest.approx(105 / 2.0)
        assert result.iloc[0]["low"] == pytest.approx(98 / 2.0)
        assert result.iloc[0]["close"] == pytest.approx(103 / 2.0)

    def test_3_for_1_split(self) -> None:
        """3-for-1 split: prices before split are divided by 3."""
        data = self._make_data(
            ["2025-01-01", "2025-03-01"],
            [(300, 310, 295, 305, 1000),
             (100, 105, 98, 102, 3000)],
        )
        splits = [{"date": "2025-03-01", "ratio": 3.0}]
        result = split_adjust(data, splits, price_policy="split")
        assert result.iloc[0]["close"] == pytest.approx(305 / 3.0)
        assert result.iloc[1]["close"] == pytest.approx(102.0)

    def test_dividend_adjust(self) -> None:
        """Dividend adjustment: prices before ex-date are reduced by dividend."""
        data = self._make_data(
            ["2025-01-01", "2025-03-01"],
            [(100, 105, 98, 103, 1000),
             (102, 107, 100, 106, 1200)],
        )
        dividends = [{"date": "2025-02-01", "amount": 5.0, "ex_date": "2025-02-01"}]
        result = split_adjust(data, splits=[], dividends=dividends, price_policy="split_dividend")
        # Pre-ex-date close should be reduced by dividend amount
        assert result.iloc[0]["close"] == pytest.approx(103 - 5.0)
        # Post-ex-date close unchanged
        assert result.iloc[1]["close"] == pytest.approx(106.0)

    def test_combined_split_dividend(self) -> None:
        """Split + dividend: dividend is scaled by split ratio."""
        data = self._make_data(
            ["2025-01-01", "2025-03-01", "2025-06-15"],
            [(100, 105, 98, 103, 1000),
             (105, 110, 102, 108, 1100),
             (50, 55, 48, 52, 2400)],
        )
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        dividends = [{"date": "2025-03-01", "amount": 10.0, "ex_date": "2025-03-01"}]
        result = split_adjust(data, splits, dividends=dividends, price_policy="split_dividend")
        # Pre-split: close 103 adjusted by dividend 10 and split 2:1
        # Adjusted: (103 - 10) / 2 = 46.5
        assert result.iloc[0]["close"] == pytest.approx(46.5)

    def test_original_not_modified(self) -> None:
        """Original data is not modified (defensive copy)."""
        data = self._make_data(
            ["2025-01-01", "2025-06-15"],
            [(100, 105, 98, 103, 1000), (50, 55, 48, 52, 2400)],
        )
        original_close = data["close"].tolist().copy()
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        split_adjust(data, splits, price_policy="split")
        # Original unchanged
        assert data["close"].tolist() == original_close


# ---------------------------------------------------------------------------
# Tests: validate_continuity
# ---------------------------------------------------------------------------

class TestValidateContinuity:
    def test_consistent_split(self) -> None:
        """2:1 split with price halving → consistent."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-01-02", "2025-06-15"],
            "close": [100.0, 105.0, 52.5],  # 105/52.5 = 2.0 → consistent
        })
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        results = validate_continuity(data, splits, tolerance=0.01)
        assert len(results) == 1
        assert results[0]["consistent"] is True
        assert results[0]["observed_ratio"] == pytest.approx(2.0, abs=0.01)

    def test_inconsistent_split(self) -> None:
        """2:1 split but price doesn't halve → inconsistent."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-01-02", "2025-06-15"],
            "close": [100.0, 105.0, 40.0],  # 105/40 = 2.625 ≠ 2.0 → inconsistent
        })
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        results = validate_continuity(data, splits, tolerance=0.01)
        assert results[0]["consistent"] is False
        assert results[0]["observed_ratio"] == pytest.approx(2.625, abs=0.001)
        assert results[0]["deviation"] > 0.01

    def test_no_prior_day(self) -> None:
        """Split on first day → no prior day to compare."""
        data = pd.DataFrame({
            "date": ["2025-01-01"],
            "close": [100.0],
        })
        splits = [{"date": "2025-01-01", "ratio": 2.0}]
        results = validate_continuity(data, splits, tolerance=0.01)
        assert results[0]["consistent"] is False
        assert results[0]["observed_ratio"] is None
        assert "no prior trading day" in results[0]["note"]

    def test_missing_data(self) -> None:
        """Split date not in data → reported as inconsistent."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-01-02"],
            "close": [100.0, 105.0],
        })
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        results = validate_continuity(data, splits, tolerance=0.01)
        assert results[0]["consistent"] is False
        assert "missing price data" in results[0]["note"]

    def test_zero_price(self) -> None:
        """Zero price on split day → inconsistent."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-06-15"],
            "close": [100.0, 0.0],
        })
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        results = validate_continuity(data, splits, tolerance=0.01)
        assert results[0]["consistent"] is False
        assert "zero price" in results[0]["note"]

    def test_multiple_splits(self) -> None:
        """Multiple splits are all checked."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-03-01", "2025-06-01"],
            "close": [200.0, 100.0, 50.0],
        })
        splits = [
            {"date": "2025-03-01", "ratio": 2.0},  # 200/100 = 2.0 ✓
            {"date": "2025-06-01", "ratio": 2.0},  # 100/50 = 2.0 ✓
        ]
        results = validate_continuity(data, splits, tolerance=0.01)
        assert len(results) == 2
        assert all(r["consistent"] for r in results)


# ---------------------------------------------------------------------------
# Tests: validate_volume_adjustment
# ---------------------------------------------------------------------------

class TestValidateVolumeAdjustment:
    def test_raw_volume_with_unadjusted_policy(self) -> None:
        """Raw volume + unadjusted policy → ok (no mismatch)."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-06-15"],
            "volume": [1000, 2400],  # 2400 = 1200 * 2 (raw, exchange-reported after split)
        })
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        result = validate_volume_adjustment(data, volume_policy="unadjusted", splits=splits)
        # Volume is raw, policy says unadjusted → match → ok
        assert result["ok"] is True

    def test_adjusted_volume_with_adjusted_policy(self) -> None:
        """Already-adjusted volume + adjusted policy → ok (no double-adjust)."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-06-15"],
            "volume": [500, 2400],  # 500 = 1000/2 (split-adjusted pre-split), 2400 unchanged
        })
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        result = validate_volume_adjustment(data, volume_policy="adjusted", splits=splits)
        # Ratio 500/2400 = 0.208 ≈ 1/4 (split-adjusted) → matches policy → ok
        assert result["ok"] is True

    def test_double_adjustment_detected(self) -> None:
        """Double-adjusted volume detected (ratio ≈ 1 but split ratio ≠ 1)."""
        # If volume was already adjusted, the ratio on split day should be ~1
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-06-15"],
            "volume": [2000, 2000],  # ratio = 1.0, but split ratio = 2.0
        })
        splits = [{"date": "2025-06-15", "ratio": 2.0}]
        result = validate_volume_adjustment(data, volume_policy="adjusted", splits=splits)
        # Volume ratio is 1.0 ≈ 1.0 but split ratio is 2.0 → double-adjustment suspected
        assert result["ok"] is False
        assert any("double-adjustment" in i for i in result["issues"])

    def test_no_splits_ok(self) -> None:
        """No splits → always ok."""
        data = pd.DataFrame({
            "date": ["2025-01-01", "2025-01-02"],
            "volume": [1000, 1200],
        })
        result = validate_volume_adjustment(data, volume_policy="adjusted", splits=[])
        assert result["ok"] is True

    def test_invalid_policy(self) -> None:
        data = pd.DataFrame({"volume": [1000]})
        with pytest.raises(ValueError):
            validate_volume_adjustment(data, volume_policy="invalid")

    def test_missing_volume_column(self) -> None:
        data = pd.DataFrame({"date": ["2025-01-01"]})
        result = validate_volume_adjustment(data, volume_policy="adjusted")
        assert result["ok"] is False
        assert any("volume column not found" in i for i in result["issues"])


# ---------------------------------------------------------------------------
# Tests: beta_corr
# ---------------------------------------------------------------------------

class TestBetaCorr:
    def test_ok_case(self) -> None:
        """Sufficient data with non-zero variance → ok."""
        stock = [0.01, 0.02, 0.015, 0.01, 0.02, 0.015, 0.01, 0.02, 0.015, 0.01]
        mkt = [0.005, 0.01, 0.0075, 0.005, 0.01, 0.0075, 0.005, 0.01, 0.0075, 0.005]
        result = beta_corr(stock, mkt, window=10)
        assert result["reason"] == "ok"
        assert result["n_obs"] == 10
        assert result["beta"] is not None
        assert result["corr"] is not None
        assert result["r2"] is not None
        # Beta should be ~2.0 (stock moves twice as much as market)
        assert result["beta"] == pytest.approx(2.0, abs=0.01)
        # Correlation should be 1.0 (perfect linear relationship)
        assert result["corr"] == pytest.approx(1.0, abs=0.001)
        assert result["r2"] == pytest.approx(1.0, abs=0.001)

    def test_insufficient_sample(self) -> None:
        """Not enough observations → insufficient."""
        stock = [0.01, 0.02, 0.015]
        mkt = [0.005, 0.01, 0.0075]
        result = beta_corr(stock, mkt, window=10)
        assert result["reason"] == "insufficient"
        assert result["n_obs"] == 3
        assert result["beta"] is None
        assert result["corr"] is None
        assert result["r2"] is None

    def test_zero_variance_market(self) -> None:
        """Market returns all zero → zero_variance."""
        stock = [0.01, 0.02, 0.015, 0.01, 0.02, 0.015, 0.01, 0.02, 0.015, 0.01]
        mkt = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        result = beta_corr(stock, mkt, window=10)
        assert result["reason"] == "zero_variance"
        assert result["n_obs"] == 10
        assert result["beta"] is None
        assert result["corr"] is None
        assert result["r2"] is None

    def test_missing_benchmark(self) -> None:
        """Empty benchmark → missing_benchmark."""
        result = beta_corr([0.01, 0.02], [], window=10)
        assert result["reason"] == "missing_benchmark"
        assert result["n_obs"] == 0
        assert result["beta"] is None

    def test_nan_handling(self) -> None:
        """NaN values are filtered out."""
        stock = [0.01, float("nan"), 0.015, 0.01, 0.02, 0.015, 0.01, 0.02, 0.015, 0.01]
        mkt = [0.005, 0.002, 0.0075, 0.005, 0.01, 0.0075, 0.005, 0.01, 0.0075, 0.005]
        result = beta_corr(stock, mkt, window=10)
        # One NaN filtered, so n_obs = 9 < window=10 → insufficient
        assert result["reason"] == "insufficient"
        assert result["n_obs"] == 9

    def test_zero_variance_stock(self) -> None:
        """Stock returns all zero but market moves → beta=0, corr=None."""
        stock = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        mkt = [0.005, 0.01, 0.0075, 0.005, 0.01, 0.0075, 0.005, 0.01, 0.0075, 0.005]
        result = beta_corr(stock, mkt, window=10)
        assert result["reason"] == "ok"
        assert result["beta"] == pytest.approx(0.0, abs=1e-6)
        assert result["corr"] is None
        assert result["r2"] is None

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="length mismatch"):
            beta_corr([0.01, 0.02], [0.005], window=10)

    def test_t_minus_1_cutoff(self) -> None:
        """Returns must be pre-shifted (t-1 cutoff) by caller."""
        # This is a contract test — the function assumes shifted returns
        stock = [0.01, 0.02, 0.015]
        mkt = [0.005, 0.01, 0.0075]
        result = beta_corr(stock, mkt, window=3)
        assert result["reason"] == "ok"
        assert result["n_obs"] == 3
