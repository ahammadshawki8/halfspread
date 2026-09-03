"""The agent. Preflight, scan, size, veto, execute, journal.

    python -m agent.run --once                       # one cycle, dry run on dev
    python -m agent.run --once --live                # one cycle, real order on dev
    python -m agent.run --loop --interval 600        # session loop on dev
    python -m agent.run --loop --profile comp --live --arm ARM-COMP-I-MEAN-IT
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import chain, cli, config, cost, execute, journal, llm, risk, scan

ET = ZoneInfo("America/New_York")
_stop = False


def _handle_stop(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True
    print("\nstopping after current cycle...", file=sys.stderr)


class Preflight(Exception):
    pass


def preflight(profile: str, require_open: bool = True) -> dict:
    """Refuse to trade unless the world looks the way we expect."""
    clock = cli.clock(profile=profile)
    acct = cli.account(profile=profile)

    now_et = datetime.now(ET)
    state = {
        "market_open": bool(clock.get("is_open")),
        "now_et": now_et.strftime("%Y-%m-%d %H:%M:%S"),
        "equity": float(acct.get("equity") or 0),
        "cash": float(acct.get("cash") or 0),
        "options_level": acct.get("options_trading_level"),
        "account_number": acct.get("account_number"),
        "status": acct.get("status"),
        "past_odte_cutoff": now_et.strftime("%H:%M") >= config.ODTE_ENTRY_CUTOFF_ET,
    }

    if acct.get("status") != "ACTIVE":
        raise Preflight(f"account status {acct.get('status')}, expected ACTIVE")
    if int(acct.get("options_trading_level") or 0) < 3:
        raise Preflight(f"options level {acct.get('options_trading_level')}, need 3")
    if require_open and not state["market_open"]:
        raise Preflight(f"market closed (next open {clock.get('next_open')})")

    journal.write("preflight", profile=profile, **state)
    return state


def choose(
    expiries: list[str], profile: str
) -> tuple[cost.Evaluation | None, list[cost.Evaluation]]:
    """Scan every underlying across every candidate expiry and return the best.

    The expiry is a decision, not a default. Measured live on 2026-09-03 at
    14:00 UTC, every admissible same-day candidate had negative net EV with six
    hours to run, while the next session's expiry was positive across the board
    - there is simply more time value to sell. Letting the ranking pick the
    expiry, rather than always reaching for 0DTE, is the same discipline the
    rest of the agent applies to strikes.
    """
    everything: list[cost.Evaluation] = []
    for expiry in expiries:
        for u in sorted(config.UNIVERSE, key=lambda x: x != "SPY"):
            try:
                everything.extend(scan.scan_underlying(u, expiry, profile))
            except Exception as exc:
                journal.write("scan_error", underlying=u, expiry=expiry, error=str(exc))
    if not everything:
        return None, []
    everything.sort(key=lambda e: e.return_on_risk, reverse=True)
    return everything[0], everything


def cycle(
    profile: str,
    expiry: str | None = None,
    live: bool = False,
    arm: str | None = None,
    use_veto: bool = True,
    require_open: bool = True,
) -> dict:
    """One decision. Returns a summary dict; everything is also journalled."""
    state = preflight(profile, require_open=require_open)

    if expiry is None:
        days = chain.next_expiries(3, profile=profile)
        if not days:
            raise Preflight("calendar returned no trading days")
        # After the 0DTE cutoff today's expiry can no longer be opened.
        expiries = days[1:3] if state["past_odte_cutoff"] else days[0:2]
    else:
        expiries = [expiry]

    best, all_evals = choose(expiries, profile)
    if best is None:
        journal.write("no_trade", reason="no admissible candidate", expiries=expiries)
        return {"action": "no_trade", "reason": "no admissible candidate",
                "expiries": expiries}
    expiry = best.expiry

    positions = cli.positions(profile=profile)
    sizing = risk.size(best, positions, profile=profile)
    journal.write(
        "sizing",
        approved=sizing.approved, qty=sizing.qty, reason=sizing.reason,
        max_loss_total=sizing.max_loss_total,
        candidate=f"{best.underlying} {best.short_strike:g}/{best.long_strike:g}",
    )
    if not sizing.approved:
        return {"action": "no_trade", "reason": sizing.reason, "expiry": expiry}

    qty = sizing.qty
    veto = llm.event_risk_veto(
        context=(
            f"{best.underlying} reference ~{best.short_strike / (1 + best.moneyness_pct / 100):.0f}, "
            f"{best.structure} at {best.short_strike:g}/{best.long_strike:g}, "
            f"expiry {expiry}, held to settlement, {qty} contracts, "
            f"max loss ${sizing.max_loss_total:.0f} on a ${state['equity']:.0f} account. "
            f"Now {state['now_et']} ET."
        ),
        profile=profile,
        enabled=use_veto,
    )
    if veto.blocks:
        journal.write("no_trade", reason=f"event-risk veto: {veto.reason}",
                      events=veto.events, expiry=expiry)
        return {"action": "blocked", "reason": veto.reason, "events": veto.events}

    qty_after = max(1, int(qty * veto.size_multiplier)) if veto.size_multiplier > 0 else 0
    if qty_after < 1:
        journal.write("no_trade", reason="veto reduced size below one contract")
        return {"action": "blocked", "reason": "veto reduced size below one contract"}
    if qty_after != qty:
        journal.write("veto_applied", qty_before=qty, qty_after=qty_after,
                      multiplier=veto.size_multiplier, reason=veto.reason)

    result = execute.submit(
        best, qty_after, profile=profile, dry_run=not live, comp_arm=arm,
        note=f"veto={veto.action}({veto.size_multiplier})",
    )

    return {
        "action": "submitted" if live else "dry_run",
        "order_id": result.order_id,
        "status": result.status,
        "qty": qty_after,
        "candidate": f"{best.underlying} {best.structure} {best.short_strike:g}/{best.long_strike:g}",
        "credit_fill": best.credit_fill,
        "entry_cost": best.entry_cost,
        "max_loss_total": round(best.max_loss * qty_after, 2),
        "net_ev_total": round(best.net_ev * qty_after, 2),
        "veto": veto.action,
        "candidates_considered": len(all_evals),
        "expiry": expiry,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HALFSPREAD agent")
    ap.add_argument("--profile", default=config.PROFILE_DEV, choices=["dev", "comp"])
    ap.add_argument("--expiry")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--live", action="store_true", help="actually place orders")
    ap.add_argument("--arm", help=f"required for --profile comp --live")
    ap.add_argument("--no-veto", action="store_true")
    ap.add_argument("--allow-closed", action="store_true", help="skip the market-open check")
    args = ap.parse_args(argv)

    if args.profile == config.PROFILE_COMP and args.live and args.arm != execute.COMP_ARM_TOKEN:
        print("refusing: live trading on COMP needs --arm with the correct token (R4).",
              file=sys.stderr)
        return 2
    if not (args.once or args.loop):
        args.once = True

    signal.signal(signal.SIGINT, _handle_stop)
    try:
        signal.signal(signal.SIGTERM, _handle_stop)
    except (AttributeError, ValueError):
        pass

    mode = "LIVE" if args.live else "dry-run"
    print(f"halfspread agent | profile={args.profile} | {mode} | "
          f"veto={'off' if args.no_veto else 'on'}", flush=True)

    n = 0
    while not _stop:
        n += 1
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            out = cycle(
                profile=args.profile, expiry=args.expiry, live=args.live,
                arm=args.arm, use_veto=not args.no_veto,
                require_open=not args.allow_closed,
            )
            print(f"[{n:>3}] {stamp}  {out}", flush=True)
        except Preflight as exc:
            print(f"[{n:>3}] {stamp}  preflight: {exc}", flush=True)
            journal.write("preflight_failed", reason=str(exc), profile=args.profile)
        except Exception as exc:
            print(f"[{n:>3}] {stamp}  ERROR {type(exc).__name__}: {exc}", flush=True)
            journal.write("cycle_error", error=str(exc), kind_detail=type(exc).__name__)

        if not args.loop:
            break
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
