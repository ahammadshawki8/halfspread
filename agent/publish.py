"""Turn the journal into the dashboard's data payload.

The dashboard renders nothing it computes itself. Every figure it shows is
derived here from the append-only journal, so the page and the write-up
cannot drift from the evidence.

    python -m agent.publish
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import cli, config, empirical, journal, observe, settle, verify

OUT = config.ROOT / "docs" / "data.json"


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build(profile: str = config.PROFILE_COMP) -> dict:
    records = journal.read_all()

    # The dashboard reports the COMPETITION account. DEV records live in the
    # same journal and must not be mixed into it.
    def _mine(r: dict) -> bool:
        return r.get("profile") == profile

    intents = [r for r in records
               if r.get("kind") == "order_intent" and not r.get("dry_run") and _mine(r)]
    submitted = [r for r in records if r.get("kind") == "order_submitted" and _mine(r)]
    settlements = [r for r in records if r.get("kind") == "settlement" and _mine(r)]
    emergencies = [r for r in records if r.get("kind") == "emergency_close" and _mine(r)]
    vetoes = [r for r in records if r.get("kind") == "veto"]
    refusals = [r for r in records if r.get("kind") in ("no_trade", "sizing")
                and not r.get("approved", True)]
    scans = [r for r in records if r.get("kind") == "scan"]

    # ---- the ledger -------------------------------------------------------
    ledger = settle.report(profile)

    # Entry cost is paid the moment an order fills, not when it settles, so
    # draw it from the orders themselves. Reporting $0 until settlement would
    # understate the one number this project exists to measure.
    entry_paid = 0.0
    for r in intents:
        ev = r.get("evaluation") or {}
        entry_paid += _f(ev.get("entry_cost")) * int(r.get("qty") or 0)
    ledger["entry_cost_paid"] = round(entry_paid, 2)

    # For positions still open, the exit spread is not yet avoided - it is at
    # stake. Report what closing them right now would cost, from the most
    # recent monitor reading, and label it as such on the page.
    # Keyed by the order that opened the position, and scoped to this account,
    # so DEV experiments and re-opened strikes cannot inflate the count.
    open_ids = {r.get("client_order_id") for r in intents}
    settled_ids = {r.get("client_order_id") for r in settlements + emergencies}
    live_ids = open_ids - settled_ids
    latest_close_cost: dict[str, float] = {}
    for r in records:
        if (r.get("kind") == "monitor" and _mine(r)
                and r.get("exit_cost_now") is not None
                and r.get("client_order_id") in live_ids):
            latest_close_cost[r["client_order_id"]] = _f(r["exit_cost_now"])
    ledger["exit_cost_at_stake"] = round(sum(latest_close_cost.values()), 2)
    ledger["open_positions_priced"] = len(latest_close_cost)

    fills = {r.get("order_id"): r for r in records
             if r.get("kind") == "order_filled" and _mine(r)}
    ledger["credit_received"] = round(
        sum(_f(r.get("credit_received")) * _f(r.get("filled_qty")) * 100
            for r in fills.values()), 2)
    ledger["orders_filled"] = len(fills)

    # ---- cost curve: the most recent observation per underlying ----------
    curves: dict[str, dict] = {}
    for r in records:
        if r.get("kind") != "observation":
            continue
        rows = [p for p in r.get("rows", []) if -5.0 <= p["moneyness_pct"] <= 1.0]
        # A contract quoted with a zero bid has no two-sided market: you cannot
        # sell it at any price, so its "half-spread" is not a cost, it is the
        # absence of a market. Charting those as 100% overstates the curve and
        # hides the shape. They are reported separately as the no-bid region.
        tradeable = [p for p in rows if (p.get("bid") or 0) > 0]
        nobid = [p for p in rows if (p.get("bid") or 0) <= 0]
        curves[r["underlying"]] = {
            "ts": r["ts"],
            "reference_level": r.get("reference_level"),
            "points": [
                {"m": p["moneyness_pct"], "hs": p["half_spread_pct"], "mid": p["mid"],
                 "strike": p["strike"]}
                for p in tradeable
            ],
            "no_bid_count": len(nobid),
            "no_bid_from_pct": max((p["moneyness_pct"] for p in nobid), default=None),
        }

    # ---- the hero: one real contract, quoted twice -------------------------
    # The thesis is not a chart, it is a gap. Find the near-the-money strike
    # observed both earliest and latest in the session and hand the page its
    # two quotes, so the page can show the same contract widening rather than
    # asserting that it did.
    spread_story = None
    traded: set = set()
    # Regular session only. A pre-market observation carries the previous
    # close's stale quotes and would flatter the comparison.
    spy_obs = sorted([r for r in records
                      if r.get("kind") == "observation" and r.get("underlying") == "SPY"
                      and "13:30" <= r["ts"][11:16] <= "20:00"],
                     key=lambda r: r["ts"])
    if len(spy_obs) >= 2:
        def near_money(rec):
            out = {}
            for row in rec.get("rows", []):
                if (row.get("bid") or 0) > 0 and -1.2 <= row["moneyness_pct"] <= 0.2:
                    out[row["strike"]] = row
            return out
        first, last = near_money(spy_obs[0]), near_money(spy_obs[-1])
        shared = set(first) & set(last)
        if shared:
            # Prefer a strike the agent actually shorted. That is the contract
            # it is carrying, so "what would leaving cost" is a real question
            # about a real position rather than an illustration. At-the-money
            # strikes stay penny-wide all day; the cost lives where we trade.
            traded = set()
            for r in intents:
                sym = (r.get("evaluation") or {}).get("short") or ""
                parsed = __import__("agent.chain", fromlist=["parse_occ"]).parse_occ(sym)
                if parsed and parsed[0] == "SPY":
                    traded.add(parsed[1])
            pool = (shared & traded) or shared
            k = max(pool, key=lambda s: last[s]["half_spread_pct"]) if (shared & traded)                 else min(pool, key=lambda s: abs(first[s]["moneyness_pct"]))
            a, b = first[k], last[k]
            if a["ask"] > a["bid"] and b["ask"] >= b["bid"] and a["half_spread_pct"] > 0:
                wa, wb = a["ask"] - a["bid"], b["ask"] - b["bid"]
                # The gap in cents can shrink as the option decays while the gap
                # as a share of what you are trading grows. The second number is
                # the one that costs you, so that is the one the page leads with.
                spread_story = {
                    "symbol": f"SPY {k:g} put",
                    "strike": k,
                    "open": {"ts": spy_obs[0]["ts"], "bid": a["bid"], "ask": a["ask"],
                             "mid": round((a["bid"] + a["ask"]) / 2, 4),
                             "width": round(wa, 4), "half_pct": a["half_spread_pct"]},
                    "latest": {"ts": spy_obs[-1]["ts"], "bid": b["bid"], "ask": b["ask"],
                               "mid": round((b["bid"] + b["ask"]) / 2, 4),
                               "width": round(wb, 4), "half_pct": b["half_spread_pct"]},
                    "times_wider": round(b["half_spread_pct"] / a["half_spread_pct"], 2),
                    "width_change": round(wb - wa, 4),
                    "is_held": k in traded,
                }

    # ---- widening through the session ------------------------------------
    widening = observe.widening_report()

    # ---- live chains, so the page can price a trade the visitor invents ----
    # The dashboard reports what the desk did. Without the chain it cannot let
    # anyone test the reasoning on a trade of their own, which is the only way
    # to tell a measurement engine apart from a screenshot of one.
    chains: dict = {}
    seen_pairs: set = set()
    for r in reversed(records):
        if r.get("kind") != "observation":
            continue
        key = (r["underlying"], r["expiry"])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        rows = [
            {"k": row["strike"], "b": row["bid"], "a": row["ask"]}
            for row in r.get("rows", [])
            if (row.get("bid") or 0) > 0 and -6.0 <= row["moneyness_pct"] <= 2.0
        ]
        if len(rows) < 6:
            continue
        chains.setdefault(r["underlying"], {})[r["expiry"]] = {
            "ts": r["ts"],
            "spot": r.get("reference_level"),
            "puts": sorted(rows, key=lambda x: x["k"]),
        }

    gates = {
        "min_prob_win": config.MIN_PROB_WIN,
        "min_credit_to_width": config.MIN_CREDIT_TO_WIDTH,
        "max_credit_to_width": config.MAX_CREDIT_TO_WIDTH,
        "min_credit_fill": config.MIN_CREDIT_FILL,
        "min_max_loss": config.MIN_MAX_LOSS,
        "max_loss_per_position": config.MAX_LOSS_PER_POSITION,
        "max_loss_per_day": config.MAX_LOSS_PER_DAY,
        "min_net_ev": config.MIN_NET_EV,
        "vrp_haircut": config.VRP_HAIRCUT,
        "risk_free_rate": config.RISK_FREE_RATE,
    }

    # ---- decisions, newest first -----------------------------------------
    decisions = []
    for r in records:
        k = r.get("kind")
        if k == "order_intent" and not r.get("dry_run") and _mine(r):
            ev = r.get("evaluation") or {}
            decisions.append({
                "ts": r["ts"], "type": "trade",
                "what": f"{ev.get('underlying')} {ev.get('short','')[-8:]}/{ev.get('long','')[-8:]}",
                "detail": (
                    f"{r.get('qty')}x credit {ev.get('credit_fill')} "
                    f"entry cost ${_f(ev.get('entry_cost')):.2f} "
                    f"({_f(ev.get('entry_cost_pct_of_credit')):.1f}% of credit), "
                    f"max loss ${_f(ev.get('max_loss')):.0f}"
                ),
            })
        elif k == "journal_correction":
            decisions.append({"ts": r["ts"], "type": "correction",
                              "what": "journal correction",
                              "detail": str(r.get("reason", ""))})
        elif k == "no_trade":
            decisions.append({"ts": r["ts"], "type": "refusal",
                              "what": "no trade", "detail": str(r.get("reason", ""))})
        elif k == "veto" and r.get("action") != "proceed":
            decisions.append({
                "ts": r["ts"], "type": "veto",
                "what": f"veto: {r.get('action')} x{r.get('size_multiplier')}",
                "detail": f"{r.get('reason','')} {r.get('events') or ''}",
            })
        elif k == "settlement" and _mine(r):
            decisions.append({
                "ts": r["ts"], "type": "settle",
                "what": f"{r.get('underlying')} {r.get('spread')} settled",
                "detail": (
                    f"P&L ${_f(r.get('realized_pnl')):.2f} at {r.get('settlement_level')}; "
                    f"exit cost paid ${_f(r.get('exit_cost_paid')):.2f}, "
                    f"avoided ${_f(r.get('exit_cost_avoided')):.2f}"
                ),
            })
        elif k == "emergency_close" and _mine(r):
            decisions.append({
                "ts": r["ts"], "type": "emergency",
                "what": "emergency close",
                "detail": (
                    f"P&L ${_f(r.get('realized_pnl')):.2f}, "
                    f"exit cost paid ${_f(r.get('exit_cost_paid')):.2f}"
                ),
            })
    decisions.reverse()

    # ---- account ----------------------------------------------------------
    account = {}
    try:
        a = cli.account(profile=profile)
        account = {
            "account_number": a.get("account_number"),
            "equity": _f(a.get("equity")),
            "cash": _f(a.get("cash")),
            "options_level": a.get("options_trading_level"),
            "starting_equity": config.ACCOUNT_EQUITY,
            "pnl": round(_f(a.get("equity")) - config.ACCOUNT_EQUITY, 2),
        }
    except Exception as exc:
        account = {"error": str(exc)}

    scan_totals = {
        "scans": len(scans),
        "candidates_priced": sum(int(r.get("candidates_priced") or 0) for r in scans),
        "candidates_admissible": sum(int(r.get("candidates_admissible") or 0) for r in scans),
    }

    # Re-run the credential-free verifier and publish its result, so the page
    # carries the same checks a stranger with a clone can run.
    try:
        checks, facts = verify.run()
        verification = {
            "passed": len(checks.rows) - checks.failed,
            "total": len(checks.rows),
            "failed": checks.failed,
            "rows": [{"ok": ok, "claim": claim, "evidence": ev}
                     for ok, claim, ev in checks.rows],
            "facts": facts,
        }
    except Exception as exc:
        verification = {"error": str(exc)}

    emp = empirical.load() or {}
    empirical_summary = {
        "sessions": emp.get("sessions"),
        "bars": emp.get("bars"),
        "start": emp.get("start"),
        "by_hour": [
            {"hour": int(h),
             "n": v["n"],
             "p01": v["quantiles"]["p01"] * 100,
             "p05": v["quantiles"]["p05"] * 100,
             "p50": v["quantiles"]["p50"] * 100,
             "p95": v["quantiles"]["p95"] * 100,
             "stdev": v["stdev"] * 100}
            for h, v in (emp.get("by_hour_et") or {}).items()
        ],
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verification": verification,
        "empirical": empirical_summary,
        "account_id": config.COMP_ACCOUNT_ID,
        "account": account,
        "ledger": ledger,
        "scan_totals": scan_totals,
        "counts": {
            "orders": len(intents), "fills": len(submitted),
            "settlements": len(settlements), "emergency_closes": len(emergencies),
            "vetoes": len([v for v in vetoes if v.get("action") != "proceed"]),
            "refusals": len(refusals), "journal_records": len(records),
        },
        "spread_story": spread_story,
        "chains": chains,
        "gates": gates,
        # Sorted returns, thinned. A percentile lookup does not need all 668
        # values per hour and the page should not carry them.
        "empirical_samples": (
            {h: [round(x, 5) for x in v[::4]] for h, v in (emp.get("samples") or {}).items()}
            if emp else {}
        ),
        "cost_curves": curves,
        "widening": widening,
        "decisions": decisions[:80],
        "feed_note": (
            "Options quotes come from Alpaca's indicative feed, not OPRA. "
            "Costs shown are the costs this account was actually charged on that "
            "feed; they are not a claim about the true OPRA market spread."
        ),
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = build()
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"  ledger: {payload['ledger']}")
    print(f"  counts: {payload['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
