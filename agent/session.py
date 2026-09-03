"""One trading session, start to finish.

Runs the observer, the agent and the pin-risk monitor concurrently for a
bounded wall-clock duration, then captures pre-close quotes and settles.
The same entrypoint is used locally and in CI so that what runs unattended
is the thing that was tested.

    python -m agent.session --minutes 60                       # dev, dry run
    python -m agent.session --live --minutes 360
    python -m agent.session --profile comp --live --arm <token> --minutes 360
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import subprocess

from . import chain, cli, config, execute, journal, monitor, observe, publish, run, settle

ET = ZoneInfo("America/New_York")
_stop = threading.Event()


def _handle_stop(signum, frame):  # noqa: ARG001
    _stop.set()
    print("\nsession stopping...", file=sys.stderr)


def _log(tag: str, msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"{stamp} [{tag:<8}] {msg}", flush=True)


def _observer_thread(expiry: str, profile: str, interval: int) -> None:
    while not _stop.is_set():
        for u in sorted(config.UNIVERSE, key=lambda x: x != "SPY"):
            if _stop.is_set():
                return
            rec = observe.snapshot(u, expiry, profile)
            if rec:
                near = observe._band(rec["rows"], -1.0, 0.0)
                far = observe._band(rec["rows"], -3.0, -2.0)
                _log("observe", f"{u} ref={rec['reference_level']:.2f} "
                                f"near={near} far={far}")
        _stop.wait(interval)


def _monitor_thread(profile: str, interval: int, live: bool, arm: str | None,
                    threshold: float) -> None:
    while not _stop.is_set():
        try:
            rows = monitor.check(profile, threshold, live, arm)
            for r in rows:
                _log("monitor", f"{r['underlying']} {r['spread']} x{r['qty']} "
                                f"spot={r['spot']} dist={r['distance_to_short_pct']}% "
                                f"{'BREACHED' if r['breached'] else 'ok'}")
        except Exception as exc:
            _log("monitor", f"error {type(exc).__name__}: {exc}")
        _stop.wait(interval)


def _agent_thread(profile: str, expiry: str | None, interval: int, live: bool,
                  arm: str | None, use_veto: bool) -> None:
    while not _stop.is_set():
        try:
            out = run.cycle(profile=profile, expiry=expiry, live=live, arm=arm,
                            use_veto=use_veto, require_open=True)
            _log("agent", str(out))
        except run.Preflight as exc:
            _log("agent", f"preflight: {exc}")
        except Exception as exc:
            _log("agent", f"ERROR {type(exc).__name__}: {exc}")
            journal.write("cycle_error", error=str(exc))
        _stop.wait(interval)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HALFSPREAD trading session")
    ap.add_argument("--profile", default=config.PROFILE_DEV, choices=["dev", "comp"])
    ap.add_argument("--minutes", type=int, default=60, help="wall-clock budget")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--arm")
    ap.add_argument("--expiry")
    ap.add_argument("--no-veto", action="store_true")
    ap.add_argument("--agent-interval", type=int, default=900)
    ap.add_argument("--observe-interval", type=int, default=300)
    ap.add_argument("--monitor-interval", type=int, default=60)
    ap.add_argument("--pin-threshold", type=float, default=0.25)
    ap.add_argument("--publish-interval", type=int, default=600,
                    help="seconds between dashboard refreshes")
    ap.add_argument("--preclose-minutes", type=int, default=15,
                    help="capture the counterfactual this long before the close")
    args = ap.parse_args(argv)

    if args.profile == config.PROFILE_COMP and args.live and args.arm != execute.COMP_ARM_TOKEN:
        print("refusing: live COMP session needs --arm (R4).", file=sys.stderr)
        return 2

    signal.signal(signal.SIGINT, _handle_stop)
    try:
        signal.signal(signal.SIGTERM, _handle_stop)
    except (AttributeError, ValueError):
        pass

    expiry = args.expiry
    if not expiry:
        days = chain.next_expiries(2, profile=args.profile)
        if not days:
            print("calendar returned no trading days", file=sys.stderr)
            return 1
        now_et = datetime.now(ET).strftime("%H:%M")
        expiry = days[1] if now_et >= config.ODTE_ENTRY_CUTOFF_ET and len(days) > 1 else days[0]

    deadline = datetime.now(timezone.utc) + timedelta(minutes=args.minutes)
    mode = "LIVE" if args.live else "dry-run"
    _log("session", f"profile={args.profile} {mode} expiry={expiry} "
                    f"budget={args.minutes}min veto={'off' if args.no_veto else 'on'}")
    journal.write("session_start", profile=args.profile, live=args.live, expiry=expiry,
                  minutes=args.minutes)

    threads = [
        threading.Thread(target=_observer_thread,
                         args=(expiry, args.profile, args.observe_interval), daemon=True),
        threading.Thread(target=_agent_thread,
                         args=(args.profile, expiry, args.agent_interval, args.live,
                               args.arm, not args.no_veto), daemon=True),
        threading.Thread(target=_monitor_thread,
                         args=(args.profile, args.monitor_interval, args.live, args.arm,
                               args.pin_threshold), daemon=True),
    ]
    for t in threads:
        t.start()

    def _refresh_site() -> None:
        """Regenerate the dashboard payload and push it, so the published page
        tracks the running session instead of a snapshot taken by hand."""
        try:
            payload = publish.build(args.profile)
            publish.OUT.parent.mkdir(parents=True, exist_ok=True)
            import json as _json
            publish.OUT.write_text(_json.dumps(payload, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            _log("publish", f"payload failed: {type(exc).__name__}: {exc}")
            return
        for cmd in (
            ["git", "add", "-A", "docs", "data/journal"],
            ["git", "-c", "user.name=ahammadshawki8",
             "-c", "user.email=ahammadshawki8@users.noreply.github.com",
             "commit", "-q", "-m", "Session update: journal and dashboard"],
            ["git", "pull", "--rebase", "--autostash", "-q", "origin", "main"],
            ["git", "push", "-q", "origin", "main"],
        ):
            try:
                subprocess.run(cmd, cwd=str(config.ROOT), capture_output=True,
                               text=True, timeout=90)
            except Exception:
                break

    preclose_done = False
    last_publish = 0.0
    while not _stop.is_set() and datetime.now(timezone.utc) < deadline:
        try:
            clock = cli.clock(profile=args.profile)
            close_at = clock.get("next_close")
            if close_at and not preclose_done:
                closes = datetime.fromisoformat(close_at.replace("Z", "+00:00"))
                remaining = (closes - datetime.now(timezone.utc)).total_seconds() / 60
                if 0 < remaining <= args.preclose_minutes:
                    _log("preclose", f"{remaining:.1f}min to close, capturing counterfactual")
                    for r in settle.snapshot_preclose(args.profile):
                        _log("preclose", f"{r['underlying']} {r['spread']}: closing now would "
                                         f"cost ${r['exit_cost_if_closed_now']:.2f} "
                                         f"({r['widening_vs_entry']}x entry)")
                    preclose_done = True
            if not clock.get("is_open") and preclose_done:
                _log("session", "market closed")
                break
        except Exception as exc:
            _log("session", f"clock check failed: {exc}")

        if time.time() - last_publish > args.publish_interval:
            _refresh_site()
            last_publish = time.time()

        _stop.wait(30)

    _stop.set()
    _log("session", "winding down")
    for t in threads:
        t.join(timeout=10)

    try:
        for r in settle.settle(args.profile):
            _log("settle", f"{r['underlying']} {r['spread']} x{r['qty']}: "
                           f"P&L ${r['realized_pnl']:.2f} at {r['settlement_level']}")
    except Exception as exc:
        _log("settle", f"error: {exc}")

    rep = settle.report(args.profile)
    _log("session", f"report {rep}")
    journal.write("session_end", profile=args.profile, report=rep)
    _refresh_site()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
