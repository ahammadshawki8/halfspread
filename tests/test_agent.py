"""Tests for the load-bearing arithmetic.

Standard library only.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import condor, config, cost, execute, llm, pricing, risk  # noqa: E402
from agent.chain import Contract, parse_occ  # noqa: E402


def contract(symbol, strike, bid, ask, kind="put", expiry="2026-09-04"):
    return Contract(symbol=symbol, root="SPY", strike=strike, expiry=expiry, kind=kind,
                    bid=bid, ask=ask, bid_size=10, ask_size=10, quote_ts="")


class TestPricing(unittest.TestCase):
    def test_put_call_parity(self):
        S, K, T, r, sig = 100.0, 100.0, 0.25, 0.04, 0.2
        call = pricing.bs_price(S, K, T, r, sig, "call")
        put = pricing.bs_price(S, K, T, r, sig, "put")
        # C - P = S - K e^{-rT}
        self.assertAlmostEqual(call - put, S - K * math.exp(-r * T), places=8)

    def test_implied_vol_round_trip(self):
        S, K, T, r = 765.0, 760.0, 0.02, 0.042
        for sig in (0.08, 0.15, 0.35, 0.90):
            px = pricing.bs_price(S, K, T, r, sig, "put")
            back = pricing.implied_vol(px, S, K, T, r, "put")
            self.assertIsNotNone(back, f"failed to solve at sigma={sig}")
            self.assertAlmostEqual(back, sig, places=4)

    def test_implied_vol_rejects_arbitrage(self):
        S, K, T, r = 765.0, 760.0, 0.02, 0.042
        # Below intrinsic and above the strike bound are both unsolvable.
        self.assertIsNone(pricing.implied_vol(-1.0, S, K, T, r, "put"))
        self.assertIsNone(pricing.implied_vol(K * 10, S, K, T, r, "put"))

    def test_put_delta_sign_and_bounds(self):
        g = pricing.greeks(765.0, 760.0, 0.02, 0.042, 0.2, "put")
        self.assertLess(g.delta, 0.0)
        self.assertGreater(g.delta, -1.0)
        self.assertGreater(g.gamma, 0.0)

    def test_further_otm_has_smaller_breach_probability(self):
        args = (765.0, 0.02, 0.042, 0.2, "put")
        near = pricing.prob_itm(args[0], 763.0, *args[1:])
        far = pricing.prob_itm(args[0], 750.0, *args[1:])
        self.assertGreater(near, far)


class TestOCC(unittest.TestCase):
    def test_parses_symbol(self):
        self.assertEqual(parse_occ("SPY260903P00758000"),
                         ("SPY", 758.0, "2026-09-03", "put"))
        self.assertEqual(parse_occ("SPXW260903C07600000"),
                         ("SPXW", 7600.0, "2026-09-03", "call"))

    def test_rejects_nonsense(self):
        self.assertIsNone(parse_occ("not-an-occ-symbol"))


class TestSpreadArithmetic(unittest.TestCase):
    def setUp(self):
        self.short = contract("SPY260904P00760000", 760, 0.40, 0.50)
        self.long = contract("SPY260904P00757000", 757, 0.10, 0.20)
        self.spread = cost.PutCreditSpread("SPY", "2026-09-04", self.short, self.long)

    def test_credit_at_mid_beats_credit_actually_fillable(self):
        # mid: 0.45 - 0.15 = 0.30 ; fill: bid 0.40 - ask 0.20 = 0.20
        self.assertAlmostEqual(self.spread.credit_mid, 0.30, places=6)
        self.assertAlmostEqual(self.spread.credit_fill, 0.20, places=6)
        self.assertGreater(self.spread.credit_mid, self.spread.credit_fill)

    def test_entry_cost_is_the_two_half_spreads(self):
        expected = self.short.half_spread + self.long.half_spread
        self.assertAlmostEqual(self.spread.entry_cost, expected, places=6)

    def test_max_loss_uses_the_fillable_credit_not_mid(self):
        # (width - credit_fill) * 100 = (3 - 0.20) * 100
        self.assertAlmostEqual(self.spread.max_loss, 280.0, places=6)

    def test_half_spread_pct_is_relative_to_mid(self):
        c = contract("X", 1, 0.10, 0.30)
        self.assertAlmostEqual(c.mid, 0.20, places=6)
        self.assertAlmostEqual(c.half_spread_pct, 0.5, places=6)

    def test_zero_bid_contract_is_not_tradeable_as_a_short(self):
        self.assertFalse(contract("X", 1, 0.0, 0.0).tradeable)


class TestCondorArithmetic(unittest.TestCase):
    def setUp(self):
        self.ic = condor.IronCondor(
            "SPY", "2026-09-04",
            put_long=contract("P755", 755, 0.05, 0.10),
            put_short=contract("P758", 758, 0.20, 0.25),
            call_short=contract("C772", 772, 0.20, 0.25, "call"),
            call_long=contract("C775", 775, 0.05, 0.10, "call"),
        )

    def test_collects_both_credits(self):
        # each side: bid 0.20 - ask 0.10 = 0.10
        self.assertAlmostEqual(self.ic.credit_fill, 0.20, places=6)

    def test_max_loss_is_the_wider_wing_only(self):
        # Only one side can finish ITM, so risk is one 3-wide wing, not both.
        self.assertAlmostEqual(self.ic.width, 3.0, places=6)
        self.assertAlmostEqual(self.ic.max_loss, (3.0 - 0.20) * 100, places=6)

    def test_better_paid_per_dollar_of_risk_than_one_vertical(self):
        vertical = cost.PutCreditSpread(
            "SPY", "2026-09-04",
            contract("P758", 758, 0.20, 0.25), contract("P755", 755, 0.05, 0.10))
        self.assertAlmostEqual(self.ic.width, vertical.width, places=6)
        self.assertGreater(self.ic.credit_fill, vertical.credit_fill)

    def test_rejects_crossed_strikes(self):
        bad = condor.IronCondor(
            "SPY", "2026-09-04",
            put_long=contract("P780", 780, 0.05, 0.10),
            put_short=contract("P758", 758, 0.20, 0.25),
            call_short=contract("C772", 772, 0.20, 0.25, "call"),
            call_long=contract("C775", 775, 0.05, 0.10, "call"))
        self.assertFalse(bad.valid)


class TestExecutionPayload(unittest.TestCase):
    """The bug that bit us live: Alpaca signs the mleg limit from the
    package's point of view. A POSITIVE limit is a maximum net DEBIT, so a
    credit spread sent positive behaves as a market order."""

    def _evaluation(self, **over):
        base = dict(
            underlying="SPY", expiry="2026-09-04", short_strike=760.0, long_strike=757.0,
            short_symbol="SPY260904P00760000", long_symbol="SPY260904P00757000",
            width=3.0, credit_mid=0.30, credit_fill=0.20, entry_cost=10.0,
            entry_cost_pct_of_credit=33.3, exit_cost_if_closed=10.0, round_trip_cost=20.0,
            max_profit=20.0, max_loss=280.0, prob_short_itm=0.1, prob_max_profit=0.9,
            expected_payoff=5.0, net_ev=5.0, net_ev_mid_naive=15.0,
            net_ev_if_round_tripped=-5.0, return_on_risk=0.018, iv_short=0.2,
            iv_long=0.22, sigma_used=0.18, delta_short=-0.15, moneyness_pct=-0.6,
            exit_cost_projected=40.0, net_ev_if_round_tripped_projected=-35.0,
            admissible=True, reject_reason=None)
        base.update(over)
        return cost.Evaluation(**base)

    def test_credit_spread_limit_is_negative(self):
        payload = execute.build_payload(self._evaluation(), 3)
        self.assertEqual(payload["limit_price"], "-0.20")
        self.assertEqual(payload["qty"], "3")
        self.assertEqual(payload["order_class"], "mleg")

    def test_positive_credit_input_still_emits_a_negative_limit(self):
        payload = execute.build_payload(self._evaluation(), 1, limit_price=0.45)
        self.assertEqual(payload["limit_price"], "-0.45")

    def test_vertical_has_two_covered_legs(self):
        legs = execute.build_payload(self._evaluation(), 1)["legs"]
        self.assertEqual(len(legs), 2)
        self.assertEqual({l["side"] for l in legs}, {"buy", "sell"})
        self.assertTrue(all(l["ratio_qty"] == "1" for l in legs))

    def test_condor_emits_all_four_legs(self):
        ev = self._evaluation(structure="iron_condor", legs=(
            {"symbol": "P755", "side": "buy", "position_intent": "buy_to_open"},
            {"symbol": "P758", "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": "C772", "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": "C775", "side": "buy", "position_intent": "buy_to_open"},
        ))
        legs = execute.build_payload(ev, 1)["legs"]
        self.assertEqual(len(legs), 4)
        self.assertEqual(sum(1 for l in legs if l["side"] == "sell"), 2)

    def test_rejects_non_positive_credit(self):
        with self.assertRaises(ValueError):
            execute.build_payload(self._evaluation(credit_fill=0.0), 1)

    def test_comp_requires_an_arming_token(self):
        with self.assertRaises(execute.ExecutionRefused):
            execute.submit(self._evaluation(), 1, profile=config.PROFILE_COMP, dry_run=True)


class TestVetoClamp(unittest.TestCase):
    """The model can shrink a position and nothing else. Enforced in code."""

    def test_cannot_enlarge(self):
        for raw in ({"action": "proceed", "size_multiplier": 5.0},
                    {"action": "increase", "size_multiplier": 2.0},
                    {"action": "proceed", "size_multiplier": 99}):
            self.assertLessEqual(llm._coerce(raw, "t").size_multiplier, 1.0)

    def test_block_becomes_the_floor_not_zero(self):
        d = llm._coerce({"action": "block", "size_multiplier": 0.0}, "t")
        self.assertEqual(d.size_multiplier, llm.VETO_FLOOR)
        self.assertFalse(d.blocks)
        self.assertIn("converted", d.reason)

    def test_reduction_below_the_floor_is_lifted_to_it(self):
        self.assertEqual(llm._coerce({"action": "reduce", "size_multiplier": 0.01}, "t")
                         .size_multiplier, llm.VETO_FLOOR)

    def test_garbage_is_a_no_op(self):
        d = llm._coerce({"nonsense": True}, "t")
        self.assertEqual((d.action, d.size_multiplier), ("proceed", 1.0))

    def test_unreachable_model_leaves_the_decision_alone(self):
        d = llm.event_risk_veto("ctx", enabled=False)
        self.assertEqual(d.size_multiplier, 1.0)
        self.assertFalse(d.blocks)


class TestRiskSizing(unittest.TestCase):
    def _ev(self, max_loss=280.0, net_ev=5.0, admissible=True, reason=None):
        return cost.Evaluation(
            underlying="SPY", expiry="2026-09-04", short_strike=760.0, long_strike=757.0,
            short_symbol="A", long_symbol="B", width=3.0, credit_mid=0.30, credit_fill=0.20,
            entry_cost=10.0, entry_cost_pct_of_credit=33.3, exit_cost_if_closed=10.0,
            round_trip_cost=20.0, max_profit=20.0, max_loss=max_loss, prob_short_itm=0.1,
            prob_max_profit=0.9, expected_payoff=net_ev, net_ev=net_ev,
            net_ev_mid_naive=15.0, net_ev_if_round_tripped=-5.0, return_on_risk=0.018,
            iv_short=0.2, iv_long=0.22, sigma_used=0.18, delta_short=-0.15,
            moneyness_pct=-0.6, exit_cost_projected=40.0,
            net_ev_if_round_tripped_projected=-35.0, admissible=admissible,
            reject_reason=reason)

    def test_total_risk_never_exceeds_the_per_position_cap(self):
        d = risk.size(self._ev(), positions=[], journal_records=[])
        self.assertTrue(d.approved)
        self.assertLessEqual(d.max_loss_total, config.MAX_LOSS_PER_POSITION)

    def test_refuses_an_inadmissible_candidate(self):
        d = risk.size(self._ev(admissible=False, reason="test"), [], [])
        self.assertFalse(d.approved)
        self.assertEqual(d.qty, 0)

    def test_refuses_when_net_ev_is_below_the_floor(self):
        self.assertFalse(risk.size(self._ev(net_ev=-1.0), [], []).approved)

    def test_refuses_a_position_larger_than_the_cap(self):
        d = risk.size(self._ev(max_loss=config.MAX_LOSS_PER_POSITION + 1), [], [])
        self.assertFalse(d.approved)

    def test_refuses_once_the_concurrency_cap_is_reached(self):
        legs = [{"asset_class": "us_option", "qty": "1", "avg_entry_price": "0.1"}
                for _ in range(config.MAX_CONCURRENT_POSITIONS * 2)]
        self.assertFalse(risk.size(self._ev(), legs, []).approved)

    def test_daily_realised_loss_reduces_the_budget(self):
        spent = [{"kind": "settlement", "realized_pnl": -config.MAX_LOSS_PER_DAY}]
        self.assertFalse(risk.size(self._ev(), [], spent).approved)

    def test_pin_risk_reports_signed_distance(self):
        breached, dist = risk.pin_risk(765.0, 768.0, 0.25)
        self.assertFalse(breached)
        self.assertGreater(dist, 0)
        breached, dist = risk.pin_risk(765.0, 764.0, 0.25)
        self.assertTrue(breached)
        self.assertLess(dist, 0)


class TestExpectedPayoff(unittest.TestCase):
    def test_deep_otm_put_is_worth_almost_nothing(self):
        v = cost._expected_put_payoff(700.0, 765.0, 0.02, 0.15)
        self.assertLess(v, 0.05)

    def test_deep_itm_put_approaches_intrinsic(self):
        v = cost._expected_put_payoff(900.0, 765.0, 0.001, 0.15)
        self.assertAlmostEqual(v, 900.0 - 765.0, delta=1.0)

    def test_call_payoff_mirrors_put_through_parity(self):
        F, K, T, sig = 765.0, 760.0, 0.05, 0.2
        c = condor.expected_call_payoff(K, F, T, sig)
        p = cost._expected_put_payoff(K, F, T, sig)
        self.assertAlmostEqual(c - p, F - K, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestAccountIsolation(unittest.TestCase):
    """Nothing measured on one account may affect the other. Every one of these
    was a real leak at some point: the ledger, the monitor and the risk budget
    all read a shared journal."""

    def setUp(self):
        from agent import risk as _risk
        self.risk = _risk
        self.records = [
            {"kind": "settlement", "profile": "dev", "realized_pnl": -900.0},
            {"kind": "settlement", "profile": "comp", "realized_pnl": -100.0},
            {"kind": "settlement", "profile": "comp", "realized_pnl": 50.0},
        ]

    def test_dev_losses_do_not_consume_the_comp_budget(self):
        self.assertEqual(self.risk.realized_loss_today(self.records, "comp"), 100.0)

    def test_comp_losses_do_not_consume_the_dev_budget(self):
        self.assertEqual(self.risk.realized_loss_today(self.records, "dev"), 900.0)

    def test_unscoped_still_sums_everything(self):
        self.assertEqual(self.risk.realized_loss_today(self.records), 1000.0)

    def test_gains_never_count_as_loss(self):
        only_wins = [{"kind": "settlement", "profile": "comp", "realized_pnl": 500.0}]
        self.assertEqual(self.risk.realized_loss_today(only_wins, "comp"), 0.0)

    def test_a_days_losses_can_stop_the_account_trading(self):
        from agent import config
        spent = [{"kind": "settlement", "profile": "comp",
                  "realized_pnl": -config.MAX_LOSS_PER_DAY}]
        ev = TestRiskSizing._ev(TestRiskSizing())
        self.assertFalse(self.risk.size(ev, [], spent, profile="comp").approved)
        # ...but only its own.
        self.assertTrue(self.risk.size(ev, [], spent, profile="dev").approved)


class TestRefusalDefinition(unittest.TestCase):
    """The verifier, the dashboard and the README each counted refusals
    differently and reported three numbers for one journal."""

    def test_every_kind_of_refusal_is_counted_once(self):
        from agent import verify
        records = [
            {"kind": "no_trade"},
            {"kind": "hold_through_breach"},
            {"kind": "order_abandoned"},
            {"kind": "sizing", "approved": False},
            {"kind": "sizing", "approved": True},     # not a refusal
            {"kind": "order_submitted"},              # not a refusal
        ]
        self.assertEqual(len(verify.count_refusals(records)), 4)
