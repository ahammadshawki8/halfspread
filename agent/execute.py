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

    Alpaca signs the mleg limit price from the package's point of view:
    a POSITIVE limit is the maximum net DEBIT you will pay, a NEGATIVE limit
    is the minimum net CREDIT you require. Verified on 2026-09-03: an order
    sent at +0.16 filled at -0.12, i.e. it behaved as a debit ceiling and so
    was effectively a market order, while -0.60 was accepted and correctly
    rested unfilled. Credit spreads must therefore be submitted negative.
    """
    if qty < 1:
        raise ValueError("qty must be at least 1")
    credit = ev.credit_fill if limit_price is None else limit_price
    if credit <= 0:
        raise ValueError(f"credit must be positive, got {credit}")

    if ev.legs:
        legs = [
            {"symbol": l["symbol"], "side": l["side"], "ratio_qty": "1",
             "position_intent": l["position_intent"]}
            for l in ev.legs
        ]
    else:
        legs = [
            {"symbol": ev.short_symbol, "side": "sell", "ratio_qty": "1",
             "position_intent": "sell_to_open"},
            {"symbol": ev.long_symbol, "side": "buy", "ratio_qty": "1",
             "position_intent": "buy_to_open"},
        ]

    return {
        "order_class": "mleg",
        "qty": str(qty),
        "type": "limit",
        "time_in_force": "day",
        "limit_price": f"{-abs(credit):.2f}",
        "legs": legs,
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


def requote(ev: Evaluation, profile: str) -> dict | None:
    """Re-read both legs immediately before submitting.

    Scanning the whole universe takes time, and at the open the market moves
    inside that window. Pricing off a stale scan is itself an execution cost,
    so the limit is set from quotes taken seconds before the order goes out
    and the difference is journalled as decision-to-execution slippage.
    """
    if ev.legs:
        spec = [(l["symbol"], l["side"]) for l in ev.legs]
    else:
        spec = [(ev.short_symbol, "sell"), (ev.long_symbol, "buy")]

    try:
        payload = cli.run(
            "data", "option", "snapshot",
            "--symbols", ",".join(sym for sym, _ in spec),
            "--feed", config.OPTION_FEED, profile=profile, journal_kind=None,
        )
    except Exception:
        return None
    snaps = (payload or {}).get("snapshots") or {}

    credit_now = credit_mid_now = 0.0
    quotes = {}
    for sym, side in spec:
        q = (snaps.get(sym) or {}).get("latestQuote") or {}
        bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
        if ask <= 0:
            return None
        quotes[sym] = {"bid": bid, "ask": ask}
        mid = (bid + ask) / 2
        # Sell the shorts at the bid, buy the longs at the ask.
        credit_now += bid if side == "sell" else -ask
        credit_mid_now += mid if side == "sell" else -mid

    return {
        "credit_fill_now": round(credit_now, 4),
        "credit_mid_now": round(credit_mid_now, 4),
        "entry_cost_now": round((credit_mid_now - credit_now) * 100, 2),
        "drift_vs_scan": round((credit_now - ev.credit_fill) * 100, 2),
        "quotes": quotes,
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

    fresh = None if dry_run else requote(ev, profile)
    if fresh is not None:
        if fresh["credit_fill_now"] <= 0:
            journal.write("order_abandoned", profile=profile,
                          reason="re-quote shows no credit available",
                          candidate=f"{ev.underlying} {ev.short_strike:g}/{ev.long_strike:g}",
                          **fresh)
            raise ExecutionRefused("re-quote shows no credit available; not submitting")
        payload = build_payload(ev, qty, limit_price=fresh["credit_fill_now"])
    else:
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
        requote=fresh,
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

    # Follow it to a terminal state so the record shows what actually happened
    # rather than only what was asked for.
    if result.order_id:
        confirm_fill(result.order_id, profile)

    return result


def get_order(order_id: str, profile: str = config.PROFILE_DEV) -> dict:
    return cli.run("order", "get", "--order-id", order_id, profile=profile)


def confirm_fill(order_id: str, profile: str, attempts: int = 6, pause: float = 2.0) -> dict:
    """Follow an order to a terminal state and journal what actually happened.

    Submitting returns `pending_new` with nothing filled, so a journal that
    stops at the acknowledgement records every order as unfilled. Anyone
    reading it later, including us, would conclude the desk never traded.
    """
    import time as _time

    terminal = {"filled", "canceled", "expired", "rejected", "done_for_day"}
    raw: dict = {}
    for i in range(attempts):
        try:
            raw = get_order(order_id, profile=profile) or {}
        except Exception as exc:
            journal.write("fill_check_failed", order_id=order_id, profile=profile,
                          attempt=i + 1, error=str(exc))
            return {}
        if str(raw.get("status", "")).lower() in terminal:
            break
        _time.sleep(pause)

    legs = [
        {"symbol": l.get("symbol"), "side": l.get("side"), "status": l.get("status"),
         "filled_qty": l.get("filled_qty"),
         "filled_avg_price": l.get("filled_avg_price")}
        for l in (raw.get("legs") or [])
    ]
    filled_price = raw.get("filled_avg_price")
    record = {
        "order_id": order_id,
        "profile": profile,
        "status": raw.get("status"),
        "filled_qty": float(raw.get("filled_qty") or 0),
        # Alpaca signs an mleg fill from the package's point of view, so a
        # credit comes back negative. Store both so nothing has to be
        # re-derived from a sign convention later.
        "filled_avg_price": float(filled_price) if filled_price else None,
        "credit_received": abs(float(filled_price)) if filled_price else None,
        "legs": legs,
    }
    journal.write("order_filled", **record)
    return record


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
