"""PY-07: Price/Volume Adjustment + Context.

Provides adjustment policy declarations, split/dividend price adjustment,
continuity validation, volume adjustment guard, and market context
(beta/correlation) with proper sample counting and N/A reasons.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# AdjustmentPolicy — explicit policy declaration
# ---------------------------------------------------------------------------

@dataclass
class AdjustmentPolicy:
    """Explicit declaration of price and volume adjustment policies.

    Must be declared before any price/volume calculation to prevent
    accidental double-adjustment or inconsistent mixing of adjusted
    and unadjusted data.

    Parameters
    ----------
    price_policy : str
        One of ``"split"``, ``"split_dividend"``, ``"none"``.
        - ``"split"``: Adjust prices for stock splits only.
        - ``"split_dividend"``: Adjust prices for splits AND dividends
          (full adjusted-close style).
        - ``"none"``: Raw prices, no adjustment.
    volume_policy : str
        One of ``"adjusted"``, ``"unadjusted"``, ``"raw"``.
        - ``"adjusted"``: Volume adjusted for splits (but NOT dividends).
        - ``"unadjusted"``: Volume as reported by the exchange.
        - ``"raw"``: Alias for unadjusted (for backward compatibility).

    Raises
    ------
    ValueError
        If an invalid policy string is provided.
    """

    price_policy: str
    volume_policy: str

    _VALID_PRICE_POLICIES = frozenset({"split", "split_dividend", "none"})
    _VALID_VOLUME_POLICIES = frozenset({"adjusted", "unadjusted", "raw"})

    def __post_init__(self) -> None:
        if self.price_policy not in self._VALID_PRICE_POLICIES:
            raise ValueError(
                f"invalid price_policy: {self.price_policy!r} — "
                f"must be one of {sorted(self._VALID_PRICE_POLICIES)}"
            )
        if self.volume_policy not in self._VALID_VOLUME_POLICIES:
            raise ValueError(
                f"invalid volume_policy: {self.volume_policy!r} — "
                f"must be one of {sorted(self._VALID_VOLUME_POLICIES)}"
            )

    def to_dict(self) -> dict[str, str]:
        return {"price": self.price_policy, "volume": self.volume_policy}


# ---------------------------------------------------------------------------
# Split / Dividend Price Adjustment
# ---------------------------------------------------------------------------

def split_adjust(
    data: pd.DataFrame,
    splits: list[dict[str, Any]],
    dividends: list[dict[str, Any]] | None = None,
    price_policy: str = "split",
) -> pd.DataFrame:
    """Apply stock split and/or dividend adjustments to a DataFrame of OHLCV data.

    Parameters
    ----------
    data : pd.DataFrame
        DataFrame with columns: ``date`` (str or datetime), ``open``, ``high``,
        ``low``, ``close``, ``volume``. Must be sorted by date ascending.
    splits : list[dict]
        List of split events. Each dict must have at least
        ``{"date": str, "ratio": float}`` (e.g., ``{"date": "2025-06-15", "ratio": 2.0}``
        for a 2-for-1 split). The ratio is the multiplier applied to the
        post-split price (2.0 means each old share becomes 2 new shares).
    dividends : list[dict], optional
        List of dividend events. Each dict must have
        ``{"date": str, "amount": float, "ex_date": str}``.
        Only used when ``price_policy == "split_dividend"``.
    price_policy : str
        ``"split"`` — adjust for splits only.
        ``"split_dividend"`` — adjust for splits and dividends.

    Returns
    -------
    pd.DataFrame
        A copy of ``data`` with adjusted prices. Original data is not modified.
        Split adjustments: prices before the split date are divided by the
        ratio (so they are on the same basis as post-split prices).
        Dividend adjustments: prices before the ex-date are reduced by the
        dividend amount (adjusted for the ratio if split occurred later).

    Notes
    -------
    The adjustment is applied backwards from the latest date to the earliest,
    ensuring that cascading adjustments are correct (a split after a dividend
    means the dividend amount must also be scaled by the split ratio).
    """
    df = data.copy()
    if "date" not in df.columns:
        raise ValueError("data must have a 'date' column")

    # Build a sorted list of all adjustment events (splits and dividends)
    # sorted by date descending (we apply from latest to earliest)
    events: list[tuple[str, str, float]] = []  # (date, type, param)
    for s in splits:
        events.append((s["date"], "split", s["ratio"]))
    if price_policy == "split_dividend":
        for d in dividends or []:
            events.append((d["ex_date"], "dividend", d["amount"]))

    # Sort by date descending (latest first)
    events.sort(key=lambda e: e[0], reverse=True)

    dates = df["date"].astype(str).tolist()
    n_rows = len(dates)
    split_factors = [1.0] * n_rows
    div_amounts = [0.0] * n_rows

    cum_factor = 1.0
    cum_div = 0.0

    for evt_date, evt_type, param in events:
        if evt_type == "split":
            cum_div /= param
            cum_factor /= param
        elif evt_type == "dividend":
            cum_div += param * cum_factor

        # Apply cumulative factors to all rows before this event
        for idx, d in enumerate(dates):
            if d < evt_date:
                split_factors[idx] = cum_factor
                div_amounts[idx] = cum_div

    ohlc_cols = ["open", "high", "low", "close"]

    # Guard: only apply if there's actually something to adjust
    if any(sf != 1.0 or da != 0.0 for sf, da in zip(split_factors, div_amounts)):
        for col in ohlc_cols:
            if col in df.columns:
                df[col] = df[col] * split_factors
                df[col] = df[col] - div_amounts

    return df


# ---------------------------------------------------------------------------
# Continuity Validation
# ---------------------------------------------------------------------------

def validate_continuity(
    data: pd.DataFrame,
    splits: list[dict[str, Any]],
    tolerance: float = 0.01,
) -> list[dict[str, Any]]:
    """Validate that price jumps on split dates are consistent with the split ratio.

    After a split with ratio R, the closing price on the split date should be
    approximately ``pre_split_close * R`` (for a 2-for-1 split, price doubles
    in terms of shares but the per-share price halves, so the adjusted price
    should show continuity when properly adjusted).

    Specifically, this checks that the price discontinuity on the split date
    matches the expected split ratio within the given tolerance.

    Parameters
    ----------
    data : pd.DataFrame
        DataFrame with ``date`` and ``close`` columns, sorted by date ascending.
        Should be RAW (unadjusted) prices.
    splits : list[dict]
        Split events with ``{"date": str, "ratio": float}``.
    tolerance : float
        Maximum acceptable relative deviation (e.g., 0.01 = 1%).

    Returns
    -------
    list[dict]
        One dict per split event:
        ``{"split_date": str, "expected_ratio": float, "observed_ratio": float,
        "consistent": bool, "deviation": float}``.
        ``consistent`` is True if ``|observed/expected - 1| <= tolerance``.
    """
    if "date" not in data.columns or "close" not in data.columns:
        raise ValueError("data must have 'date' and 'close' columns")

    df = data.copy()
    df["date"] = df["date"].astype(str)

    # Build date → close lookup
    close_lookup = dict(zip(df["date"], df["close"]))

    results: list[dict[str, Any]] = []
    for s in splits:
        split_date = s["date"]
        expected_ratio = s["ratio"]

        # Find the trading day before the split date
        prior_dates = [d for d in df["date"].tolist() if d < split_date]
        if not prior_dates:
            results.append({
                "split_date": split_date,
                "expected_ratio": expected_ratio,
                "observed_ratio": None,
                "consistent": False,
                "deviation": None,
                "note": "no prior trading day found",
            })
            continue

        prior_date = max(prior_dates)
        pre_split_close = close_lookup.get(prior_date)
        split_day_close = close_lookup.get(split_date)

        if pre_split_close is None or split_day_close is None:
            results.append({
                "split_date": split_date,
                "expected_ratio": expected_ratio,
                "observed_ratio": None,
                "consistent": False,
                "deviation": None,
                "note": f"missing price data (prior={prior_date}, split={split_date})",
            })
            continue

        observed_ratio = pre_split_close / split_day_close if split_day_close != 0 else None

        if observed_ratio is None:
            results.append({
                "split_date": split_date,
                "expected_ratio": expected_ratio,
                "observed_ratio": None,
                "consistent": False,
                "deviation": None,
                "note": "zero price on split day",
            })
            continue

        deviation = abs(observed_ratio / expected_ratio - 1.0)
        consistent = deviation <= tolerance

        results.append({
            "split_date": split_date,
            "expected_ratio": expected_ratio,
            "observed_ratio": round(observed_ratio, 6),
            "consistent": consistent,
            "deviation": round(deviation, 6),
        })

    return results


# ---------------------------------------------------------------------------
# Volume Adjustment Guard
# ---------------------------------------------------------------------------

def validate_volume_adjustment(
    data: pd.DataFrame,
    volume_policy: str,
    splits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Detect double-adjustment or mismatch of volume data.

    Checks whether the actual volume data is consistent with the declared
    volume_policy. Detects both directions of mismatch:
    - Policy says "adjusted" but volume looks raw (double-adjustment)
    - Policy says "unadjusted" but volume looks split-adjusted

    Parameters
    ----------
    data : pd.DataFrame
        DataFrame with ``date`` and ``volume`` columns, sorted by date ascending.
    volume_policy : str
        Declared volume adjustment policy (``"adjusted"``, ``"unadjusted"``, or ``"raw"``).
    splits : list[dict], optional
        Split events with ``{"date": str, "ratio": float}``.

    Returns
    -------
    dict
        ``{"ok": bool, "issues": list[str]}``
        ``ok`` is True if no double-adjustment or inconsistency detected.
        ``issues`` is a list of human-readable problem descriptions.
    """
    if volume_policy not in ("adjusted", "unadjusted", "raw"):
        raise ValueError(f"invalid volume_policy: {volume_policy!r}")

    splits = splits or []
    issues: list[str] = []

    if "volume" not in data.columns:
        issues.append("volume column not found in data")
        return {"ok": False, "issues": issues}

    for s in splits:
        split_date = s["date"]
        ratio = s["ratio"]
        if ratio == 1.0:
            continue

        dates = data["date"].astype(str).tolist()
        vol_lookup = dict(zip(dates, data["volume"].tolist()))

        prior_dates = [d for d in dates if d < split_date]
        if not prior_dates:
            continue
        prior_date = max(prior_dates)
        prior_vol = vol_lookup.get(prior_date)
        split_vol = vol_lookup.get(split_date)

        if prior_vol is None or split_vol is None:
            continue

        observed_ratio = prior_vol / split_vol if split_vol != 0 else 0.0

        # 3-tier detection
        if abs(observed_ratio - 1.0) < 0.01:
            # Volume is unchanged (ratio ≈ 1.0) → double-adjustment
            issues.append(
                f"double-adjustment on {split_date}: volume ratio {observed_ratio:.4f} ≈ 1.0 "
                f"but split ratio is {ratio:.4f}. Volume has been adjusted twice."
            )
        elif abs(observed_ratio - 1.0 / ratio) < 0.01:
            # Volume matches 1/ratio → raw (unadjusted)
            if volume_policy == "adjusted":
                issues.append(
                    f"raw volume detected on {split_date}: volume ratio {observed_ratio:.4f} ≈ "
                    f"1/{ratio:.4f} but policy declares 'adjusted'. Volume has NOT been adjusted."
                )
        elif abs(observed_ratio - 1.0 / ratio ** 2) < 0.01:
            # Volume matches 1/ratio² → split-adjusted (pre-split division convention)
            if volume_policy == "unadjusted":
                issues.append(
                    f"split-adjusted volume detected on {split_date}: volume ratio {observed_ratio:.4f} ≈ "
                    f"1/{ratio:.4f}² but policy declares 'unadjusted'. Volume HAS been adjusted."
                )

    return {"ok": len(issues) == 0, "issues": issues}


# ---------------------------------------------------------------------------
# Market Context: beta, correlation, R² with proper N/A handling
# ---------------------------------------------------------------------------

VAR_EPS = 1e-12


def beta_corr(
    stock_rets: list[float],
    mkt_rets: list[float],
    window: int = 60,
) -> dict[str, Any]:
    """Compute beta, correlation, R² with proper sample counting and N/A reasons.

    Uses the last ``window`` returns as the sample. Returns must be pre-shifted
    by the caller (t-1 cutoff: use returns up to t-1 for t's context).

    Parameters
    ----------
    stock_rets : list[float]
        List of stock returns (already shifted for t-1 cutoff).
        Length must be >= 2.
    mkt_rets : list[float]
        List of market/benchmark returns, same alignment as ``stock_rets``.
        Must be same length as ``stock_rets``.
    window : int
        Rolling window size (number of observations to use).

    Returns
    -------
    dict
        ``{"beta": float|None, "corr": float|None, "r2": float|None,
        "n_obs": int, "reason": str}``.

        ``reason`` is one of:
        - ``"ok"`` — sufficient data, valid variance.
        - ``"insufficient"`` — ``n_obs < window`` (not enough observations).
        - ``"zero_variance"`` — market returns have zero variance (no movement).
        - ``"missing_benchmark"`` — benchmark returns list is empty or contains only NaN.
    """
    # Check for missing benchmark BEFORE length comparison
    if len(mkt_rets) == 0:
        return {"beta": None, "corr": None, "r2": None, "n_obs": 0, "reason": "missing_benchmark"}

    n = len(stock_rets)
    if n != len(mkt_rets):
        raise ValueError(
            f"length mismatch: stock_rets({n}) vs mkt_rets({len(mkt_rets)})"
        )

    # Filter out NaN pairs (both must be valid)
    valid_pairs = []
    for rs, rm in zip(stock_rets, mkt_rets):
        if rs is None or rm is None or (isinstance(rs, float) and math.isnan(rs)) or \
           (isinstance(rm, float) and math.isnan(rm)):
            continue
        valid_pairs.append((rs, rm))

    n_valid = len(valid_pairs)

    if n_valid == 0:
        return {"beta": None, "corr": None, "r2": None, "n_obs": 0, "reason": "missing_benchmark"}

    # Take the last `window` valid observations
    sample = valid_pairs[-window:] if n_valid >= window else valid_pairs
    n_obs = len(sample)

    if n_obs == 0:
        return {"beta": None, "corr": None, "r2": None, "n_obs": 0, "reason": "missing_benchmark"}

    # Extract arrays
    rs_arr = [p[0] for p in sample]
    rm_arr = [p[1] for p in sample]

    # Check insufficient sample
    if n_obs < window:
        return {"beta": None, "r2": None, "corr": None, "n_obs": n_obs, "reason": "insufficient"}

    # Compute covariance and variance
    rs_mean = sum(rs_arr) / n_obs
    rm_mean = sum(rm_arr) / n_obs

    cov = sum((rs_arr[i] - rs_mean) * (rm_arr[i] - rm_mean) for i in range(n_obs)) / n_obs
    var_rm = sum((rm_arr[i] - rm_mean) ** 2 for i in range(n_obs)) / n_obs

    # Check zero variance
    if abs(var_rm) < VAR_EPS:
        return {"beta": None, "r2": None, "corr": None, "n_obs": n_obs, "reason": "zero_variance"}

    beta = cov / var_rm

    # Correlation
    var_rs = sum((rs_arr[i] - rs_mean) ** 2 for i in range(n_obs)) / n_obs
    if var_rs < VAR_EPS:
        # Stock has zero variance — correlation is undefined but we can still compute beta
        corr = None
    else:
        corr = cov / math.sqrt(var_rs * var_rm)

    r2 = corr ** 2 if corr is not None else None

    return {
        "beta": round(beta, 8),
        "corr": round(corr, 8) if corr is not None else None,
        "r2": round(r2, 8) if r2 is not None else None,
        "n_obs": n_obs,
        "reason": "ok",
    }
