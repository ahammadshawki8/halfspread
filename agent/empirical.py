"""Empirical intraday move distribution.

The model's probability of breaching a short strike comes from Black-Scholes,
which assumes lognormal returns. Real index moves are not lognormal: they have
fat tails, they trend, and the size of the move left in a session depends on
what time of day it is in a way a constant-volatility diffusion does not
capture.

So rather than trust the assumption, this module measures it. It pulls SPY
intraday bars back to the start of Alpaca's history, and for every historical
session records the return from each time of day to that session's close. The
result is an empirical distribution of "how far can this still move before the
bell", conditioned on the hour, which gives a breach probability counted from
what actually happened instead of derived from what a diffusion would do.

The agent uses whichever of the two is more conservative, so the empirical
record can veto an optimistic model but never flatter it.

    python -m agent.empirical --rebuild       # fetch and cache
    python -m agent.empirical --report
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import cli, config

ET = ZoneInfo("America/New_York")
CACHE = config.ROOT / "data" / "empirical" / "spy_intraday.json"
HISTORY_START = "2024-01-02"
TIMEFRAME = "1Hour"


def _fetch_bars(symbol: str, start: str, timeframe: str, profile: str) -> list[dict]:
    """Page through Alpaca's bar history until it stops handing back tokens."""
    out: list[dict] = []
    token = None
    for _ in range(200):  # hard stop; ~40k bars is far more than we need
        args = [
            "data", "bars", "--symbol", symbol, "--timeframe", timeframe,
            "--start", start, "--limit", "10000", "--feed", config.STOCK_FEED,
        ]
        if token:
            args += ["--page-token", token]
        payload = cli.run(*args, profile=profile, journal_kind=None, timeout=60)
        bars = (payload or {}).get("bars") or []
        out.extend(bars)
        token = (payload or {}).get("next_page_token")
        if not token or not bars:
            break
    return out


def build(profile: str = config.PROFILE_DEV, start: str = HISTORY_START) -> dict:
    """Return-to-close, bucketed by the hour of the trading day."""
    bars = _fetch_bars("SPY", start, TIMEFRAME, profile)
    if not bars:
        raise RuntimeError("no bars returned")

    by_day: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for b in bars:
        ts = datetime.fromisoformat(str(b["t"]).replace("Z", "+00:00")).astimezone(ET)
        if not (9 <= ts.hour <= 16):
            continue
        by_day[ts.date().isoformat()].append((ts, float(b["c"])))

    # hour of day (ET) -> list of log returns from that bar to the day's close
    buckets: dict[int, list[float]] = defaultdict(list)
    sessions = 0
    for day, rows in by_day.items():
        if len(rows) < 3:
            continue
        rows.sort()
        close = rows[-1][1]
        if close <= 0:
            continue
        sessions += 1
        for ts, px in rows[:-1]:
            if px > 0:
                buckets[ts.hour].append(math.log(close / px))

    dist = {
        str(hour): {
            "n": len(vals),
            "quantiles": _quantiles(sorted(vals)),
            "mean": round(sum(vals) / len(vals), 6),
            "stdev": round(_stdev(vals), 6),
        }
        for hour, vals in sorted(buckets.items()) if len(vals) >= 30
    }

    payload = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbol": "SPY",
        "timeframe": TIMEFRAME,
        "start": start,
        "bars": len(bars),
        "sessions": sessions,
        "by_hour_et": dist,
        "samples": {str(h): sorted(v) for h, v in buckets.items() if len(v) >= 30},
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def _quantiles(sorted_vals: list[float]) -> dict:
    if not sorted_vals:
        return {}
    def q(p: float) -> float:
        i = min(len(sorted_vals) - 1, max(0, int(round(p * (len(sorted_vals) - 1)))))
        return round(sorted_vals[i], 6)
    return {"p01": q(.01), "p05": q(.05), "p10": q(.10), "p25": q(.25), "p50": q(.50),
            "p75": q(.75), "p90": q(.90), "p95": q(.95), "p99": q(.99)}


def _stdev(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


_CACHED: dict | None = None


def load() -> dict | None:
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    if not CACHE.exists():
        return None
    try:
        _CACHED = json.loads(CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return _CACHED


def breach_probability(spot: float, strike: float, now_et: datetime | None = None,
                       side: str = "put") -> tuple[float | None, int]:
    """Fraction of historical sessions whose move from this hour to the close
    would have finished through the strike. Returns (probability, sample size).
    """
    data = load()
    if not data or spot <= 0 or strike <= 0:
        return None, 0
    now_et = now_et or datetime.now(ET)
    samples = data.get("samples", {})

    hour = str(now_et.hour)
    vals = samples.get(hour)
    if not vals:
        # Fall back to the nearest hour we have.
        have = sorted(int(h) for h in samples)
        if not have:
            return None, 0
        hour = str(min(have, key=lambda h: abs(h - now_et.hour)))
        vals = samples[hour]

    needed = math.log(strike / spot)
    if side == "put":
        hits = sum(1 for v in vals if v <= needed)
    else:
        hits = sum(1 for v in vals if v >= needed)
    return hits / len(vals), len(vals)


def conservative_breach(model_prob: float, spot: float, strike: float,
                        side: str = "put", now_et: datetime | None = None) -> dict:
    """Take the worse of the model and the historical record.

    The empirical distribution can veto an optimistic model but never flatter
    it, so a fat tail the diffusion does not know about still costs us size.
    """
    emp, n = breach_probability(spot, strike, now_et, side)
    if emp is None:
        return {"prob": model_prob, "source": "model", "model": model_prob,
                "empirical": None, "samples": 0}
    return {
        "prob": max(model_prob, emp),
        "source": "empirical" if emp > model_prob else "model",
        "model": round(model_prob, 4),
        "empirical": round(emp, 4),
        "samples": n,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Empirical intraday move distribution")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--profile", default=config.PROFILE_DEV, choices=["dev", "comp"])
    args = ap.parse_args(argv)

    if args.rebuild:
        print("fetching SPY intraday history...", flush=True)
        d = build(args.profile)
        print(f"built from {d['bars']} bars across {d['sessions']} sessions "
              f"since {d['start']}")
    d = load()
    if not d:
        print("no cache; run with --rebuild")
        return 1

    print(f"\nSPY move from hour to close, {d['sessions']} sessions since {d['start']}")
    print(f"{'hour ET':>8} {'n':>6} {'p01':>9} {'p05':>9} {'p50':>9} {'p95':>9} {'stdev':>9}")
    for hour, s in d["by_hour_et"].items():
        q = s["quantiles"]
        print(f"{hour:>8} {s['n']:>6} {q['p01']*100:>8.2f}% {q['p05']*100:>8.2f}% "
              f"{q['p50']*100:>8.2f}% {q['p95']*100:>8.2f}% {s['stdev']*100:>8.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
