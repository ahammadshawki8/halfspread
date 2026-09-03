"""A read-only proxy in front of Alpaca's MCP server.

Alpaca's `ALPACA_TOOLSETS` filter does not remove the order-placing tools:
they are built-in overrides rather than spec-driven operations, so a server
started with `account,trading,assets,news` still exposes `place_option_order`,
`close_position` and friends. That makes an MCP inspection window read-only by
convention, which is not a guarantee.

This proxy makes it one. It speaks stdio MCP on both sides, launches the real
server as a child, and:

  - strips every mutating tool out of `tools/list`, so a client never sees them
  - refuses `tools/call` for a mutating tool with an explicit JSON-RPC error,
    even if a client asks for one by name without listing first

Reads pass through untouched. Execution belongs to the CLI path in
`agent/execute.py`, which is journalled and replayable; nothing should ever
reach the broker through a window meant for looking.

    python -m agent.mcp_readonly            # stdio proxy
    python -m agent.mcp_readonly --audit    # list what is allowed and blocked
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading

# Anything that can create, change, cancel or destroy state at the broker.
# Matched against the tool name, case-insensitively, as whole words where the
# pattern is a verb so that "get_orders" is not caught by "order".
BLOCK_PATTERNS = [
    r"^place_", r"^create_", r"^submit_", r"^post_",
    r"^cancel_", r"^delete_", r"^close_", r"^replace_", r"^patch_", r"^update_",
    r"^exercise", r"^do_not_exercise", r"^liquidate",
    r"_order$", r"^add_to_watchlist", r"^remove_from_watchlist",
]
_BLOCK = [re.compile(p, re.I) for p in BLOCK_PATTERNS]


def is_mutating(tool_name: str) -> bool:
    return any(p.search(tool_name or "") for p in _BLOCK)


def _child_env() -> dict:
    env = dict(os.environ)
    env.setdefault("ALPACA_PAPER_TRADE", "true")
    env.setdefault("ALPACA_TOOLSETS", "account,trading,assets,news")
    return env


def _spawn() -> subprocess.Popen:
    return subprocess.Popen(
        ["uvx", "alpaca-mcp-server", "--transport", "stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
        text=True, bufsize=1, env=_child_env(),
    )


def _refusal(msg_id, tool: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {
            "code": -32601,
            "message": (
                f"'{tool}' is blocked: this is a read-only window onto the desk. "
                "Orders are placed only through the journalled CLI path in "
                "agent/execute.py, which refuses the competition account without "
                "an explicit arming token."
            ),
        },
    }


def run_proxy() -> int:
    child = _spawn()
    blocked_calls: list[str] = []

    def pump_upstream() -> None:
        """Client -> server, refusing mutating calls before they are forwarded."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                child.stdin.write(line + "\n"); child.stdin.flush()
                continue

            if msg.get("method") == "tools/call":
                tool = ((msg.get("params") or {}).get("name")) or ""
                if is_mutating(tool):
                    blocked_calls.append(tool)
                    sys.stdout.write(json.dumps(_refusal(msg.get("id"), tool)) + "\n")
                    sys.stdout.flush()
                    continue

            child.stdin.write(json.dumps(msg) + "\n")
            child.stdin.flush()

    def pump_downstream() -> None:
        """Server -> client, stripping mutating tools out of any listing."""
        for line in child.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                sys.stdout.write(line + "\n"); sys.stdout.flush()
                continue

            result = msg.get("result")
            if isinstance(result, dict) and isinstance(result.get("tools"), list):
                result["tools"] = [t for t in result["tools"]
                                   if not is_mutating(t.get("name", ""))]
            sys.stdout.write(json.dumps(msg) + "\n")
            sys.stdout.flush()

    t = threading.Thread(target=pump_upstream, daemon=True)
    t.start()
    try:
        pump_downstream()
    except KeyboardInterrupt:
        pass
    finally:
        child.terminate()
    return 0


def audit() -> int:
    """Start the real server, list its tools, and show what the proxy does."""
    child = _spawn()

    def send(obj):
        child.stdin.write(json.dumps(obj) + "\n"); child.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "halfspread-audit", "version": "1.0"}}})
    json.loads(child.stdout.readline())
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = json.loads(child.stdout.readline()).get("result", {}).get("tools", [])
    child.terminate()

    allowed = sorted(t["name"] for t in tools if not is_mutating(t["name"]))
    blocked = sorted(t["name"] for t in tools if is_mutating(t["name"]))

    print(f"upstream server exposes {len(tools)} tools\n")
    print(f"BLOCKED by the proxy ({len(blocked)}):")
    for n in blocked:
        print(f"  x {n}")
    print(f"\nallowed through ({len(allowed)}):")
    for n in allowed:
        print(f"  . {n}")
    print(f"\n{len(blocked)} mutating tools removed; {len(allowed)} read-only tools remain.")
    return 0 if blocked else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only MCP proxy for Alpaca")
    ap.add_argument("--audit", action="store_true",
                    help="list which tools are blocked and which pass through")
    args = ap.parse_args(argv)
    return audit() if args.audit else run_proxy()


if __name__ == "__main__":
    raise SystemExit(main())
