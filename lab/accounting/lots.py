from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class Lot:
    price: float
    quantity: float
    fee: float
    date: str
    cost_basis: float

@dataclass
class RealizedPnL:
    date: str
    quantity: float
    proceeds: float
    cost_basis: float
    realized_pnl: float

@dataclass
class LotManager:
    _lots: list[Lot] = field(default_factory=list)
    _realized: list[RealizedPnL] = field(default_factory=list)

    def add_lot(self, price: float, quantity: float, fee: float, date: str) -> Lot:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        cost = quantity * price + fee
        lot = Lot(price=price, quantity=quantity, fee=fee, date=date, cost_basis=cost)
        self._lots.append(lot)
        return lot

    def remove_quantity(self, quantity: float, date: str, fee: float,
                        proceeds: float) -> list[RealizedPnL]:
        if quantity <= 0:
            return []
        total = quantity
        remaining = quantity
        realized: list[RealizedPnL] = []

        while remaining > 1e-9:
            if not self._lots:
                raise ValueError(
                    f"Cannot remove {remaining} shares; only "
                    f"{sum(l.quantity for l in self._lots)} available."
                )
            lot = self._lots[0]
            consumed = min(remaining, lot.quantity)
            # FIFO: proceeds are split pro-rata across consumed lots so that
            # the sum of per-lot proceeds equals the sell order proceeds.
            lot_proceeds = proceeds * (consumed / total)
            consumed_cost = consumed * lot.price + lot.fee * (consumed / lot.quantity)
            if consumed >= lot.quantity - 1e-9:
                self._lots.pop(0)
            else:
                new_qty = lot.quantity - consumed
                new_fee = lot.fee * (new_qty / lot.quantity)
                lot.quantity = new_qty
                lot.fee = new_fee
                lot.cost_basis = new_qty * lot.price + new_fee
            realized.append(RealizedPnL(
                date=date,
                quantity=consumed,
                proceeds=lot_proceeds,
                cost_basis=consumed_cost,
                realized_pnl=lot_proceeds - consumed_cost,
            ))
            remaining -= consumed
        self._realized.extend(realized)
        return realized

    def total_shares(self) -> float:
        return sum(l.quantity for l in self._lots)

    def total_cost_basis(self) -> float:
        return sum(l.cost_basis for l in self._lots)

    def to_list(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return ([dict(vars(l)) for l in self._lots], [dict(vars(r)) for r in self._realized])
