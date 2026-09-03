"""Intraday spread-widening recorder.

Entry and exit half-spreads are identical at a single instant, so the claim
that "the exit is where the money dies" is a claim about *time*: liquidity in
far-OTM 0DTE strikes evaporates through the session, and the trade you have
to close at 15:45 is not the trade you opened at 10:00.

This process re-quotes the same strikes on a fixed cadence and journals the
curve, so the widening factor used by cost.py is measured on the day rather
than assumed. Runs read-only and places no orders.

    python -m agent.observe --interval 300
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timezone

from . import chain, cli, config, journal

_stop = False


def _handle_stop(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True
    print("\nstopping after current cycle...", file=sys.stderr)


def snapshot(underlying: str, expiry: str, profile: str) -> dict | None:
    """One observation of the whole cost curve for one underlying."""
    try:
        spot, source, puts, _ = chain.reference_level(underlying, expiry, profile=profile)
    except Exception as exc:
        journal.write("observe_error", underlying=underlying, expiry=expiry, error=str(exc))
        return None

    chain.remember_center(underlying, spot)
    rows = []
    for c in puts:
        if not c.tradeable:
            continue
        hp = c.half_spread_pct
        if hp is None:
            continue
        rows.append({
            "strike": c.strike,
            "moneyness_pct": round((c.strike - spot) / spot * 100, 3),
            "bid": c.bid, "ask": c.ask,
            "mid": round(c.mid, 4),
            "width": round(c.width, 4),
            "half_spread_pct": round(hp * 100, 3),
            "bid_size": c.bid_size, "ask_size": c.ask_size,
        })

    rec = journal.write(
        "observation",
        underlying=underlying, expiry=expiry,
        reference_level=round(spot, 4), reference_source=source,
        strikes=len(rows), rows=rows,
    )
    return rec


def _band(rows: list[dict], lo: float, hi: float) -> float | None:
    """Median half-spread% for strikes in a moneyness band."""
    vals = sorted(r["half_spread_pct"] for r in rows if lo <= r["moneyness_pct"] < hi)
    if not vals:
        return None
    return vals[len(vals) // 2]


BANDS = [(-1.0, 0.0), (-2.0, -1.0), (-3.0, -2.0), (-5.0, -3.0)]


def widening_report(underlying: str | None = None) -> dict:
    """Compare each observation's cost curve against the session's first,
    per moneyness band. This is the exhibit."""
    obs = [r for r in journal.read() if r.get("kind") == "observation"]
    if underlying:
        obs = [r for r in obs if r.get("underlying") == underlying]
    if not obs:
        return {}

    by_under: dict[str, list[dict]] = {}
    for r in obs:
        by_under.setdefault(r["underlying"], []).append(r)

    report: dict = {}
    for u, records in by_under.items():
        records.sort(key=lambda r: r["ts"])
        base = records[0]
        base_bands = {f"{lo}:{hi}": _band(base["rows"], lo, hi) for lo, hi in BANDS}
        series = []
        for r in records:
            cur = {f"{lo}:{hi}": _band(r["rows"], lo, hi) for lo, hi in BANDS}
            ratios = {
                k: round(cur[k] / base_bands[k], 3)
                for k in cur
                if cur.get(k) and base_bands.get(k)
            }
            series.append({"ts": r["ts"], "half_spread_pct": cur, "vs_open": ratios})
        report[u] = {
            "first_observation": base["ts"],
            "observations": len(records),
            "baseline": base_bands,
            "series": series,
            "latest_widening": series[-1]["vs_open"] if series else {},
        }
    return report


def measured_widening(underlying: str) -> float | None:
    """Single widening multiplier for cost.py, taken from the near-OTM bands."""
    rep = widening_report(underlying).get(underlying)
    if not rep:
        return None
    latest = rep.get("latest_widening") or {}
    vals = [v for v in latest.values() if v and v > 0]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 3)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Intraday spread-widening recorder")
    ap.add_argument("--interval", type=int, default=300, help="seconds between cycles")
    ap.add_argument("--underlying", action="append")
    ap.add_argument("--expiry")
    ap.add_argument("--profile", default=config.PROFILE_DEV, choices=["dev", "comp"])
    ap.add_argument("--until-close", action="store_true", help="stop when the market closes")
    ap.add_argument("--report", action="store_true", help="print the widening report and exit")
    args = ap.parse_args(argv)

    if args.report:
        import json
        print(json.dumps(widening_report(), indent=2, default=str))
        return 0

    expiry = args.expiry
    if not expiry:
        days = chain.next_expiries(2, profile=args.profile)
        if not days:
            print("no trading days from the calendar", file=sys.stderr)
            return 1
        expiry = days[0]

    underlyings = sorted(args.underlying or config.UNIVERSE, key=lambda u: u != "SPY")

    signal.signal(signal.SIGINT, _handle_stop)
    try:
        signal.signal(signal.SIGTERM, _handle_stop)
    except (AttributeError, ValueError):
        pass

    print(f"observing {underlyings} expiry={expiry} every {args.interval}s", flush=True)
    cycle = 0
    while not _stop:
        cycle += 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        parts = []
        for u in underlyings:
            rec = snapshot(u, expiry, args.profile)
            if rec:
                near = _band(rec["rows"], -1.0, 0.0)
                far = _band(rec["rows"], -3.0, -2.0)
                parts.append(
                    f"{u} ref={rec['reference_level']:.2f} "
                    f"near={near if near is None else f'{near:.2f}%'} "
                    f"far={far if far is None else f'{far:.2f}%'}"
                )
        print(f"[{cycle:>3}] {now}  " + " | ".join(parts), flush=True)

        if args.until_close:
            try:
                if not (cli.clock(profile=args.profile) or {}).get("is_open", True):
                    if cycle > 1:
                        print("market closed, stopping", flush=True)
                        break
            except Exception:
                pass

        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)

    rep = widening_report()
    journal.write("widening_report", report=rep)
    for u, r in rep.items():
        print(f"{u}: {r['observations']} observations, widening vs open {r['latest_widening']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
