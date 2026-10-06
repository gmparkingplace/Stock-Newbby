from __future__ import annotations



"""Position and cash tracking for the stock-signal-lab accounting engine.



PositionTracker maintains the cash balance and share count for a single

strategy.  It reads FeeRecord objects produced by the FeeLedger and applies

fee amounts to cash on every trade.



Buy  : cash decreases by (quantity * effective_price + commission).

Sell : cash increases by (quantity * effective_price - commission - sell_tax).

``effective_price`` is already slippage-adjusted by the FeeLedger, so
``slippage_cost`` (an informational absolute difference) is never added
again here.  ``total_fees = commission + sell_tax`` matches FeeRecord.



"""



from dataclasses import dataclass, field

from typing import Any



from lab.accounting.fees import FeeRecord





@dataclass

class DailyState:

    """Immutable snapshot of the position at a given date.



    Attributes

    ----------

    date : str

        ISO 8601 date string.

    cash : float

        Current cash balance.

    shares : float

        Current share count (0.0 when flat).

    close : float

        Closing price used for valuation.

    market_value : float

        shares * close.

    equity : float

        cash + market_value.

    held : bool

        True when shares > 0, False otherwise.

    """



    date: str

    cash: float

    shares: float

    close: float

    market_value: float

    equity: float

    held: bool





@dataclass

class PositionTracker:

    """Tracks cash and shares for a single strategy position.



    Parameters

    ----------

    initial_capital : float

        Starting cash balance.



    Notes

    -----

    The tracker does **not** know about the FeeLedger.  It receives

    FeeRecord objects and uses their fee fields to update cash.

    

    Buy  : cash -= quantity * effective_price + commission

    Sell : cash += quantity * effective_price - commission - sell_tax

    """



    initial_capital: float

    cash: float = field(init=False)

    shares: float = field(default=0.0)

    entry_price: float | None = None

    _states: list[DailyState] = field(default_factory=list)



    def __post_init__(self) -> None:

        self.cash = self.initial_capital



    def open_position(self, side: str, price: float, quantity: float,

                      date: str, fee_record: FeeRecord) -> None:

        """Open or partially fill a position.



        Applies the fee record's fee components to cash and updates

        shares.  The effective price from the FeeRecord is used for the

        cash adjustment.



        Parameters

        ----------

        side : str

            ``"buy"`` to increase shares, ``"sell"`` to decrease.

        price : float

            Reference price (unused -- effective_price from fee_record is used).

        quantity : float

            Number of shares to buy or sell.

        date : str

            Trade date (ISO 8601).

        fee_record : FeeRecord

            Fee record from the FeeLedger containing effective_price,

            commission, sell_tax, and slippage_cost.



        Raises

        ------

        ValueError

            If selling more shares than currently held.

        """



        eff = fee_record.effective_price

        comm = fee_record.commission

        tax = fee_record.sell_tax



        if side == "buy":

            # NOTE: eff is already slippage-adjusted; slip is informational
            # only (see FeeRecord) and must not be charged a second time.
            self.cash -= quantity * eff + comm

            self.shares += quantity

            if self.shares > 0:

                self.entry_price = eff

        else:

            if quantity > self.shares + 1e-9:

                raise ValueError(

                    f"Cannot sell {quantity} shares; only {self.shares} held."

                )

            self.cash += quantity * eff - comm - tax

            self.shares -= quantity

            if self.shares <= 1e-9:

                self.shares = 0.0

                self.entry_price = None



    def close_position(self) -> None:

        """Reset entry_price to None (position is flat).



        This is a convenience method -- open_position already resets

        entry_price when shares reach zero.  This can be used as an

        explicit signal that the position is fully closed.

        """

        self.entry_price = None



    @property

    def is_held(self) -> bool:

        """True when shares > 0, False when flat."""

        return self.shares > 1e-9



    def valuation(self, close_price: float) -> float:

        """Return the current portfolio equity.



        equity = cash + shares * close_price



        Parameters

        ----------

        close_price : float

            Current closing price for mark-to-market valuation.



        Returns

        -------

        float

            Total equity (cash + market value of shares).

        """

        return self.cash + self.shares * close_price



    def daily_state(self, date: str, close_price: float) -> DailyState:

        """Return an immutable snapshot of the position at the given date.



        Parameters

        ----------

        date : str

            ISO 8601 date.

        close_price : float

            Closing price for valuation.



        Returns

        -------

        DailyState

            Immutable record with cash, shares, market_value, equity, held.

        """

        mv = self.shares * close_price

        eq = self.cash + mv

        held = self.shares > 1e-9

        state = DailyState(

            date=date,

            cash=self.cash,

            shares=self.shares,

            close=close_price,

            market_value=mv,

            equity=eq,

            held=held,

        )

        self._states.append(state)

        return state



    def to_list(self) -> list[dict[str, Any]]:

        """Return all daily state snapshots as a list of plain dicts.



        The returned list is a copy.

        """

        return [dict(vars(s)) for s in self._states]


