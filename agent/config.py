"""Central configuration. Everything tunable lives here."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "data" / "journal"

# Windows locally, Linux in CI. An explicit override wins over both.
_BIN_CANDIDATES = [
    Path(os.environ["ALPACA_CLI"]) if os.environ.get("ALPACA_CLI") else None,
    ROOT / "bin" / "alpaca.exe",
    ROOT / "bin" / "alpaca",
]

# ---- accounts -------------------------------------------------------------
# DEV: experimentation, test orders, anything goes.
# COMP: competition only. Never traded by hand. See CLAUDE.md R4.
PROFILE_DEV = "dev"
PROFILE_COMP = "comp"
COMP_ACCOUNT_ID = "0509a308-f1ef-44e2-8e8b-8a6d0893f84b"

# ---- market data ----------------------------------------------------------
# The Basic (free) plan only entitles us to the indicative feed. The CLI
# defaults to opra, which returns nothing for us, so this must be passed
# explicitly on every option data call. See CLAUDE.md R7 and 5.1.
OPTION_FEED = "indicative"
STOCK_FEED = "iex"

# Underlyings the agent prices every cycle. SPY is primary on measured cost
# (CLAUDE.md 5.1 Finding 3); the others stay in so measurement picks the
# winner rather than assumption.
UNIVERSE = ["SPY", "XSP", "SPXW"]

# Approximate spot scale relative to SPY, used only for strike-window sizing.
SPOT_SCALE = {"SPY": 1.0, "XSP": 1.0, "SPXW": 10.0}

# ---- pricing --------------------------------------------------------------
RISK_FREE_RATE = 0.042
TRADING_DAYS = 252
# Floor on time-to-expiry so 0DTE maths stays finite near the close.
MIN_T_YEARS = 1.0 / (365.0 * 24.0 * 60.0)  # one minute

# ---- strike search --------------------------------------------------------
# Percentage band around spot to pull from the chain. Deliberately wide: the
# whole point is to search for the net-EV maximum rather than snap to a delta.
STRIKE_BAND_PCT = 0.045
SPREAD_WIDTHS = [1, 2, 3, 5]  # in SPY points; scaled per underlying

# ---- risk -----------------------------------------------------------------
ACCOUNT_EQUITY = 100_000.0
MAX_LOSS_PER_POSITION = 700.0     # hard cap, dollars
MAX_LOSS_PER_DAY = 1_400.0        # 1.4% of the account
MAX_CONCURRENT_POSITIONS = 2
MIN_NET_EV = 1.0                  # dollars per contract; refuse marginal edges

# ---- candidate admissibility ---------------------------------------------
# The short strike must be genuinely out of the money. Selling ITM premium
# scores well on a naive EV screen but the "edge" is just mid-vs-model noise
# on the least reliable quotes in the chain (see the 780/775 case, 5.1).
REQUIRE_SHORT_OTM = True
MIN_PROB_WIN = 0.85
MIN_CREDIT_TO_WIDTH = 0.05
MAX_CREDIT_TO_WIDTH = 0.40
MIN_MAX_LOSS = 100.0              # ignore trades too small to matter
MIN_CREDIT_FILL = 0.05            # option points; below this the spread dominates

# ---- exit-cost projection -------------------------------------------------
# Entry and exit half-spreads are identical at a single instant. The thesis is
# that the exit happens HOURS LATER, once far-OTM 0DTE liquidity has gone.
# This multiplier is the placeholder; observe.py measures the real curve
# through the session and it should be replaced with that measurement.
EXIT_WIDENING_DEFAULT = 4.0
EXIT_WIDENING_MEASURED: dict[str, float] = {}

# Assumed haircut of realised vol vs implied vol (the variance risk premium).
# Conservative: we only claim a fraction of the documented premium.
#
# BE HONEST ABOUT THIS. Measured live on 2026-09-03, admitted candidates need
# breakeven win rates of 83-97% against modelled P(win) of 73-92%. On a binary
# max-profit/max-loss view almost every candidate is marginal. The positive net
# EV the model reports comes from this haircut and from the continuous payoff
# between the strikes - it is an assumption, not an observation. This is
# Vilkov's finding reproducing in live quotes, and the write-up must say so.
VRP_HAIRCUT = 0.12

# ---- session --------------------------------------------------------------
ODTE_ENTRY_CUTOFF_ET = "15:15"    # Alpaca rejects 0DTE opens after this
MARKET_CLOSE_ET = "16:00"


def alpaca_bin() -> str:
    for candidate in _BIN_CANDIDATES:
        if candidate and candidate.exists():
            return str(candidate)
    import shutil
    found = shutil.which("alpaca")
    if found:
        return found
    raise FileNotFoundError(
        "Alpaca CLI not found. Expected bin/alpaca(.exe), $ALPACA_CLI, or alpaca on PATH. "
        "Releases: github.com/alpacahq/cli/releases"
    )


def load_env() -> dict[str, str]:
    """Read .env without a dependency. Missing file is not an error."""
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env
