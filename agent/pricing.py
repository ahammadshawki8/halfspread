"""Black-Scholes pricing, implied-volatility solving and greeks.

Alpaca's indicative feed returns greeks of exactly zero and a null implied
volatility at every strike and every expiry (CLAUDE.md 5.1, Finding 2), so
the agent cannot consume them and computes its own. Standard library only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    v = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / v
    return d1, d1 - v


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str = "put") -> float:
    """European option price. Degenerates to intrinsic as T or sigma vanish."""
    T = max(T, config.MIN_T_YEARS)
    if sigma <= 1e-9 or S <= 0 or K <= 0:
        intrinsic = (K - S) if kind == "put" else (S - K)
        return max(intrinsic, 0.0) * math.exp(-r * T)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    disc = math.exp(-r * T)
    if kind == "put":
        return K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    return S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)


def implied_vol(
    price: float, S: float, K: float, T: float, r: float, kind: str = "put"
) -> float | None:
    """Solve for sigma by bisection. Returns None when the price is outside
    the no-arbitrage band, which happens routinely on stale or crossed quotes."""
    T = max(T, config.MIN_T_YEARS)
    if price <= 0 or S <= 0 or K <= 0:
        return None

    disc = math.exp(-r * T)
    intrinsic = max((K - S) if kind == "put" else (S - K), 0.0) * disc
    upper_bound = K * disc if kind == "put" else S
    if price <= intrinsic + 1e-9 or price >= upper_bound - 1e-9:
        return None

    lo, hi = 1e-4, 6.0
    if bs_price(S, K, T, r, hi, kind) < price:
        return None

    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, T, r, mid, kind) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta: float   # per calendar day
    vega: float    # per 1 vol point (0.01)


def greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str = "put") -> Greeks:
    T = max(T, config.MIN_T_YEARS)
    if sigma <= 1e-9:
        itm = (S < K) if kind == "put" else (S > K)
        return Greeks(delta=(-1.0 if kind == "put" else 1.0) if itm else 0.0,
                      gamma=0.0, theta=0.0, vega=0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    sqrtT = math.sqrt(T)
    disc = math.exp(-r * T)
    pdf = _norm_pdf(d1)

    if kind == "put":
        delta = _norm_cdf(d1) - 1.0
        theta_yr = -(S * pdf * sigma) / (2 * sqrtT) + r * K * disc * _norm_cdf(-d2)
    else:
        delta = _norm_cdf(d1)
        theta_yr = -(S * pdf * sigma) / (2 * sqrtT) - r * K * disc * _norm_cdf(d2)

    return Greeks(
        delta=delta,
        gamma=pdf / (S * sigma * sqrtT),
        theta=theta_yr / 365.0,
        vega=S * pdf * sqrtT * 0.01,
    )


def prob_itm(S: float, K: float, T: float, r: float, sigma: float, kind: str = "put") -> float:
    """Risk-neutral probability of finishing in the money, i.e. N(-d2) for a put."""
    T = max(T, config.MIN_T_YEARS)
    if sigma <= 1e-9:
        itm = (S < K) if kind == "put" else (S > K)
        return 1.0 if itm else 0.0
    _, d2 = _d1_d2(S, K, T, r, sigma)
    return _norm_cdf(-d2) if kind == "put" else _norm_cdf(d2)


def year_fraction(expiry_close_utc: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    seconds = (expiry_close_utc - now).total_seconds()
    return max(seconds / (365.0 * 24 * 3600.0), config.MIN_T_YEARS)
