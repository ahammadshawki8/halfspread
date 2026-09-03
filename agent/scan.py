"""Read-only scan: price every candidate spread and rank by net EV.

Places no orders. This is the Tier 1 proof and the evidence generator for
the cost-curve exhibit.

    python -m agent.scan                 # all underlyings, nearest expiry
    python -m agent.scan --underlying SPY --expiry 2026-09-03 --top 15
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import chain, config, cost, journal, pricing


def scan_underlying(
    underlying: str, expiry: str, profile: str, widths: list[float] | None = None
) -> list[cost.Evaluation]:
    scale = config.SPOT_SCALE.get(underlying, 1.0)
    widths = widths or [w * scale for w in config.SPREAD_WIDTHS]

    spot_equiv, source, puts, _calls = chain.reference_level(underlying, expiry, profile=profile)
    chain.remember_center(underlying, spot_equiv)

    T = pricing.year_fraction(chain.expiry_close_utc(expiry))
    candidates = cost.build_candidates(puts, underlying, expiry, widths)

    evals = [e for e in (cost.evaluate(c, spot_equiv, T) for c in candidates) if e]
    admissible = [e for e in evals if e.admissible]
    # Capital, not headline EV, is the binding constraint, so rank by return
    # on risk among the candidates that survived the gates.
    admissible.sort(key=lambda e: e.return_on_risk, reverse=True)

    journal.write(
        "scan",
        underlying=underlying,
        expiry=expiry,
        reference_level=round(spot_equiv, 4),
        reference_source=source,
        time_to_expiry_years=round(T, 8),
        contracts_seen=len(puts),
        candidates_built=len(candidates),
        candidates_priced=len(evals),
        candidates_admissible=len(admissible),
        rejections=_rejection_tally(evals),
        best=cost.to_dict(admissible[0]) if admissible else None,
    )
    return admissible


def _rejection_tally(evals: list[cost.Evaluation]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for e in evals:
        if e.reject_reason:
            key = e.reject_reason.split("(")[0].split(str(e.short_strike))[0].strip()
            key = " ".join(key.split()[:4])
            tally[key] = tally.get(key, 0) + 1
    return tally


def cost_curve(underlying: str, expiry: str, profile: str) -> list[dict]:
    """Half-spread as a percentage of mid across moneyness. The measurement
    that drives strike selection (CLAUDE.md 5.1 Finding 3)."""
    spot_equiv, source, puts, _ = chain.reference_level(underlying, expiry, profile=profile)
    rows = []
    for c in puts:
        if not c.tradeable:
            continue
        hp = c.half_spread_pct
        if hp is None:
            continue
        rows.append({
            "strike": c.strike,
            "moneyness_pct": round((c.strike - spot_equiv) / spot_equiv * 100, 3),
            "bid": c.bid, "ask": c.ask, "mid": round(c.mid, 4),
            "half_spread": round(c.half_spread, 4),
            "half_spread_pct": round(hp * 100, 2),
        })
    journal.write(
        "cost_curve", underlying=underlying, expiry=expiry,
        reference_level=round(spot_equiv, 4), reference_source=source, rows=rows,
    )
    return rows


def _fmt_table(evals: list[cost.Evaluation], top: int) -> str:
    head = (
        f"{'under':<6} {'short':>8} {'long':>8} {'%OTM':>6} {'delta':>6} "
        f"{'credit':>7} {'entry$':>7} {'cost%':>6} {'exit$':>7} "
        f"{'maxL$':>7} {'P(win)':>7} {'netEV$':>8} {'naive$':>8} {'RoR':>7}"
    )
    lines = [head, "-" * len(head)]
    for e in evals[:top]:
        lines.append(
            f"{e.underlying:<6} {e.short_strike:>8.0f} {e.long_strike:>8.0f} "
            f"{e.moneyness_pct:>6.2f} {e.delta_short:>6.3f} "
            f"{e.credit_fill:>7.2f} {e.entry_cost:>7.2f} {e.entry_cost_pct_of_credit:>5.1f}% "
            f"{e.exit_cost_if_closed:>7.2f} {e.max_loss:>7.0f} {e.prob_max_profit:>7.3f} "
            f"{e.net_ev:>8.2f} {e.net_ev_mid_naive:>8.2f} {e.return_on_risk:>7.3f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HALFSPREAD read-only candidate scan")
    ap.add_argument("--underlying", action="append", help="repeatable; default: whole universe")
    ap.add_argument("--expiry", help="YYYY-MM-DD; default: nearest trading day")
    ap.add_argument("--profile", default=config.PROFILE_DEV, choices=["dev", "comp"])
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--curve", action="store_true", help="also print the cost curve")
    args = ap.parse_args(argv)

    if args.profile == config.PROFILE_COMP:
        print("refusing: scan runs on dev. COMP is reserved for the agent (R4).", file=sys.stderr)
        return 2

    expiry = args.expiry
    if not expiry:
        days = chain.next_expiries(2, profile=args.profile)
        if not days:
            print("no trading days returned by the calendar", file=sys.stderr)
            return 1
        expiry = days[0]

    underlyings = args.underlying or config.UNIVERSE
    # SPY first so its level seeds the strike window for the index symbols.
    underlyings = sorted(underlyings, key=lambda u: u != "SPY")

    print(f"scan @ {datetime.now(timezone.utc).isoformat(timespec='seconds')}  expiry={expiry}\n")

    all_evals: list[cost.Evaluation] = []
    for u in underlyings:
        try:
            evals = scan_underlying(u, expiry, args.profile)
        except Exception as exc:
            print(f"{u}: {type(exc).__name__}: {exc}", file=sys.stderr)
            journal.write("scan_error", underlying=u, expiry=expiry, error=str(exc))
            continue
        print(f"--- {u}: {len(evals)} priced candidates ---")
        if evals:
            print(_fmt_table(evals, args.top))
        print()
        all_evals.extend(evals)

        if args.curve:
            rows = cost_curve(u, expiry, args.profile)
            print(f"  cost curve ({len(rows)} strikes):")
            step = max(1, len(rows) // 12)
            for r in rows[::step]:
                print(f"    {r['strike']:>8.0f} {r['moneyness_pct']:>7.2f}%  "
                      f"mid {r['mid']:>7.3f}  half-spread {r['half_spread_pct']:>6.2f}%")
            print()

    if all_evals:
        all_evals.sort(key=lambda e: e.return_on_risk, reverse=True)
        print("=== best across universe ===")
        print(_fmt_table(all_evals, args.top))
        b = all_evals[0]
        print(
            f"\ntop candidate {b.underlying} {b.short_strike:.0f}/{b.long_strike:.0f}: "
            f"net EV ${b.net_ev:.2f} vs ${b.net_ev_mid_naive:.2f} priced at mid "
            f"(entry cost ${b.entry_cost:.2f} = {b.entry_cost_pct_of_credit:.1f}% of credit). "
            f"Closing instead of settling would cost a further ${b.exit_cost_if_closed:.2f}, "
            f"taking it to ${b.net_ev_if_round_tripped:.2f}."
        )
    else:
        print("no priceable candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
