"""Pin-risk watch and emergency close.

Settling for free only works while the short strike stays out of the money.
Once it is threatened the position has to be closed, into the widest spreads
of the day - which is precisely the cost this agent exists to avoid. So an
emergency close is journalled as a cost event, with the price paid recorded
against the exit we would otherwise not have taken.

    python -m agent.monitor --loop --interval 60
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import chain, cli, config, execute, journal, risk

ET = ZoneInfo("America/New_York")
_stop = False


def _handle_stop(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True


@dataclass
class OpenSpread:
    underlying: str
    expiry: str
    short_symbol: str
    long_symbol: str
    short_strike: float
    long_strike: float
    qty: int
    credit_fill: float
    entry_cost: float
    max_loss: float
    order_id: str | None
    client_order_id: str


def open_spreads(profile: str) -> list[OpenSpread]:
    """Reconstruct live spreads by intersecting the journal's submitted
    orders with the positions the broker actually reports."""
    held = {
        p.get("symbol"): p for p in cli.positions(profile=profile)
        if p.get("asset_class") == "us_option"
    }
    if not held:
        return []

    submitted = {}
    for r in journal.read_all():
        if r.get("kind") == "order_intent" and not r.get("dry_run"):
            submitted[r.get("client_order_id")] = r
    closed = {
        r.get("client_order_id") for r in journal.read_all()
        if r.get("kind") in ("emergency_close", "settlement")
    }

    out: list[OpenSpread] = []
    for coid, rec in submitted.items():
        if coid in closed:
            continue
        ev = rec.get("evaluation") or {}
        short_sym, long_sym = ev.get("short"), ev.get("long")
        if short_sym not in held:
            continue
        parsed_s = chain.parse_occ(short_sym or "")
        parsed_l = chain.parse_occ(long_sym or "")
        if not parsed_s or not parsed_l:
            continue
        out.append(OpenSpread(
            underlying=ev.get("underlying") or parsed_s[0],
            expiry=parsed_s[2],
            short_symbol=short_sym, long_symbol=long_sym,
            short_strike=parsed_s[1], long_strike=parsed_l[1],
            qty=int(rec.get("qty") or 0),
            credit_fill=float(ev.get("credit_fill") or 0),
            entry_cost=float(ev.get("entry_cost") or 0),
            max_loss=float(ev.get("max_loss") or 0),
            order_id=None, client_order_id=coid,
        ))
    return out


def current_close_cost(sp: OpenSpread, profile: str) -> dict | None:
    """What it would cost right now to buy the package back: pay the ask on
    the short leg, hit the bid on the long."""
    try:
        payload = cli.run(
            "data", "option", "snapshot", "--symbols", f"{sp.short_symbol},{sp.long_symbol}",
            "--feed", config.OPTION_FEED, profile=profile, journal_kind=None,
        )
    except Exception:
        return None
    snaps = (payload or {}).get("snapshots") or {}
    s = (snaps.get(sp.short_symbol) or {}).get("latestQuote") or {}
    l = (snaps.get(sp.long_symbol) or {}).get("latestQuote") or {}
    if not s or not l:
        return None
    s_bid, s_ask = float(s.get("bp") or 0), float(s.get("ap") or 0)
    l_bid, l_ask = float(l.get("bp") or 0), float(l.get("ap") or 0)
    if s_ask <= 0:
        return None
    debit_to_close = s_ask - l_bid
    mid_to_close = ((s_bid + s_ask) / 2) - ((l_bid + l_ask) / 2)
    return {
        "debit_to_close": round(debit_to_close, 4),
        "mid_to_close": round(mid_to_close, 4),
        "exit_cost_now": round((debit_to_close - mid_to_close) * 100 * sp.qty, 2),
        "short_bid": s_bid, "short_ask": s_ask, "long_bid": l_bid, "long_ask": l_ask,
    }


def check(profile: str, threshold_pct: float, live: bool, arm: str | None) -> list[dict]:
    spreads = open_spreads(profile)
    if not spreads:
        return []

    results = []
    for sp in spreads:
        try:
            spot, source, _, _ = chain.reference_level(sp.underlying, sp.expiry, profile=profile)
        except Exception as exc:
            journal.write("monitor_error", underlying=sp.underlying, error=str(exc))
            continue

        breached, distance = risk.pin_risk(sp.short_strike, spot, threshold_pct)
        close_cost = current_close_cost(sp, profile)

        rec = {
            "underlying": sp.underlying,
            "spread": f"{sp.short_strike:g}/{sp.long_strike:g}",
            "qty": sp.qty,
            "spot": round(spot, 3),
            "spot_source": source,
            "distance_to_short_pct": distance,
            "breached": breached,
            "entry_cost_paid": sp.entry_cost,
            **(close_cost or {}),
        }
        journal.write("monitor", **rec)
        results.append(rec)

        if breached and live:
            _emergency_close(sp, close_cost, spot, distance, profile, arm)
    return results


def _emergency_close(sp, close_cost, spot, distance, profile, arm) -> None:
    """Close the package and book the exit cost explicitly."""
    if not close_cost:
        journal.write("emergency_close_failed", client_order_id=sp.client_order_id,
                      reason="no quotes available to price the close")
        return

    from .cost import Evaluation  # local import to avoid a cycle at module load

    stub = Evaluation(
        underlying=sp.underlying, expiry=sp.expiry,
        short_strike=sp.short_strike, long_strike=sp.long_strike,
        short_symbol=sp.short_symbol, long_symbol=sp.long_symbol,
        width=sp.short_strike - sp.long_strike,
        credit_mid=0, credit_fill=sp.credit_fill, entry_cost=sp.entry_cost,
        entry_cost_pct_of_credit=0, exit_cost_if_closed=0, round_trip_cost=0,
        max_profit=0, max_loss=sp.max_loss, prob_short_itm=0, prob_max_profit=0,
        expected_payoff=0, net_ev=0, net_ev_mid_naive=0, net_ev_if_round_tripped=0,
        return_on_risk=0, iv_short=None, iv_long=None, sigma_used=0,
        delta_short=0, moneyness_pct=0, exit_cost_projected=0,
        net_ev_if_round_tripped_projected=0, admissible=True, reject_reason=None,
    )
    payload = execute.build_close_payload(stub, sp.qty, close_cost["debit_to_close"])

    journal.write(
        "emergency_close_intent",
        client_order_id=sp.client_order_id, spot=round(spot, 3),
        distance_to_short_pct=distance, payload=payload, **close_cost,
    )
    try:
        raw = execute._post_order(payload, profile)
    except Exception as exc:
        journal.write("emergency_close_failed", client_order_id=sp.client_order_id,
                      error=str(exc))
        return

    realized = (sp.credit_fill - close_cost["debit_to_close"]) * 100 * sp.qty
    journal.write(
        "emergency_close",
        client_order_id=sp.client_order_id, order_id=raw.get("id"),
        status=raw.get("status"),
        credit_received=sp.credit_fill, debit_paid=close_cost["debit_to_close"],
        realized_pnl=round(realized, 2),
        exit_cost_paid=close_cost["exit_cost_now"],
        note=("Short strike breached: settling for free was no longer available, "
              "so the exit spread had to be paid. Booked as a cost event."),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pin-risk monitor")
    ap.add_argument("--profile", default=config.PROFILE_DEV, choices=["dev", "comp"])
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--threshold", type=float, default=0.25,
                    help="close when spot is within this %% of the short strike")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--live", action="store_true", help="actually place the closing order")
    ap.add_argument("--arm")
    args = ap.parse_args(argv)

    if args.profile == config.PROFILE_COMP and args.live and args.arm != execute.COMP_ARM_TOKEN:
        print("refusing: live close on COMP needs --arm (R4).", file=sys.stderr)
        return 2

    signal.signal(signal.SIGINT, _handle_stop)
    print(f"monitor | profile={args.profile} | threshold={args.threshold}% | "
          f"{'LIVE' if args.live else 'observe only'}", flush=True)

    while not _stop:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = check(args.profile, args.threshold, args.live, args.arm)
        if not rows:
            print(f"{stamp}  no open spreads", flush=True)
        for r in rows:
            flag = "BREACHED" if r["breached"] else "ok"
            print(f"{stamp}  {r['underlying']} {r['spread']} x{r['qty']}  "
                  f"spot={r['spot']}  dist={r['distance_to_short_pct']}%  {flag}", flush=True)
        if not args.loop:
            break
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
