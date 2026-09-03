"""Bounded event-risk veto.

The only place a language model touches this system. Its authority is
deliberately one-directional and bounded at both ends: it can shrink a
position, down to a floor, and it can do nothing else. Strike selection,
sizing, entry price and exit are decided by arithmetic in risk.py and
cost.py and are not shown to the model as adjustable.

The clamp is enforced in code, not by prompt: whatever comes back, the size
multiplier is forced into [0.0, 1.0]. A model that tries to double the
position gets its answer truncated to "no change".

If the model is unreachable or returns nonsense the agent proceeds on its
deterministic decision and journals the failure. The veto is an additional
safety layer, never a dependency - making it one would put a single point
of failure in front of a system whose entire argument is determinism.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import cli, config, journal

# The reviewer scales size; it does not abstain. Every position it sees is
# already defined-risk with a hard dollar cap enforced upstream, so the
# proportionate response to elevated event risk is a smaller position, not
# no position - the tail it is worried about is the one the structure has
# already bounded. A "block" is therefore honoured as the floor multiplier
# and logged as a conversion, so the model's judgement still shows up in the
# size and in the journal without it acquiring a prohibition it was not given.
VETO_FLOOR = 0.25

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PRIMARY_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "qwen/qwen3.8-27b"

SYSTEM_PROMPT = """You are a risk reviewer on an options desk. A deterministic \
system has already chosen a defined-risk put credit spread. You cannot change the \
strikes, the price, or the exit. Your only job is to judge scheduled or breaking \
EVENT RISK that would make selling downside premium into today's close unwise.

Things that justify reducing size:
- A major scheduled macro release landing during or just before the holding period \
(non-farm payrolls, CPI, PPI, FOMC decision or minutes, GDP, PCE).
- Breaking geopolitical, credit or systemic news likely to move the index sharply.
- An unusually large scheduled single-name event with index-level consequences.

Things that DO NOT justify reducing:
- Ordinary market commentary, analyst notes, price-target changes.
- Routine single-stock earnings with no index-level consequence.
- Speculation, opinion pieces, or "will the market go up today" filler.
- The general possibility that markets can fall. That is already priced and sized for.

Respond with ONE JSON object and nothing else:
{"action":"proceed"|"reduce"|"block","size_multiplier":<0.0-1.0>,\
"reason":"<one sentence, max 30 words>","events":["<event>"]}

action "proceed" requires size_multiplier 1.0.
action "reduce" requires 0.0 < size_multiplier < 1.0.
action "block" requires size_multiplier 0.0.
Default to "proceed" unless there is specific, identifiable event risk."""


@dataclass(frozen=True)
class VetoDecision:
    action: str              # proceed | reduce | block
    size_multiplier: float   # clamped to [0, 1] in code
    reason: str
    events: list[str]
    model: str | None
    ok: bool                 # False when the model failed and we fell through

    @property
    def blocks(self) -> bool:
        """True only if size was driven to nothing. With VETO_FLOOR in force
        this should not happen through the model path."""
        return self.size_multiplier <= 0.0


def _passthrough(reason: str) -> VetoDecision:
    return VetoDecision("proceed", 1.0, reason, [], None, False)


def fetch_headlines(symbols: str = "SPY,QQQ", limit: int = 25,
                    profile: str = config.PROFILE_DEV) -> list[dict]:
    try:
        payload = cli.run(
            "data", "news", "--symbols", symbols, "--limit", str(limit),
            "--exclude-contentless", profile=profile, journal_kind=None,
        )
    except Exception as exc:
        journal.write("news_error", error=str(exc))
        return []
    items = (payload or {}).get("news") or []
    return [
        {"headline": n.get("headline", ""), "created_at": n.get("created_at", ""),
         "source": n.get("source", "")}
        for n in items if n.get("headline")
    ]


def _call_groq(api_key: str, model: str, headlines: list[dict], context: str) -> dict | None:
    lines = "\n".join(f"- [{h['created_at']}] {h['headline']}" for h in headlines[:25])
    user = (
        f"Context: {context}\n\n"
        f"Recent headlines:\n{lines if lines else '(none retrieved)'}\n\n"
        "Judge event risk for selling a defined-risk put credit spread held to "
        "today's settlement. Respond with the JSON object only."
    )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }).encode()

    req = urllib.request.Request(
        GROQ_URL, data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Groq sits behind Cloudflare, which rejects urllib's default
            # User-Agent with error 1010 before the request reaches the API.
            "User-Agent": "halfspread/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    content = payload["choices"][0]["message"]["content"]
    return json.loads(content)


def _coerce(raw: dict, model: str) -> VetoDecision:
    """Validate and clamp. The model does not get to exceed its remit."""
    action = str(raw.get("action", "proceed")).strip().lower()
    if action not in ("proceed", "reduce", "block"):
        action = "proceed"

    try:
        mult = float(raw.get("size_multiplier", 1.0))
    except (TypeError, ValueError):
        mult = 1.0
    # Hard clamp. This is the guarantee, and it is enforced here rather than
    # asked for in the prompt.
    mult = max(0.0, min(1.0, mult))

    # Reconcile contradictions in the model's favour only when that means
    # taking less risk, then apply the floor.
    if action == "block":
        mult = 0.0
    elif action == "proceed":
        mult = 1.0
    elif mult >= 1.0:
        action, mult = "proceed", 1.0
    elif mult <= 0.0:
        action, mult = "block", 0.0

    converted = False
    if mult < VETO_FLOOR:
        mult = VETO_FLOOR
        converted = action == "block"
        action = "reduce"

    if converted:
        reason_prefix = "[block converted to floor size] "
    else:
        reason_prefix = ""

    reason = reason_prefix + (str(raw.get("reason", ""))[:200] or "no reason given")
    events = [str(e)[:120] for e in (raw.get("events") or [])][:6]
    return VetoDecision(action, mult, reason, events, model, True)


def event_risk_veto(
    context: str,
    symbols: str = "SPY,QQQ",
    profile: str = config.PROFILE_DEV,
    enabled: bool = True,
) -> VetoDecision:
    if not enabled:
        return _passthrough("veto layer disabled")

    api_key = config.load_env().get("GROQ_API_KEY", "").strip()
    if not api_key:
        d = _passthrough("no GROQ_API_KEY configured")
        journal.write("veto", **_as_record(d, 0))
        return d

    headlines = fetch_headlines(symbols, profile=profile)

    last_error = None
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            raw = _call_groq(api_key, model, headlines, context)
            if raw is None:
                continue
            decision = _coerce(raw, model)
            journal.write("veto", headlines_seen=len(headlines),
                          **_as_record(decision, len(headlines)))
            return decision
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

    d = _passthrough(f"model unreachable ({last_error}); proceeding on deterministic decision")
    journal.write("veto", error=last_error, **_as_record(d, len(headlines)))
    return d


def _as_record(d: VetoDecision, n_headlines: int) -> dict:
    return {
        "action": d.action,
        "size_multiplier": d.size_multiplier,
        "reason": d.reason,
        "events": d.events,
        "model": d.model,
        "model_ok": d.ok,
        "headlines_considered": n_headlines,
    }
