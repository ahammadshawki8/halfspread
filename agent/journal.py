"""Append-only decision journal.

The journal is the product, not a debug log. Every observation, every
refusal and every order goes in, one JSON object per line, so the dashboard
and the write-up are both derived from the same evidence rather than from
anything restated by hand.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

_lock = threading.Lock()


def _path_for(day: str | None = None) -> Path:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    config.JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    return config.JOURNAL_DIR / f"{day}.jsonl"


def write(kind: str, **payload: Any) -> dict:
    """Append one record. Returns the record so callers can log and pass on."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "kind": kind,
        **payload,
    }
    line = json.dumps(record, separators=(",", ":"), default=str)
    with _lock:
        path = _path_for()
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return record


def read(day: str | None = None) -> list[dict]:
    path = _path_for(day)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_all() -> list[dict]:
    if not config.JOURNAL_DIR.exists():
        return []
    out: list[dict] = []
    for path in sorted(config.JOURNAL_DIR.glob("*.jsonl")):
        out.extend(read(path.stem))
    return out
