"""Settlement accounting and the counterfactual.

When a spread expires out of the money there is no closing trade, so the
exit costs nothing. This module proves that rather than asserting it: it
records the last quotes before the close, computes what buying the package
back at that moment would have cost, and reports the realised result both
ways - as settled, and as it would have been had the position been closed
like almost every other agent in this competition closes theirs.

    python -m agent.settle --report
    python -m agent.settle --snapshot        # capture pre-close quotes
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import chain, cli, config, journal, monitor

ET = ZoneInfo("America/New_York")


def snapshot_preclose(profile: str) -> list[dict]:
    """Record what closing would have cost, just before the bell. This is the
    counterfactual's evidence and it can only be gathered while quotes live."""
    out = []
    for sp in monitor.open_spreads(profile):
        cc = monitor.current_close_cost(sp, profile)
        if not cc:
            continue
        rec = {
            "client_order_id": sp.client_order_id,
            "underlying": sp.underlying,
            "spread": f"{sp.short_strike:g}/{sp.long_strike:g}",
            "qty": sp.qty,
            "entry_cost_paid": sp.entry_cost,
            "would_pay_to_close": cc["debit_to_close"],
            "exit_cost_if_closed_now": cc["exit_cost_now"],
            "widening_vs_entry": (
                round(cc["exit_cost_now"] / sp.entry_cost, 2) if sp.entry_cost else None
            ),
        }
        journal.write("preclose_snapshot", **rec)
        out.append(rec)
    return out


def settle(profile: str) -> list[dict]:
    """Resolve expired spreads against the reference level at expiry.

    A contract expiring today has NOT expired until the close. Comparing only
    the dates resolves live positions hours early and books P&L that does not
    exist, so same-day expiries additionally require the market to be shut.
    """
    results = []
    now_et = datetime.now(ET)
    today = now_et.date().isoformat()
    try:
        market_open = bool((cli.clock(profile=profile) or {}).get("is_open"))
    except Exception:
        # Fail closed: if the clock is unreachable, do not resolve anything.
        market_open = True

    for sp in monitor.open_spreads(profile):
        if sp.expiry > today:
            continue
        if sp.expiry == today and market_open:
            continue

        try:
            spot, source, _, _ = chain.reference_level(sp.underlying, sp.expiry, profile=profile)
        except Exception as exc:
            journal.write("settle_error", client_order_id=sp.client_order_id, error=str(exc))
            continue

        short_itm = spot < sp.short_strike
        long_itm = spot < sp.long_strike
        width = sp.short_strike - sp.long_strike

        if not short_itm:
            intrinsic = 0.0
        elif long_itm:
            intrinsic = width
        else:
            intrinsic = sp.short_strike - spot

        realized = (sp.credit_fill - intrinsic) * 100 * sp.qty

        pre = _last_preclose(sp.client_order_id)
        exit_cost_avoided = pre.get("exit_cost_if_closed_now") if pre else None
        realized_if_closed = (
            round(realized - exit_cost_avoided, 2) if exit_cost_avoided is not None else None
        )

        rec = {
            "client_order_id": sp.client_order_id,
            "profile": profile,
            "underlying": sp.underlying,
            "expiry": sp.expiry,
            "spread": f"{sp.short_strike:g}/{sp.long_strike:g}",
            "qty": sp.qty,
            "settlement_level": round(spot, 3),
            "settlement_source": source,
            "short_finished_itm": short_itm,
            "intrinsic_at_expiry": round(intrinsic, 4),
            "credit_received": sp.credit_fill,
            "entry_cost_paid": sp.entry_cost,
            "exit_cost_paid": 0.0,
            "realized_pnl": round(realized, 2),
            "exit_cost_avoided": exit_cost_avoided,
            "realized_pnl_if_round_tripped": realized_if_closed,
            "note": (
                "Expired out of the money. No closing trade, so no exit spread was paid."
                if not short_itm else
                "Finished in the money and settled at intrinsic. No closing trade was made."
            ),
        }
        journal.write("settlement", **rec)
        results.append(rec)
    return results


def _last_preclose(client_order_id: str) -> dict | None:
    best = None
    for r in journal.read_all():
        if r.get("kind") == "preclose_snapshot" and r.get("client_order_id") == client_order_id:
            best = r
    return best


def report(profile: str = config.PROFILE_DEV) -> dict:
    """The headline: what we made, what the spread cost us, and what settling
    instead of closing was worth."""
    records = journal.read_all()
    # Settlements and closes are per-account. Summing across profiles would
    # attribute DEV experiments to the competition ledger.
    settlements = [r for r in records
                   if r.get("kind") == "settlement" and r.get("profile") == profile]
    emergencies = [r for r in records
                   if r.get("kind") == "emergency_close" and r.get("profile") == profile]

    def _f(v) -> float:
        return float(v) if isinstance(v, (int, float)) else 0.0

    realized = sum(_f(r.get("realized_pnl")) for r in settlements + emergencies)
    entry_costs = sum(_f(r.get("entry_cost_paid")) for r in settlements + emergencies)
    exit_paid = sum(_f(r.get("exit_cost_paid")) for r in settlements + emergencies)
    exit_avoided = sum(_f(r.get("exit_cost_avoided")) for r in settlements)

    counterfactual = sum(
        _f(r.get("realized_pnl_if_round_tripped"))
        if r.get("realized_pnl_if_round_tripped") is not None
        else _f(r.get("realized_pnl"))
        for r in settlements + emergencies
    )

    wins = sum(1 for r in settlements if _f(r.get("realized_pnl")) > 0)
    n = len(settlements) + len(emergencies)

    try:
        acct = cli.account(profile=profile)
        equity = float(acct.get("equity") or 0)
    except Exception:
        equity = 0.0

    out = {
        "positions_resolved": n,
        "settled_at_expiry": len(settlements),
        "closed_early": len(emergencies),
        "wins": wins,
        "win_rate": round(wins / len(settlements), 3) if settlements else None,
        "realized_pnl": round(realized, 2),
        "entry_cost_paid": round(entry_costs, 2),
        "exit_cost_paid": round(exit_paid, 2),
        "exit_cost_avoided_by_settling": round(exit_avoided, 2),
        "realized_pnl_if_round_tripped": round(counterfactual, 2),
        "advantage_from_not_exiting": round(realized - counterfactual, 2),
        "account_equity": equity,
    }
    journal.write("settlement_report", **out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Settlement accounting")
    ap.add_argument("--profile", default=config.PROFILE_DEV, choices=["dev", "comp"])
    ap.add_argument("--snapshot", action="store_true", help="capture pre-close quotes")
    ap.add_argument("--settle", action="store_true", help="resolve expired spreads")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)

    if args.snapshot:
        for r in snapshot_preclose(args.profile):
            print(f"{r['underlying']} {r['spread']} x{r['qty']}: closing now would cost "
                  f"${r['exit_cost_if_closed_now']:.2f} "
                  f"({r['widening_vs_entry']}x the ${r['entry_cost_paid']:.2f} entry)")
    if args.settle:
        for r in settle(args.profile):
            print(f"{r['underlying']} {r['spread']} x{r['qty']}: "
                  f"settled at {r['settlement_level']}, P&L ${r['realized_pnl']:.2f} "
                  f"({'OTM, expired free' if not r['short_finished_itm'] else 'ITM'})")
    if args.report or not (args.snapshot or args.settle):
        import json as _json
        print(_json.dumps(report(args.profile), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
