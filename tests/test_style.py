"""Enforces CLAUDE.md R11: no emoji and no long dashes in anything readable.

A rule that lives only in a document decays. This makes it fail the build.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BANNED = {
    "\u2014": "em dash",
    "\u2013": "en dash",
    "\u2192": "rightwards arrow",
    "\u2190": "leftwards arrow",
    "\u21d2": "double arrow",
    "\u2705": "check mark",
    "\u274c": "cross mark",
    "\u26a0": "warning sign",
}
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")

CHECKED = (
    ["README.md", "CLAUDE.md", ".mcp.json", "LICENSE", "requirements.txt",
     ".env.example", "docs/index.html"]
    + [f"agent/{p.name}" for p in (ROOT / "agent").glob("*.py")]
    + [f"tests/{p.name}" for p in (ROOT / "tests").glob("*.py")]
    + [f".github/workflows/{p.name}" for p in (ROOT / ".github/workflows").glob("*.yml")]
)


class TestNoEmojiOrLongDashes(unittest.TestCase):
    def test_readable_files_are_clean(self):
        offences = []
        for rel in CHECKED:
            path = ROOT / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), 1):
                for ch, name in BANNED.items():
                    if ch in line:
                        offences.append(f"{rel}:{line_no} contains {name}")
                if EMOJI.search(line):
                    offences.append(f"{rel}:{line_no} contains an emoji")
        self.assertEqual(offences, [], "R11 violations:\n  " + "\n  ".join(offences))

    def test_the_guard_would_actually_catch_something(self):
        self.assertIn("\u2014", BANNED)
        self.assertTrue(EMOJI.search("\U0001F680"))
