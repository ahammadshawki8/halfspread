"""Order construction and submission.

Every order is a multi-leg package with both legs covered inside the same
order, which is what Alpaca's Level 3 mleg rule requires. Orders are placed
as marketable limits at the measured fill price: Alpaca's paper engine only
fills marketable orders, so resting at mid would simply not trade. We pay
the entry spread deliberately, measure it, and then avoid paying it again by
settling instead of closing.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from . import cli, config, journal
from .cost import Evaluation

# Trading the competition account requires this to be passed explicitly at
# the call site. CLAUDE.md R4: COMP is never touched by hand or by accident.
COMP_ARM_TOKEN = "ARM-COMP-I-MEAN-IT"


class ExecutionRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    order_id: str | None
    client_order_id: str
    status: str
    filled_qty: float
    filled_avg_price: float | None
    raw: dict
    payload: dict


def build_payload(ev: Evaluation, qty: int, limit_price: float | None = None) -> dict:
    """Put credit spread as an mleg package.

    limit_price is the net credit as a positive number; Alpaca infers the
    direction of the package from the legs.
    """
    if qty < 1:
        raise ValueError("qty must be at least 1")
    price = ev.credit_fill if limit_price is None else limit_price
    if price <= 0:
        raise ValueError(f"credit must be positive, got {price}")

    return {
        "order_class": "mleg",
        "qty": str(qty),
        "type": "limit",
        "time_in_force": "day",
        "limit_price": f"{price:.2f}",
        "legs": [
            {
                "symbol": ev.short_symbol,
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": ev.long_symbol,
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_open",
            },
        ],
    }


def build_close_payload(ev: Evaluation, qty: int, limit_price: float) -> dict:
    """Unwind the same package. Used only for an emergency close, which is
    journalled as a cost event because it is the thing we exist to avoid."""
    return {
        "order_class": "mleg",
        "qty": str(qty),
        "type": "limit",
        "time_in_force": "day",
        "limit_price": f"{abs(limit_price):.2f}",
        "legs": [
            {
                "symbol": ev.short_symbol,
                "side": "buy",
                "ratio_qty": "1",
                "position_intent": "buy_to_close",
            },
            {
                "symbol": ev.long_symbol,
                "side": "sell",
                "ratio_qty": "1",
                "position_intent": "sell_to_close",
            },
        ],
    }


def _post_order(payload: dict, profile: str) -> dict:
    body = json.dumps(payload, separators=(",", ":"))
    return cli.run(
        "api", "POST", "/v2/orders", "--body", body,
        profile=profile, journal_kind="cli_order", timeout=45,
    )


def submit(
    ev: Evaluation,
    qty: int,
    profile: str = config.PROFILE_DEV,
    dry_run: bool = True,
    comp_arm: str | None = None,
    note: str = "",
) -> OrderResult:
    """Place the spread. dry_run builds and journals the payload without
    sending it."""
    if profile == config.PROFILE_COMP and comp_arm != COMP_ARM_TOKEN:
        raise ExecutionRefused(
            "COMP requires an explicit arming token (CLAUDE.md R4). Refusing."
        )

    payload = build_payload(ev, qty)
    client_order_id = f"hs-{uuid.uuid4().hex[:16]}"
    payload["client_order_id"] = client_order_id

    journal.write(
        "order_intent",
        profile=profile,
        dry_run=dry_run,
        note=note,
        client_order_id=client_order_id,
        qty=qty,
        payload=payload,
        evaluation={
            "underlying": ev.underlying,
            "short": ev.short_symbol,
            "long": ev.long_symbol,
            "credit_mid": ev.credit_mid,
            "credit_fill": ev.credit_fill,
            "entry_cost": ev.entry_cost,
            "entry_cost_pct_of_credit": ev.entry_cost_pct_of_credit,
            "exit_cost_if_closed": ev.exit_cost_if_closed,
            "exit_cost_projected": ev.exit_cost_projected,
            "max_loss": ev.max_loss,
            "max_profit": ev.max_profit,
            "prob_max_profit": ev.prob_max_profit,
            "net_ev": ev.net_ev,
            "net_ev_mid_naive": ev.net_ev_mid_naive,
            "net_ev_if_round_tripped_projected": ev.net_ev_if_round_tripped_projected,
        },
    )

    if dry_run:
        return OrderResult(
            ok=True, order_id=None, client_order_id=client_order_id,
            status="dry_run", filled_qty=0.0, filled_avg_price=None,
            raw={}, payload=payload,
        )

    raw = _post_order(payload, profile)
    result = OrderResult(
        ok=bool(raw.get("id")),
        order_id=raw.get("id"),
        client_order_id=raw.get("client_order_id", client_order_id),
        status=str(raw.get("status") or "unknown"),
        filled_qty=float(raw.get("filled_qty") or 0),
        filled_avg_price=(
            float(raw["filled_avg_price"]) if raw.get("filled_avg_price") else None
        ),
        raw=raw, payload=payload,
    )
    journal.write(
        "order_submitted",
        profile=profile, order_id=result.order_id,
        client_order_id=result.client_order_id, status=result.status,
        filled_qty=result.filled_qty, filled_avg_price=result.filled_avg_price,
        legs=[{"symbol": l.get("symbol"), "status": l.get("status"),
               "filled_qty": l.get("filled_qty"),
               "filled_avg_price": l.get("filled_avg_price")}
              for l in (raw.get("legs") or [])],
    )
    return result


def get_order(order_id: str, profile: str = config.PROFILE_DEV) -> dict:
    return cli.run("order", "get", "--order-id", order_id, profile=profile)


def cancel(order_id: str, profile: str = config.PROFILE_DEV) -> dict:
    res = cli.run("order", "cancel", "--order-id", order_id, profile=profile,
                  allow_empty=True, journal_kind="cli_order")
    journal.write("order_cancelled", profile=profile, order_id=order_id)
    return res or {}


def realized_fill_cost(ev: Evaluation, filled_avg_price: float | None, qty: int) -> dict:
    """Compare the credit we actually received against mid and against the
    price we modelled. This is the post-trade half of the thesis."""
    if filled_avg_price is None:
        return {}
    credit_actual = abs(filled_avg_price)
    slip_vs_model = (ev.credit_fill - credit_actual) * 100.0 * qty
    cost_vs_mid = (ev.credit_mid - credit_actual) * 100.0 * qty
    return {
        "credit_mid": ev.credit_mid,
        "credit_modelled_fill": ev.credit_fill,
        "credit_actual": round(credit_actual, 4),
        "entry_cost_actual": round(cost_vs_mid, 2),
        "slippage_vs_model": round(slip_vs_model, 2),
        "qty": qty,
    }
