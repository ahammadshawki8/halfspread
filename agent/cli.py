"""Thin wrapper around the Alpaca CLI.

Every broker interaction goes through here so that the exact invocation is
journalled and can be replayed by hand. See CLAUDE.md R9.
"""
from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Sequence

from . import config, journal


class AlpacaError(RuntimeError):
    def __init__(self, argv: Sequence[str], message: str, raw: str = ""):
        super().__init__(message)
        self.argv = list(argv)
        self.raw = raw


def _shell_repr(argv: Sequence[str]) -> str:
    """Reproduce the command a human could paste into a terminal."""
    parts = []
    for a in argv:
        parts.append(f'"{a}"' if " " in a else a)
    return " ".join(parts)


def run(
    *args: str,
    profile: str = config.PROFILE_DEV,
    timeout: int = 30,
    journal_kind: str | None = "cli",
    allow_empty: bool = False,
) -> Any:
    """Run the CLI and return parsed JSON.

    Raises AlpacaError on non-zero exit, an error field in the payload, or
    unparseable output.
    """
    argv = [config.alpaca_bin(), "-p", profile, *args, "--quiet"]
    started = time.time()
    proc = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )
    elapsed_ms = round((time.time() - started) * 1000)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    parsed: Any = None
    parse_error = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    # The CLI reports API-level failures as a JSON object with a non-empty
    # "error" rather than a non-zero exit code.
    api_error = None
    if isinstance(parsed, dict) and parsed.get("error"):
        api_error = str(parsed["error"])

    ok = proc.returncode == 0 and api_error is None and parse_error is None

    if journal_kind:
        journal.write(
            journal_kind,
            command=_shell_repr(argv),
            profile=profile,
            ok=ok,
            exit_code=proc.returncode,
            elapsed_ms=elapsed_ms,
            error=api_error or parse_error or (stderr if not ok else None),
        )

    if api_error:
        raise AlpacaError(argv, f"alpaca API error: {api_error}", stdout)
    if proc.returncode != 0:
        raise AlpacaError(argv, f"alpaca exited {proc.returncode}: {stderr or stdout}", stdout)
    if parse_error:
        raise AlpacaError(argv, f"could not parse CLI output: {parse_error}", stdout)
    if parsed is None and not allow_empty:
        raise AlpacaError(argv, "alpaca returned no output", stdout)
    return parsed


# ---- convenience wrappers -------------------------------------------------

def account(profile: str = config.PROFILE_DEV) -> dict:
    return run("account", "get", profile=profile)


def clock(profile: str = config.PROFILE_DEV) -> dict:
    return run("clock", profile=profile)


def latest_stock_quote(symbol: str, profile: str = config.PROFILE_DEV) -> dict:
    return run(
        "data", "latest-quote", "--symbol", symbol, "--feed", config.STOCK_FEED, profile=profile
    )


def option_chain(
    underlying: str,
    expiration: str,
    opt_type: str = "put",
    strike_gte: float | None = None,
    strike_lte: float | None = None,
    limit: int = 200,
    profile: str = config.PROFILE_DEV,
) -> dict:
    args = [
        "data", "option", "chain",
        "--underlying-symbol", underlying,
        "--feed", config.OPTION_FEED,
        "--expiration-date", expiration,
        "--type", opt_type,
        "--limit", str(limit),
    ]
    if strike_gte is not None:
        args += ["--strike-price-gte", f"{strike_gte:g}"]
    if strike_lte is not None:
        args += ["--strike-price-lte", f"{strike_lte:g}"]
    return run(*args, profile=profile)


def positions(profile: str = config.PROFILE_DEV) -> list:
    return run("position", "list", profile=profile, allow_empty=True) or []


def orders(profile: str = config.PROFILE_DEV, status: str = "all") -> list:
    return run("order", "list", "--status", status, profile=profile, allow_empty=True) or []
