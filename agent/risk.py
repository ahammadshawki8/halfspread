"""Position sizing and hard limits.

Deterministic. Nothing here consults a model or an LLM: the sizing rule is
arithmetic on measured max loss, and every refusal carries a reason that is
journalled so the decision can be audited after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config, journal
from .cost import Evaluation


@dataclass(frozen=True)
class SizingDecision:
    approved: bool
    qty: int
    reason: str
    max_loss_total: float
    risk_budget_remaining: float


def realized_loss_today(records: list[dict] | None = None) -> float:
    """Dollars of realised loss booked so far today. Positive number."""
    records = records if records is not None else journal.read()
    loss = 0.0
    for r in records:
        if r.get("kind") in ("settlement", "emergency_close"):
            pnl = r.get("realized_pnl")
            if isinstance(pnl, (int, float)) and pnl < 0:
                loss += -pnl
    return loss


def open_risk(positions: list[dict]) -> float:
    """Worst-case dollars already committed to open option positions.

    Alpaca reports legs individually, so this is a conservative proxy: sum
    the absolute cost basis of short option legs. Precise per-spread max
    loss comes from the journal when a spread is recorded.
    """
    total = 0.0
    for p in positions:
        if p.get("asset_class") != "us_option":
            continue
        try:
            qty = abs(float(p.get("qty") or 0))
            price = abs(float(p.get("avg_entry_price") or 0))
        except (TypeError, ValueError):
            continue
        total += qty * price * 100.0
    return total


def spreads_open(positions: list[dict]) -> int:
    """Each vertical contributes two option legs."""
    legs = sum(1 for p in positions if p.get("asset_class") == "us_option")
    return (legs + 1) // 2


def size(
    ev: Evaluation,
    positions: list[dict] | None = None,
    journal_records: list[dict] | None = None,
) -> SizingDecision:
    positions = positions or []

    def refuse(reason: str, budget: float = 0.0) -> SizingDecision:
        return SizingDecision(False, 0, reason, 0.0, budget)

    if not ev.admissible:
        return refuse(f"candidate inadmissible: {ev.reject_reason}")
    if ev.net_ev <= config.MIN_NET_EV:
        return refuse(f"net EV ${ev.net_ev:.2f} <= floor ${config.MIN_NET_EV:.2f}")
    if ev.max_loss <= 0:
        return refuse("max loss is not positive")

    n_open = spreads_open(positions)
    if n_open >= config.MAX_CONCURRENT_POSITIONS:
        return refuse(f"{n_open} spreads already open, cap {config.MAX_CONCURRENT_POSITIONS}")

    lost = realized_loss_today(journal_records)
    budget = config.MAX_LOSS_PER_DAY - lost - open_risk(positions)
    if budget <= 0:
        return refuse(
            f"daily risk budget exhausted (realised loss ${lost:.2f}, "
            f"open risk ${open_risk(positions):.2f})",
            budget,
        )

    per_contract = ev.max_loss
    if per_contract > config.MAX_LOSS_PER_POSITION:
        return refuse(
            f"per-contract max loss ${per_contract:.2f} exceeds cap "
            f"${config.MAX_LOSS_PER_POSITION:.2f}",
            budget,
        )

    qty = int(min(budget, config.MAX_LOSS_PER_POSITION) // per_contract)
    if qty < 1:
        return refuse(
            f"risk budget ${budget:.2f} cannot fund one contract at ${per_contract:.2f}",
            budget,
        )

    total = qty * per_contract
    return SizingDecision(
        approved=True,
        qty=qty,
        reason=(
            f"{qty} contract(s) x ${per_contract:.2f} max loss = ${total:.2f}; "
            f"budget ${budget:.2f}; net EV ${ev.net_ev * qty:.2f}"
        ),
        max_loss_total=total,
        risk_budget_remaining=budget - total,
    )


def pin_risk(ev_short_strike: float, spot: float, threshold_pct: float = 0.25) -> tuple[bool, float]:
    """How close the underlying is to the short strike, as a percentage.

    Returns (breached, distance_pct). Negative distance means the short
    strike is already through — the case where settling is no longer free
    and the position has to be closed into the widest spreads of the day.
    """
    distance_pct = (spot - ev_short_strike) / spot * 100.0
    return distance_pct <= threshold_pct, round(distance_pct, 3)
