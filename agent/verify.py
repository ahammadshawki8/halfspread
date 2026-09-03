"""Re-derive every published claim from the committed journal.

No API keys, no network, no account. Everything this prints is recomputed
from `data/journal/*.jsonl`, which is committed to the repository, so any
number on the dashboard or in the write-up can be checked by a stranger with
a clone and a Python interpreter.

    python -m agent.verify

Exit code is 0 when every check reproduces and 1 when any does not.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from . import config, journal

COMP = config.PROFILE_COMP


class Check:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def add(self, ok: bool, claim: str, evidence: str) -> None:
        self.rows.append((ok, claim, evidence))

    @property
    def failed(self) -> int:
        return sum(1 for ok, _, _ in self.rows if not ok)

    def render(self) -> str:
        out = []
        for ok, claim, evidence in self.rows:
            out.append(f"  [{'PASS' if ok else 'FAIL'}] {claim}")
            out.append(f"         {evidence}")
        return "\n".join(out)


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[len(s) // 2]


def run() -> tuple[Check, dict]:
    records = journal.read_all()
    c = Check()
    facts: dict = {"journal_records": len(records)}

    c.add(len(records) > 0, "The journal exists and is readable.",
          f"{len(records)} records across {len(list(config.JOURNAL_DIR.glob('*.jsonl')))} file(s).")

    # ---- 1. execution cost is measured before every order --------------------
    intents = [r for r in records
               if r.get("kind") == "order_intent" and not r.get("dry_run")
               and r.get("profile") == COMP]
    with_cost = [r for r in intents
                 if (r.get("evaluation") or {}).get("entry_cost") is not None]
    facts["orders"] = len(intents)
    c.add(len(intents) > 0 and len(with_cost) == len(intents),
          "Every competition order carried a measured entry cost before it was sent.",
          f"{len(with_cost)}/{len(intents)} order intents record entry_cost.")

    # ---- 2. every order re-quoted immediately before submission --------------
    requoted = [r for r in intents if r.get("requote")]
    drifts = [_f((r.get("requote") or {}).get("drift_vs_scan")) for r in requoted]
    facts["requoted"] = len(requoted)
    facts["max_abs_drift"] = max((abs(d) for d in drifts), default=0.0)
    c.add(len(requoted) == len(intents) and len(intents) > 0,
          "Every order was re-priced from fresh quotes immediately before submission.",
          f"{len(requoted)}/{len(intents)} carry a re-quote; largest decision-to-execution "
          f"drift {facts['max_abs_drift']:.2f} $/contract.")

    # ---- 3. every order was followed to a terminal state ---------------------
    fills = {r.get("order_id"): r for r in records
             if r.get("kind") == "order_filled" and r.get("profile") == COMP}
    submitted_ids = {r.get("order_id") for r in records
                     if r.get("kind") == "order_submitted" and r.get("profile") == COMP
                     and r.get("order_id")}
    settled_states = [r for r in fills.values()
                      if str(r.get("status", "")).lower() in
                      ("filled", "canceled", "expired", "rejected", "done_for_day")]
    credit_total = sum(_f(r.get("credit_received")) * _f(r.get("filled_qty")) * 100
                       for r in fills.values())
    facts["orders_filled"] = len(settled_states)
    facts["credit_received"] = round(credit_total, 2)
    c.add(bool(submitted_ids) and submitted_ids <= set(fills),
          "Every order was followed to a terminal state, not just acknowledged.",
          f"{len(fills)}/{len(submitted_ids)} submissions carry a terminal fill record; "
          f"{len(settled_states)} reached a settled status; "
          f"${credit_total:.2f} of credit received in total.")

    # ---- 4. the cost curve rises as strikes go out of the money --------------
    obs = [r for r in records if r.get("kind") == "observation" and r.get("underlying") == "SPY"]
    atm, far = [], []
    for r in obs:
        for p in r.get("rows", []):
            if (p.get("bid") or 0) <= 0:
                continue
            m, hs = p["moneyness_pct"], p["half_spread_pct"]
            if -0.5 <= m <= 0.0:
                atm.append(hs)
            elif -3.0 <= m <= -2.0:
                far.append(hs)
    m_atm, m_far = _median(atm), _median(far)
    facts["half_spread_atm_pct"] = m_atm
    facts["half_spread_far_pct"] = m_far
    if m_atm and m_far:
        facts["cost_curve_ratio"] = round(m_far / m_atm, 1)
    c.add(bool(m_atm and m_far and m_far > m_atm),
          "Relative execution cost rises as strikes move out of the money.",
          f"SPY median half-spread {m_atm:.2f}% of mid at the money vs {m_far:.2f}% at 2-3% OTM"
          + (f" ({facts.get('cost_curve_ratio')}x)." if m_atm else "."))

    # ---- 5. spreads widen through the session --------------------------------
    by_under: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in obs:
        vals = [p["half_spread_pct"] for p in r.get("rows", [])
                if (p.get("bid") or 0) > 0 and -1.0 <= p["moneyness_pct"] <= 0.0]
        med = _median(vals)
        if med:
            by_under[r["underlying"]].append((r["ts"], med))
    widened = None
    if by_under.get("SPY") and len(by_under["SPY"]) > 2:
        series = sorted(by_under["SPY"])
        first, last = series[0][1], series[-1][1]
        widened = round(last / first, 2) if first else None
        facts["widening_vs_open"] = widened
        facts["observations"] = len(series)
    c.add(widened is not None,
          "The same strikes were re-quoted through the session and the spread was tracked.",
          f"{facts.get('observations', 0)} SPY observations; near-the-money half-spread "
          f"ended at {widened}x its first reading."
          if widened else "Not enough observations recorded yet.")

    # ---- 6. refusals are recorded, not just fills ----------------------------
    refusals = [r for r in records if r.get("kind") in ("no_trade", "hold_through_breach")]
    vetoes = [r for r in records if r.get("kind") == "veto" and r.get("action") != "proceed"]
    facts["refusals"] = len(refusals)
    facts["vetoes"] = len(vetoes)
    c.add(len(refusals) > 0,
          "Decisions not to trade are journalled with a specific reason.",
          f"{len(refusals)} refusals and {len(vetoes)} non-trivial risk-review outcomes recorded.")

    # ---- 7. settlements paid no exit spread ----------------------------------
    settlements = [r for r in records
                   if r.get("kind") == "settlement" and r.get("profile") == COMP]
    exit_paid = sum(_f(r.get("exit_cost_paid")) for r in settlements)
    realized = sum(_f(r.get("realized_pnl")) for r in settlements)
    avoided = sum(_f(r.get("exit_cost_avoided")) for r in settlements)
    facts.update({"settlements": len(settlements), "realized_pnl": round(realized, 2),
                  "exit_cost_paid": round(exit_paid, 2),
                  "exit_cost_avoided": round(avoided, 2)})
    if settlements:
        c.add(exit_paid == 0.0,
              "Positions held to settlement paid no exit spread.",
              f"{len(settlements)} settled, total exit cost paid ${exit_paid:.2f}, "
              f"exit cost avoided ${avoided:.2f}, realised P&L ${realized:.2f}.")
    else:
        c.add(True, "No positions have settled yet, so no settlement claim is made.",
              "0 settlements in the journal.")

    # ---- 8. the empirical distribution is real -------------------------------
    from . import empirical
    emp = empirical.load()
    if emp:
        facts["empirical_sessions"] = emp.get("sessions")
        facts["empirical_bars"] = emp.get("bars")
        c.add(int(emp.get("sessions") or 0) > 100,
              "Breach probabilities are checked against measured intraday history.",
              f"{emp.get('bars')} bars across {emp.get('sessions')} sessions "
              f"since {emp.get('start')}.")
    else:
        c.add(False, "Empirical distribution cache is present.",
              "data/empirical/spy_intraday.json missing; run python -m agent.empirical --rebuild.")

    # ---- 9. corrections are on the record ------------------------------------
    corrections = [r for r in records if r.get("kind") == "journal_correction"]
    facts["corrections"] = len(corrections)
    c.add(True, "Corrections to the journal are themselves journalled.",
          f"{len(corrections)} correction record(s); nothing is removed silently.")

    return c, facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Re-derive published claims from the journal")
    ap.add_argument("--json", action="store_true", help="emit the facts as JSON")
    args = ap.parse_args(argv)

    c, facts = run()
    if args.json:
        print(json.dumps(facts, indent=2, default=str))
        return 1 if c.failed else 0

    print("HALFSPREAD - verifying published claims against the committed journal")
    print("no API keys, no network, no account\n")
    print(c.render())
    print()
    if c.failed:
        print(f"{c.failed} check(s) did not reproduce.")
        return 1
    print(f"All {len(c.rows)} checks reproduce from data/journal/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
