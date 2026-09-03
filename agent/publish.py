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

from . import cli, config, journal, observe, settle

OUT = config.ROOT / "site" / "data.json"


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build(profile: str = config.PROFILE_COMP) -> dict:
    records = journal.read_all()

    intents = [r for r in records if r.get("kind") == "order_intent" and not r.get("dry_run")]
    submitted = [r for r in records if r.get("kind") == "order_submitted"]
    settlements = [r for r in records if r.get("kind") == "settlement"]
    emergencies = [r for r in records if r.get("kind") == "emergency_close"]
    vetoes = [r for r in records if r.get("kind") == "veto"]
    refusals = [r for r in records if r.get("kind") in ("no_trade", "sizing")
                and not r.get("approved", True)]
    scans = [r for r in records if r.get("kind") == "scan"]

    # ---- the ledger -------------------------------------------------------
    ledger = settle.report(profile)

    # ---- cost curve: the most recent observation per underlying ----------
    curves: dict[str, dict] = {}
    for r in records:
        if r.get("kind") != "observation":
            continue
        curves[r["underlying"]] = {
            "ts": r["ts"],
            "reference_level": r.get("reference_level"),
            "points": [
                {"m": p["moneyness_pct"], "hs": p["half_spread_pct"], "mid": p["mid"],
                 "strike": p["strike"]}
                for p in r.get("rows", [])
                if -5.0 <= p["moneyness_pct"] <= 1.0
            ],
        }

    # ---- widening through the session ------------------------------------
    widening = observe.widening_report()

    # ---- decisions, newest first -----------------------------------------
    decisions = []
    for r in records:
        k = r.get("kind")
        if k == "order_intent" and not r.get("dry_run"):
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
        elif k == "no_trade":
            decisions.append({"ts": r["ts"], "type": "refusal",
                              "what": "no trade", "detail": str(r.get("reason", ""))})
        elif k == "veto" and r.get("action") != "proceed":
            decisions.append({
                "ts": r["ts"], "type": "veto",
                "what": f"veto: {r.get('action')} x{r.get('size_multiplier')}",
                "detail": f"{r.get('reason','')} {r.get('events') or ''}",
            })
        elif k == "settlement":
            decisions.append({
                "ts": r["ts"], "type": "settle",
                "what": f"{r.get('underlying')} {r.get('spread')} settled",
                "detail": (
                    f"P&L ${_f(r.get('realized_pnl')):.2f} at {r.get('settlement_level')}; "
                    f"exit cost paid ${_f(r.get('exit_cost_paid')):.2f}, "
                    f"avoided ${_f(r.get('exit_cost_avoided')):.2f}"
                ),
            })
        elif k == "emergency_close":
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

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
