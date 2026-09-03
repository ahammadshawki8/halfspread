"""Iron condor: a put credit spread below the market and a call credit spread
above it, in one four-leg package.

Only one side can finish in the money, so the package collects two credits
against a max loss set by the wider wing alone. For the same dollar of risk it
is better paid than a single vertical, which matters here: the measured
credit-to-width on one-sided spreads runs 5-9%, leaving almost nothing above
execution cost once the bid-ask is charged properly.

Condors are scored onto the same `Evaluation` shape the verticals use so the
two structures compete on a single ranking rather than being chosen by
preference.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import config, empirical, pricing
from .chain import Contract
from .cost import CONTRACT_MULTIPLIER, Evaluation, _expected_put_payoff


def expected_call_payoff(K: float, F: float, T: float, sigma: float) -> float:
    """E[max(S_T - K, 0)] under a lognormal terminal distribution with mean F."""
    T = max(T, config.MIN_T_YEARS)
    if sigma <= 1e-9 or F <= 0 or K <= 0:
        return max(F - K, 0.0)
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    return F * pricing._norm_cdf(d1) - K * pricing._norm_cdf(d2)


@dataclass(frozen=True)
class IronCondor:
    underlying: str
    expiry: str
    put_long: Contract     # lowest strike
    put_short: Contract
    call_short: Contract
    call_long: Contract    # highest strike

    @property
    def put_width(self) -> float:
        return self.put_short.strike - self.put_long.strike

    @property
    def call_width(self) -> float:
        return self.call_long.strike - self.call_short.strike

    @property
    def width(self) -> float:
        return max(self.put_width, self.call_width)

    @property
    def credit_mid(self) -> float:
        return ((self.put_short.mid - self.put_long.mid)
                + (self.call_short.mid - self.call_long.mid))

    @property
    def credit_fill(self) -> float:
        """Sell both shorts at the bid, buy both longs at the ask."""
        return ((self.put_short.bid - self.put_long.ask)
                + (self.call_short.bid - self.call_long.ask))

    @property
    def entry_cost(self) -> float:
        return self.credit_mid - self.credit_fill

    @property
    def exit_cost_if_closed(self) -> float:
        return (
            (self.put_short.ask - self.put_short.mid)
            + (self.put_long.mid - self.put_long.bid)
            + (self.call_short.ask - self.call_short.mid)
            + (self.call_long.mid - self.call_long.bid)
        )

    @property
    def max_profit(self) -> float:
        return self.credit_fill * CONTRACT_MULTIPLIER

    @property
    def max_loss(self) -> float:
        """Only one wing can finish in the money, so the wider wing sets it."""
        return (self.width - self.credit_fill) * CONTRACT_MULTIPLIER

    @property
    def all_legs(self) -> list[Contract]:
        return [self.put_long, self.put_short, self.call_short, self.call_long]

    @property
    def valid(self) -> bool:
        return (
            all(c.tradeable for c in self.all_legs)
            and self.put_long.strike < self.put_short.strike
            < self.call_short.strike < self.call_long.strike
            and self.credit_fill > 0
            and self.credit_fill < self.width
        )


def evaluate(
    ic: IronCondor,
    spot_equiv: float,
    T: float,
    vrp_haircut: float = config.VRP_HAIRCUT,
) -> Evaluation | None:
    if not ic.valid:
        return None

    r = config.RISK_FREE_RATE
    forward = spot_equiv * math.exp(r * T)

    iv_p = pricing.implied_vol(ic.put_short.mid, spot_equiv, ic.put_short.strike, T, r, "put")
    iv_c = pricing.implied_vol(ic.call_short.mid, spot_equiv, ic.call_short.strike, T, r, "call")
    if iv_p is None or iv_c is None:
        return None

    sig_p = iv_p * (1.0 - vrp_haircut)
    sig_c = iv_c * (1.0 - vrp_haircut)

    put_leg = (_expected_put_payoff(ic.put_short.strike, forward, T, sig_p)
               - _expected_put_payoff(ic.put_long.strike, forward, T, sig_p))
    call_leg = (expected_call_payoff(ic.call_short.strike, forward, T, sig_c)
                - expected_call_payoff(ic.call_long.strike, forward, T, sig_c))
    expected_terminal_loss = (put_leg + call_leg) * CONTRACT_MULTIPLIER

    expected_payoff = ic.credit_fill * CONTRACT_MULTIPLIER - expected_terminal_loss
    entry_cost_dollars = ic.entry_cost * CONTRACT_MULTIPLIER
    exit_cost_dollars = ic.exit_cost_if_closed * CONTRACT_MULTIPLIER
    widening = config.EXIT_WIDENING_MEASURED.get(ic.underlying, config.EXIT_WIDENING_DEFAULT)

    m_put = pricing.prob_itm(spot_equiv, ic.put_short.strike, T, r, sig_p, "put")
    m_call = pricing.prob_itm(spot_equiv, ic.call_short.strike, T, r, sig_c, "call")
    b_put = empirical.conservative_breach(m_put, spot_equiv, ic.put_short.strike, "put")
    b_call = empirical.conservative_breach(m_call, spot_equiv, ic.call_short.strike, "call")
    p_breach = min(1.0, b_put["prob"] + b_call["prob"])
    g = pricing.greeks(spot_equiv, ic.put_short.strike, T, r, iv_p, "put")

    reject = _reject_reason(ic, spot_equiv, 1.0 - p_breach)

    return Evaluation(
        underlying=ic.underlying,
        expiry=ic.expiry,
        short_strike=ic.put_short.strike,
        long_strike=ic.call_short.strike,
        short_symbol=ic.put_short.symbol,
        long_symbol=ic.call_short.symbol,
        width=ic.width,
        credit_mid=round(ic.credit_mid, 4),
        credit_fill=round(ic.credit_fill, 4),
        entry_cost=round(entry_cost_dollars, 2),
        entry_cost_pct_of_credit=round(
            entry_cost_dollars / (ic.credit_mid * CONTRACT_MULTIPLIER) * 100, 2
        ) if ic.credit_mid > 0 else float("inf"),
        exit_cost_if_closed=round(exit_cost_dollars, 2),
        round_trip_cost=round(entry_cost_dollars + exit_cost_dollars, 2),
        max_profit=round(ic.max_profit, 2),
        max_loss=round(ic.max_loss, 2),
        prob_short_itm=round(p_breach, 4),
        prob_max_profit=round(1.0 - p_breach, 4),
        expected_payoff=round(expected_payoff, 2),
        net_ev=round(expected_payoff, 2),
        net_ev_mid_naive=round(ic.credit_mid * CONTRACT_MULTIPLIER - expected_terminal_loss, 2),
        net_ev_if_round_tripped=round(expected_payoff - exit_cost_dollars, 2),
        return_on_risk=round(expected_payoff / ic.max_loss, 4) if ic.max_loss > 0 else 0.0,
        iv_short=round(iv_p, 4),
        iv_long=round(iv_c, 4),
        sigma_used=round((sig_p + sig_c) / 2, 4),
        delta_short=round(g.delta, 4),
        moneyness_pct=round((ic.put_short.strike - spot_equiv) / spot_equiv * 100, 3),
        exit_cost_projected=round(exit_cost_dollars * widening, 2),
        net_ev_if_round_tripped_projected=round(expected_payoff - exit_cost_dollars * widening, 2),
        admissible=reject is None,
        reject_reason=reject,
        prob_source=("empirical" if "empirical" in (b_put["source"], b_call["source"])
                     else "model"),
        prob_model=round(min(1.0, m_put + m_call), 4),
        prob_empirical=(round(min(1.0, (b_put["empirical"] or 0) + (b_call["empirical"] or 0)), 4)
                        if b_put["empirical"] is not None else None),
        empirical_samples=max(b_put["samples"], b_call["samples"]),
        structure="iron_condor",
        legs=(
            {"symbol": ic.put_long.symbol, "side": "buy", "position_intent": "buy_to_open"},
            {"symbol": ic.put_short.symbol, "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": ic.call_short.symbol, "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": ic.call_long.symbol, "side": "buy", "position_intent": "buy_to_open"},
        ),
    )


def _reject_reason(ic: IronCondor, spot: float, prob_win: float) -> str | None:
    if not (ic.put_short.strike < spot < ic.call_short.strike):
        return f"spot {spot:.2f} is not between the short strikes"
    if prob_win < config.MIN_PROB_WIN:
        return f"P(win) {prob_win:.3f} < {config.MIN_PROB_WIN}"
    ratio = ic.credit_fill / ic.width if ic.width else 0.0
    if ratio < config.MIN_CREDIT_TO_WIDTH:
        return f"credit/width {ratio:.3f} < {config.MIN_CREDIT_TO_WIDTH}"
    if ratio > config.MAX_CREDIT_TO_WIDTH:
        return f"credit/width {ratio:.3f} > {config.MAX_CREDIT_TO_WIDTH}"
    if ic.credit_fill < config.MIN_CREDIT_FILL:
        return f"credit {ic.credit_fill:.3f} < {config.MIN_CREDIT_FILL}"
    if ic.max_loss < config.MIN_MAX_LOSS:
        return f"max loss ${ic.max_loss:.0f} < ${config.MIN_MAX_LOSS:.0f}"
    if ic.max_loss > config.MAX_LOSS_PER_POSITION:
        return f"max loss ${ic.max_loss:.0f} > cap ${config.MAX_LOSS_PER_POSITION:.0f}"
    return None


def _nearest(by_strike: dict[float, Contract], target: float) -> float | None:
    if not by_strike:
        return None
    return min(by_strike.keys(), key=lambda k: abs(k - target))


def build_candidates(
    puts: list[Contract],
    calls: list[Contract],
    underlying: str,
    expiry: str,
    spot: float,
    widths: list[float],
) -> list[IronCondor]:
    """Symmetric condors straddling spot at a range of short-strike offsets."""
    puts_by = {c.strike: c for c in puts if c.tradeable}
    calls_by = {c.strike: c for c in calls if c.tradeable}

    # Offsets are a percentage of spot, not a fixed number of points, so the
    # same search works on SPY at ~769 and SPXW at ~7700. Point offsets put the
    # short strikes far too close: 1-2 points on a 769 underlying is 0.13-0.26%
    # out of the money, which prices at P(win) around 0.30 with hours to run.
    # Reaching P(win) 0.85 needs roughly 1.4 sigma a side, and at ~15% implied
    # over a 6-hour session that is about 1.2% of spot.
    seen: set[tuple] = set()
    out: list[IronCondor] = []
    for pct in (0.004, 0.006, 0.008, 0.010, 0.012, 0.015, 0.020, 0.025):
        offset = spot * pct
        ps = _nearest(puts_by, spot - offset)
        cs = _nearest(calls_by, spot + offset)
        if ps is None or cs is None or not (ps < spot < cs):
            continue
        for w in widths:
            pl = puts_by.get(ps - w)
            cl = calls_by.get(cs + w)
            if pl is None or cl is None:
                continue
            key = (pl.strike, ps, cs, cl.strike)
            if key in seen:
                continue
            seen.add(key)
            ic = IronCondor(underlying, expiry, pl, puts_by[ps], calls_by[cs], cl)
            if ic.valid:
                out.append(ic)
    return out
