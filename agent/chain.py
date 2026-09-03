"""Option chain retrieval, OCC symbol parsing and spot/forward discovery."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import cli, config, pricing

ET = ZoneInfo("America/New_York")

# Cash-settled index roots. Alpaca publishes no spot for these, so their
# reference level comes from put-call parity on the chain itself.
INDEX_ROOTS = {"XSP", "SPX", "SPXW", "VIX", "VIXW", "DJX", "NDX"}
OCC_RE = re.compile(r"^(?P<root>[A-Z]+)(?P<ymd>\d{6})(?P<kind>[CP])(?P<strike>\d{8})$")


@dataclass(frozen=True)
class Contract:
    symbol: str
    root: str
    strike: float
    expiry: str          # YYYY-MM-DD
    kind: str            # "call" | "put"
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    quote_ts: str

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def width(self) -> float:
        """Full bid-ask width in option points."""
        return self.ask - self.bid

    @property
    def half_spread(self) -> float:
        """What crossing costs relative to mid, in option points."""
        return self.width / 2.0

    @property
    def half_spread_pct(self) -> float | None:
        """Half-spread as a fraction of mid. The number nobody measures."""
        m = self.mid
        return (self.half_spread / m) if m > 0 else None

    @property
    def tradeable(self) -> bool:
        return self.ask > 0 and self.mid > 0 and self.ask >= self.bid


def parse_occ(symbol: str) -> tuple[str, float, str, str] | None:
    """SPY260903P00758000 -> ("SPY", 758.0, "2026-09-03", "put")"""
    m = OCC_RE.match(symbol)
    if not m:
        return None
    ymd = m.group("ymd")
    expiry = f"20{ymd[0:2]}-{ymd[2:4]}-{ymd[4:6]}"
    kind = "put" if m.group("kind") == "P" else "call"
    return m.group("root"), int(m.group("strike")) / 1000.0, expiry, kind


def expiry_close_utc(expiry: str) -> datetime:
    """US equity/index options stop trading at 16:00 ET on the expiry date."""
    y, mo, d = (int(x) for x in expiry.split("-"))
    return datetime.combine(
        datetime(y, mo, d).date(), time(16, 0), tzinfo=ET
    ).astimezone(timezone.utc)


def fetch(
    underlying: str,
    expiry: str,
    kind: str = "put",
    center: float | None = None,
    band_pct: float = config.STRIKE_BAND_PCT,
    profile: str = config.PROFILE_DEV,
) -> list[Contract]:
    """Pull one side of the chain for one expiry, optionally windowed around
    a reference level."""
    lo = hi = None
    if center is not None:
        lo, hi = center * (1 - band_pct), center * (1 + band_pct)

    payload = cli.option_chain(
        underlying, expiry, opt_type=kind, strike_gte=lo, strike_lte=hi,
        limit=200, profile=profile,
    )
    snapshots = (payload or {}).get("snapshots") or {}

    out: list[Contract] = []
    for symbol, snap in snapshots.items():
        parsed = parse_occ(symbol)
        if not parsed:
            continue
        root, strike, exp, k = parsed
        q = snap.get("latestQuote") or {}
        out.append(
            Contract(
                symbol=symbol, root=root, strike=strike, expiry=exp, kind=k,
                bid=float(q.get("bp") or 0.0), ask=float(q.get("ap") or 0.0),
                bid_size=int(q.get("bs") or 0), ask_size=int(q.get("as") or 0),
                quote_ts=str(q.get("t") or ""),
            )
        )
    out.sort(key=lambda c: c.strike)
    return out


def implied_forward(calls: list[Contract], puts: list[Contract]) -> tuple[float, float] | None:
    """Derive the forward from put-call parity: F = K + e^{rT}(C - P).

    Alpaca does not publish index spot data, so for XSP and SPXW the chain
    itself is the only reference level available. Uses the strike where the
    call and put mids are closest, which is where parity is best conditioned.
    Returns (forward, strike_used).
    """
    puts_by_strike = {p.strike: p for p in puts if p.tradeable}
    best: tuple[float, float, float] | None = None  # (|C-P|, strike, forward)

    for c in calls:
        if not c.tradeable:
            continue
        p = puts_by_strike.get(c.strike)
        if p is None:
            continue
        diff = abs(c.mid - p.mid)
        if best is None or diff < best[0]:
            best = (diff, c.strike, c.mid - p.mid)

    if best is None:
        return None
    _, strike, cp = best
    expiry = calls[0].expiry
    T = pricing.year_fraction(expiry_close_utc(expiry))
    forward = strike + math.exp(config.RISK_FREE_RATE * T) * cp
    return forward, strike


def spot_equivalent(forward: float, T: float) -> float:
    """Convert a forward into the spot the spot-based Black-Scholes in
    pricing.py expects: S = F * e^{-rT}."""
    return forward * math.exp(-config.RISK_FREE_RATE * T)


def reference_level(
    underlying: str, expiry: str, profile: str = config.PROFILE_DEV
) -> tuple[float, str, list[Contract], list[Contract]]:
    """Establish the pricing reference for an underlying.

    Returns (spot_equivalent, source, puts, calls). Prefers put-call parity
    because it works uniformly across equity ETFs and cash indices; falls
    back to the stock quote for SPY-like symbols.
    """
    # Every equity and ETF has a stock quote; the cash indices do not, which is
    # what put-call parity is for below. Anchoring a single name to SPY's price
    # would look for AAPL strikes near 770 and find an empty chain.
    center = None
    if underlying not in INDEX_ROOTS:
        try:
            q = (cli.latest_stock_quote(underlying, profile=profile) or {}).get("quote") or {}
            bid, ask = float(q.get("bp") or 0), float(q.get("ap") or 0)
            center = (bid + ask) / 2 if bid > 0 and ask > 0 else (bid or ask) or None
        except Exception:
            center = None
    if center is None:
        center = _last_known_center(underlying)

    puts = fetch(underlying, expiry, "put", center=center, profile=profile)
    calls = fetch(underlying, expiry, "call", center=center, profile=profile)

    T = pricing.year_fraction(expiry_close_utc(expiry))
    par = implied_forward(calls, puts)
    if par:
        forward, _ = par
        return spot_equivalent(forward, T), "put-call-parity", puts, calls
    if center:
        return center, "stock-quote", puts, calls
    raise RuntimeError(f"could not establish a reference level for {underlying}")


_CENTER_CACHE: dict[str, float] = {}


def _last_known_center(underlying: str) -> float | None:
    """Rough starting window so the first chain pull is not unbounded.
    Refined immediately by parity once quotes are in hand.

    Only scale off SPY for the index roots whose ratio to it is known. Doing
    that for an arbitrary ticker points the strike window at the wrong price
    entirely and the chain comes back empty.
    """
    if underlying in _CENTER_CACHE:
        return _CENTER_CACHE[underlying]
    if underlying not in config.SPOT_SCALE:
        return None
    spy = _CENTER_CACHE.get("SPY")
    if spy is None:
        return None
    return spy * config.SPOT_SCALE[underlying]


def remember_center(underlying: str, level: float) -> None:
    _CENTER_CACHE[underlying] = level


def next_expiries(count: int = 2, profile: str = config.PROFILE_DEV) -> list[str]:
    """Trading days from today forward, per Alpaca's calendar."""
    today = datetime.now(ET).date()
    payload = cli.run(
        "calendar",
        "--start", today.isoformat(),
        "--end", (today + timedelta(days=10)).isoformat(),
        profile=profile,
    )
    days = [row["date"] for row in (payload or []) if row.get("date")]
    return days[:count]
