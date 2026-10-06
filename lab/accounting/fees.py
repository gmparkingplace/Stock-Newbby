from __future__ import annotations



"""Cost and fee tracking for the stock-signal-lab accounting engine.



FeeLedger accumulates commission, sell tax, and slippage costs from every

trade.  All rates are expressed in basis points (1 bp = 0.01 %).  The ledger

never modifies prices that the PositionTracker sees -- it only reports

fee amounts that the position tracker applies on top of the slippage-

adjusted effective price.

"""



from dataclasses import dataclass, field

from typing import Any





@dataclass

class FeeRecord:

    """Immutable record of all costs attributable to a single trade.



    Attributes

    ----------

    trade_id : str

        Identifier linking this fee record back to the originating trade.

    date : str

        Trade date (ISO 8601).

    side : str

        ``"buy"`` or ``"sell"``.

    raw_price : float

        Unadjusted reference price (e.g. daily open or close).

    effective_price : float

        Slippage-adjusted execution price.

        Buy:  raw_price * (1 + slippage_rate)

        Sell: raw_price * (1 - slippage_rate)

    quantity : float

        Number of shares in this trade.

    commission : float

        Brokerage commission charged on the effective trade value.

        Charged on BOTH buy and sell sides.

    sell_tax : float

        Statutory sell-side tax (transaction tax, special tax, etc.).

        Charged only on the sell side; 0.0 for buys.

    slippage_cost : float

        Absolute cost of slippage.  Buy: |effective - raw| * qty.

        Sell: |raw - effective| * qty.

    total_fees : float

        commission + sell_tax.  Does NOT include slippage_cost.

    """



    trade_id: str

    date: str

    side: str

    raw_price: float

    effective_price: float

    quantity: float

    commission: float

    sell_tax: float

    slippage_cost: float

    total_fees: float





@dataclass

class FeeLedger:

    """Accumulates commission, sell tax, and slippage costs over all trades.



    All rates are given in **basis points** (1 bp = 0.01 %).  Internally they

    are converted to decimal fractions.



    The ledger is *passive*: it does not adjust cash or shares.  The

    PositionTracker reads ``FeeRecord`` objects from the ledger and applies

    the fee amounts to cash.



    Parameters

    ----------

    commission_bps : float

        Commission rate in basis points, charged on both buy and sell.

    sell_tax_bps : float

        Sell-side tax rate in basis points, charged only on sells.

    slippage_bps : float

        Slippage rate in basis points.  Adjusts the execution price:

        buy -> price * (1 + rate),  sell -> price * (1 - rate).

    """



    commission_bps: float

    sell_tax_bps: float

    slippage_bps: float

    _records: list[FeeRecord] = field(default_factory=list)

    _commission_total: float = 0.0

    _sell_tax_total: float = 0.0

    _slippage_cost_total: float = 0.0



    @property

    def commission_rate(self) -> float:

        """Commission as a decimal fraction."""

        return self.commission_bps / 10_000.0



    @property

    def sell_tax_rate(self) -> float:

        """Sell tax as a decimal fraction."""

        return self.sell_tax_bps / 10_000.0



    @property

    def slippage_rate(self) -> float:

        """Slippage as a decimal fraction."""

        return self.slippage_bps / 10_000.0



    def record_trade(self, trade_id: str, date: str, side: str,

                     raw_price: float, quantity: float) -> FeeRecord:

        """Record costs for a single trade and return the FeeRecord.



        Parameters

        ----------

        trade_id : str

            Identifier for the originating trade.

        date : str

            Trade date (ISO 8601).

        side : str

            ``"buy"`` or ``"sell"``.

        raw_price : float

            Unadjusted reference price (e.g. daily open or close).

        quantity : float

            Number of shares.



        Returns

        -------

        FeeRecord

            Immutable record containing all fee components.



        Notes

        -----

        The effective price is computed from the rat price by applying the

        slippage rate: buy side is inflated, sell side is deflated.

        Commission is charged on the effective trade value for BOTH sides.

        Sell tax is charged on the effective trade value for SELL side only.

        Slippage cost is the absolute difference between raw and effective

        trade values.

        """



        if side == "buy":

            effective_price = raw_price * (1.0 + self.slippage_rate)

            trade_value = quantity * effective_price

            commission = trade_value * self.commission_rate

            sell_tax = 0.0

            slippage_cost = abs(trade_value - quantity * raw_price)

        else:

            effective_price = raw_price * (1.0 - self.slippage_rate)

            trade_value = quantity * effective_price

            commission = trade_value * self.commission_rate

            sell_tax = trade_value * self.sell_tax_rate

            slippage_cost = abs(quantity * raw_price - trade_value)



        total_fees = commission + sell_tax



        record = FeeRecord(

            trade_id=trade_id,

            date=date,

            side=side,

            raw_price=raw_price,

            effective_price=effective_price,

            quantity=quantity,

            commission=commission,

            sell_tax=sell_tax,

            slippage_cost=slippage_cost,

            total_fees=total_fees,

        )

        self._records.append(record)

        self._commission_total += commission

        self._sell_tax_total += sell_tax

        self._slippage_cost_total += slippage_cost

        return record



    def summarize(self) -> dict[str, Any]:

        """Return aggregate fee totals as a plain dict.



        Keys

        ----

        commission_total : float

            Sum of all commissions.

        sell_tax_total : float

            Sum of all sell taxes.

        slippage_cost_total : float

            Sum of all slippage costs.

        total_fees : float

            commission_total + sell_tax_total (excludes slippage).

        total_costs : float

            total_fees + slippage_cost_total (includes slippage).

        trade_count : int

            Number of recorded trades.

        """

        total_fees = self._commission_total + self._sell_tax_total

        return {

            "commission_total": self._commission_total,

            "sell_tax_total": self._sell_tax_total,

            "slippage_cost_total": self._slippage_cost_total,

            "total_fees": total_fees,

            "total_costs": total_fees + self._slippage_cost_total,

            "trade_count": len(self._records),

        }



    def to_list(self) -> list[dict[str, Any]]:

        """Return all fee records as a list of plain dicts.



        Each dict contains the fields defined by :class:`FeeRecord`.

        The returned list is a *copy* -- mutating it does not affect the

        ledger.

        """

        return [dict(vars(r)) for r in self._records]


