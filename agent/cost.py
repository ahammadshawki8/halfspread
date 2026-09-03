"""Execution cost measurement and net expected value.

This module is the thesis. Nothing reaches the broker without a measured
entry cost and a net-EV number attached, and every candidate also carries
the exit cost it would incur if it were closed rather than settled - the
cost this agent exists to avoid.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from . import config, empirical, pricing
from .chain import Contract

CONTRACT_MULTIPLIER = 100.0


@dataclass(frozen=True)
class PutCreditSpread:
    """Sell the higher strike, buy the lower. Defined risk, both legs covered
    within one order, so it satisfies Alpaca's mleg coverage rule."""
    underlying: str
    expiry: str
    short: Contract
    long: Contract

    @property
    def width(self) -> float:
        return self.short.strike - self.long.strike

    @property
    def credit_mid(self) -> float:
        """Credit if both legs filled at mid. The number most agents quote."""
        return self.short.mid - self.long.mid

    @property
    def credit_fill(self) -> float:
        """Credit actually achievable: sell the short leg at the bid, buy the
        long leg at the ask. This is what the broker will really give us."""
        return self.short.bid - self.long.ask

    @property
    def entry_cost(self) -> float:
        """Option points surrendered to the bid-ask on the way in."""
        return self.credit_mid - self.credit_fill

    @property
    def exit_cost_if_closed(self) -> float:
        """What closing would cost at current quotes: buy back the short at
        the ask, sell the long at the bid. Symmetric to entry, and it grows
        as far-OTM liquidity evaporates into the close."""
        return (self.short.ask - self.short.mid) + (self.long.mid - self.long.bid)

    @property
    def max_profit(self) -> float:
        return self.credit_fill * CONTRACT_MULTIPLIER

    @property
    def max_loss(self) -> float:
        return (self.width - self.credit_fill) * CONTRACT_MULTIPLIER

    @property
    def valid(self) -> bool:
        return (
            self.short.tradeable
            and self.long.tradeable
            and self.width > 0
            and self.credit_fill > 0
            and self.credit_fill < self.width
        )


@dataclass(frozen=True)
class Evaluation:
    underlying: str
    expiry: str
    short_strike: float
    long_strike: float
    short_symbol: str
    long_symbol: str
    width: float

    credit_mid: float
    credit_fill: float
    entry_cost: float
    entry_cost_pct_of_credit: float
    exit_cost_if_closed: float
    round_trip_cost: float

    max_profit: float
    max_loss: float
    prob_short_itm: float
    prob_max_profit: float

    expected_payoff: float      # dollars, before entry cost
    net_ev: float               # dollars, after entry cost
    net_ev_mid_naive: float     # what it looks like if you ignore the spread
    net_ev_if_round_tripped: float
    return_on_risk: float       # net_ev / max_loss

    iv_short: float | None
    iv_long: float | None
    sigma_used: float
    delta_short: float
    moneyness_pct: float

    exit_cost_projected: float   # what closing LATER is modelled to cost
    net_ev_if_round_tripped_projected: float
    admissible: bool
    reject_reason: str | None

    # Verticals and condors compete on one ranking, so both fill this shape.
    # For a condor `short_strike`/`long_strike` are the two SHORT strikes and
    # `legs` carries the full four-leg package.
    structure: str = "put_credit_spread"
    legs: tuple = ()

    # Which probability the sizing actually used. Black-Scholes assumes
    # lognormal returns; measured sessions are not, so the agent takes the
    # worse of the two and records which one bound.
    prob_source: str = "model"
    prob_model: float = 0.0
    prob_empirical: float | None = None
    empirical_samples: int = 0


def _expected_put_payoff(K: float, F: float, T: float, sigma: float) -> float:
    """E[max(K - S_T, 0)] under a lognormal terminal distribution with mean F.
    Undiscounted, because we want the expected cash payoff at expiry."""
    T = max(T, config.MIN_T_YEARS)
    if sigma <= 1e-9 or F <= 0 or K <= 0:
        return max(K - F, 0.0)
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    return K * pricing._norm_cdf(-d2) - F * pricing._norm_cdf(-d1)


def evaluate(
    spread: PutCreditSpread,
    spot_equiv: float,
    T: float,
    vrp_haircut: float = config.VRP_HAIRCUT,
) -> Evaluation | None:
    """Score a candidate.

    The edge claimed is the variance risk premium and nothing else: we assume
    the distribution that actually realises is a haircut of the one the market
    is charging for. Under the market's own implied vol the risk-neutral EV of
    any spread is zero by construction, so pricing at implied would make every
    candidate score exactly minus its transaction cost.
    """
    if not spread.valid:
        return None

    r = config.RISK_FREE_RATE
    forward = spot_equiv * math.exp(r * T)

    iv_s = pricing.implied_vol(spread.short.mid, spot_equiv, spread.short.strike, T, r, "put")
    iv_l = pricing.implied_vol(spread.long.mid, spot_equiv, spread.long.strike, T, r, "put")
    if iv_s is None:
        return None

    sigma_used = iv_s * (1.0 - vrp_haircut)

    e_short = _expected_put_payoff(spread.short.strike, forward, T, sigma_used)
    e_long = _expected_put_payoff(spread.long.strike, forward, T, sigma_used)
    expected_terminal_loss = (e_short - e_long) * CONTRACT_MULTIPLIER

    expected_payoff = spread.credit_fill * CONTRACT_MULTIPLIER - expected_terminal_loss
    entry_cost_dollars = spread.entry_cost * CONTRACT_MULTIPLIER
    exit_cost_dollars = spread.exit_cost_if_closed * CONTRACT_MULTIPLIER
    widening = config.EXIT_WIDENING_MEASURED.get(
        spread.underlying, config.EXIT_WIDENING_DEFAULT
    )
    exit_cost_projected = exit_cost_dollars * widening

    # credit_fill already has the entry cost baked in, so expected_payoff is
    # the net figure. The naive comparison prices the same trade at mid.
    net_ev = expected_payoff
    net_ev_mid_naive = spread.credit_mid * CONTRACT_MULTIPLIER - expected_terminal_loss

    model_itm = pricing.prob_itm(spot_equiv, spread.short.strike, T, r, sigma_used, "put")
    # Black-Scholes assumes lognormal returns; measured SPY sessions are not.
    # Take the worse of the diffusion and 668 sessions of actual intraday moves,
    # so a fat tail the model does not know about still costs us size.
    breach = empirical.conservative_breach(model_itm, spot_equiv, spread.short.strike, "put")
    prob_itm = breach["prob"]
    prob_win = 1.0 - prob_itm
    g = pricing.greeks(spot_equiv, spread.short.strike, T, r, iv_s, "put")

    reject = _reject_reason(spread, spot_equiv, prob_win)

    return Evaluation(
        underlying=spread.underlying,
        expiry=spread.expiry,
        short_strike=spread.short.strike,
        long_strike=spread.long.strike,
        short_symbol=spread.short.symbol,
        long_symbol=spread.long.symbol,
        width=spread.width,
        credit_mid=round(spread.credit_mid, 4),
        credit_fill=round(spread.credit_fill, 4),
        entry_cost=round(entry_cost_dollars, 2),
        entry_cost_pct_of_credit=round(
            entry_cost_dollars / (spread.credit_mid * CONTRACT_MULTIPLIER) * 100, 2
        ) if spread.credit_mid > 0 else float("inf"),
        exit_cost_if_closed=round(exit_cost_dollars, 2),
        round_trip_cost=round(entry_cost_dollars + exit_cost_dollars, 2),
        max_profit=round(spread.max_profit, 2),
        max_loss=round(spread.max_loss, 2),
        prob_short_itm=round(prob_itm, 4),
        prob_max_profit=round(1.0 - prob_itm, 4),
        expected_payoff=round(expected_payoff, 2),
        net_ev=round(net_ev, 2),
        net_ev_mid_naive=round(net_ev_mid_naive, 2),
        net_ev_if_round_tripped=round(net_ev - exit_cost_dollars, 2),
        return_on_risk=round(net_ev / spread.max_loss, 4) if spread.max_loss > 0 else 0.0,
        iv_short=round(iv_s, 4),
        iv_long=round(iv_l, 4) if iv_l else None,
        sigma_used=round(sigma_used, 4),
        delta_short=round(g.delta, 4),
        moneyness_pct=round((spread.short.strike - spot_equiv) / spot_equiv * 100, 3),
        exit_cost_projected=round(exit_cost_projected, 2),
        net_ev_if_round_tripped_projected=round(net_ev - exit_cost_projected, 2),
        admissible=reject is None,
        reject_reason=reject,
        prob_source=breach["source"],
        prob_model=breach["model"],
        prob_empirical=breach["empirical"],
        empirical_samples=breach["samples"],
    )


def _reject_reason(spread: PutCreditSpread, spot: float, prob_win: float) -> str | None:
    """Why this candidate must not be traded. Refusals are journalled, so the
    reason has to be specific enough to audit after the fact."""
    if config.REQUIRE_SHORT_OTM and spread.short.strike >= spot:
        return f"short strike {spread.short.strike:g} not OTM (spot {spot:.2f})"
    if prob_win < config.MIN_PROB_WIN:
        return f"P(win) {prob_win:.3f} < {config.MIN_PROB_WIN}"
    ratio = spread.credit_fill / spread.width if spread.width else 0.0
    if ratio < config.MIN_CREDIT_TO_WIDTH:
        return f"credit/width {ratio:.3f} < {config.MIN_CREDIT_TO_WIDTH}"
    if ratio > config.MAX_CREDIT_TO_WIDTH:
        return f"credit/width {ratio:.3f} > {config.MAX_CREDIT_TO_WIDTH} (too close to the money)"
    if spread.credit_fill < config.MIN_CREDIT_FILL:
        return f"credit {spread.credit_fill:.3f} < {config.MIN_CREDIT_FILL}"
    if spread.max_loss < config.MIN_MAX_LOSS:
        return f"max loss ${spread.max_loss:.0f} < ${config.MIN_MAX_LOSS:.0f} (too small to matter)"
    if spread.max_loss > config.MAX_LOSS_PER_POSITION:
        return f"max loss ${spread.max_loss:.0f} > cap ${config.MAX_LOSS_PER_POSITION:.0f}"
    return None


def build_candidates(
    puts: list[Contract],
    underlying: str,
    expiry: str,
    widths: list[float],
) -> list[PutCreditSpread]:
    """Every (short, long) pair at the requested widths."""
    by_strike = {c.strike: c for c in puts}
    out: list[PutCreditSpread] = []
    for short in puts:
        if not short.tradeable:
            continue
        for w in widths:
            long = by_strike.get(short.strike - w)
            if long is None or not long.tradeable:
                continue
            s = PutCreditSpread(underlying, expiry, short, long)
            if s.valid:
                out.append(s)
    return out


def to_dict(ev: Evaluation) -> dict:
    return asdict(ev)
