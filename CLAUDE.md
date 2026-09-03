# HALFSPREAD

> **Autonomous options agent on Alpaca paper trading.**
> *In short-dated options, the exit is where the money dies. This agent is built to never take one.*

This file is the project's persistent memory. **A fresh Claude session must be able to read only this file and resume work.** Keep it current. Do not create parallel docs.

---

## 0. RULES CLAUDE MUST FOLLOW

These are hard rules from the project owner. Violating them is a defect.

| # | Rule |
|---|------|
| **R1** | **Attribution: `ahammadshawki8` ONLY.** Never add Claude, Anthropic, or any AI as co-author, contributor, or `Co-Authored-By` on any commit, PR, or file header. No "Generated with Claude Code" footers. Commits are authored by `ahammadshawki8 <ahammadshawki8@users.noreply.github.com>` and nobody else. |
| **R2** | **No new markdown/doc/summary files.** Do not create READMEs, summaries, reports, plans, or submission docs unless explicitly instructed. When something needs recording, **update this file**. (One exception already approved: the repo's own `README.md`, written only when instructed.) |
| **R3** | **Free tier only.** Never sign up for anything requiring a credit card or payment. If a service needs payment, find a free alternative or work around it. Flag it rather than paying. |
| **R4** | **COMP account is sacred.** No manual trades, no test orders, no experiments on the competition account — ever. All experimentation happens on DEV. Judges read COMP's activity as the agent's track record. |
| **R5** | **Automate everything.** Install software, fetch keys, configure tooling autonomously. Only ask the owner for things that genuinely require their identity or a human-only step. |
| **R6** | **Never claim unverified results.** Run the command, read the output, then state the outcome. No "should work". If a check fails, say so with the output. |
| **R7** | **Honest numbers.** Our data is the **indicative feed**, not OPRA. Never describe measured costs as "the true market spread" — always "the cost our broker charged on this feed". Disclose the feed limitation in any public write-up. |
| **R8** | Deadline is immovable: **2026-09-04 15:00 UTC**. When time is short, cut scope, never cut the mandatory gates (§3). |
| **R9** | Prefer the Alpaca **CLI** for anything the agent does. It is a scored differentiator (§7) and produces replayable, journalable invocations. |
| **R10** | Do not run `pip install` into system Python without `--user`, and never modify files outside the project dir + its memory dir. |

---

## 1. Context

| | |
|---|---|
| **Event** | lablab.ai × Alpaca AI Trading Agents Hackathon, 28 Aug – 4 Sep 2026 |
| **Deadline** | **2026-09-04 21:00 BST = 15:00 UTC = 11:00 ET** |
| **Goal** | **1st place. 2nd does not count.** ($2,500 + $300 Featherless credits) |
| **Owner** | ahammadshawki8 (solo build; a teammate handles video/slides/social at the end) |
| **Repo** | https://github.com/ahammadshawki8/halfspread |
| **Judging** | P&L performance · Technology implementation · Creativity & originality · Presentation & execution · Social engagement |

### Market windows before deadline
- **Thu 3 Sep:** 13:30–20:00 UTC (full session). 0DTE order cutoff **19:15 UTC** (15:15 ET).
- **Fri 4 Sep:** 13:30–15:00 UTC (90 min, overlaps submission crunch).
- **Total: ~8 hours of live market.** Thursday is the P&L run. Friday is the live demo.

---

## 2. The problem we are solving

Every premium-selling agent in this hackathon opens a position and later **closes** it. That closing trade is where the money dies, and almost nobody has priced it:

- For OTM 0DTE strikes, bid-ask spreads that are **~$0.05 wide at the open widen to $0.50 or more by 3 PM**. Far-OTM 0DTE options are *"nearly illiquid by mid-afternoon"* — closing a loser is expensive and closing a winner *"less profitable than theoretical P&L suggests."*
- **The exit costs roughly 10× the entry**, on exactly the contracts a premium seller holds, at exactly the hour everyone else is closing.
- An OTM contract that simply **expires costs zero**: no closing trade, no spread, and Alpaca charges no commission.

So the agent's central design decision is structural, not clever: **trade only defined-risk, cash-settled structures it intends to hold to settlement**, and price the entry cost before every order.

---

## 3. Mandatory gates (fail = not judged)

- [ ] Autonomous AI trading agent on Alpaca's **Trading API**
- [ ] Uses Alpaca's **MCP server or CLI** (we use **both** — CLI executes, MCP inspects)
- [ ] Strategy **incorporates options**
- [ ] **Brand-new** paper account, never used before, **exactly $100,000** starting balance
- [ ] COMP paper **account ID** submitted
- [ ] Public GitHub repo · deployed app + URL · video · slides · cover image · one-page write-up

---

## 4. Research backing

### Primary — the finding the project is built on
**Vilkov (2026), "0DTE Trading Rules: Tail Risk, Implementation, and Tactical Timing"**
SSRN 4641356 · replication package `github.com/vilkovgr/0dte-strategies` (MIT, 54★)

An **August 2026 correction** (`KNOWN-ISSUES.md`) reversed every net-of-cost conclusion in the paper. A transaction-cost unit-scale error charged the bid-ask half-spread at **1/100 of true size** (0.022 bp instead of 2.2 bp). Found by external replicators at gex.live.

| Structure (near-ATM, 10:00→16:00 ET) | Net SR before | **Net SR after** |
|---|---|---|
| Put ratio spread | +0.84 | **−0.61** |
| Risk reversal | +0.44 | **+0.10** |
| Bear put spread | +0.30 | **−0.73** |
| Strangle / straddle | −0.51 | **−0.97** |
| Iron butterfly / condor | −0.96 | **−2.67** |

Conditional rules: put-ratio **+0.93 → −0.75**; top-3 basket **+0.82 → −0.82**.
Author's verdict: *"No strategy or basket retains a positive net Sharpe ratio."*

> ⚠️ **`docs/paper/paper-annotated.md` in that repo is STALE** and still shows pre-correction numbers. Only trust `KNOWN-ISSUES.md`. The repo's Git LFS budget is exceeded, so data panels cannot be fetched.

**Why this doesn't invalidate us:** his structures are **near-the-money** and **round-tripped** (10:00 entry → 16:00 close). Ours are **far-OTM** and **held to settlement**. Different regime, separate evidence (below). We must never claim his numbers support our strategy — we cite him for the *cost dominance* finding.

### Supporting
- **~20-delta short strikes ⇒ ~80% probability of expiring OTM.** A 40-delta 7DTE bull put spread held to expiration ran an **80% win rate, 2023 → mid-2026**.
- **Liquidity evaporation in far-OTM 0DTE** (the 10× exit-cost asymmetry above).
- **Alpaca:** OTM positions simply expire, no closing trade; commission-free; index options European & cash-settled with no assignment path.

### Contextual (for the write-up's audit scorecard)
- *Beyond Agent Architecture: Execution Assumptions and Reproducibility in LLM-Based Trading Systems* — arXiv:2606.08285 (Yao & Zheng, Jun 2026). **7-dimension audit checklist**: point-in-time controls, split transparency, held-out evaluation, cost/turnover treatment, execution semantics, universe definition, artifact release.
- *The Alpha Illusion* — arXiv:2605.16895 (May 2026)
- *Profit Mirage: Information Leakage in LLM-based Financial Agents* — arXiv:2510.07920
- *Stop Comparing LLM Agents Without Disclosing the Harness* — arXiv:2605.23950

### Rejected candidates — do not revisit
- **Dispersion / correlation risk premium.** Most crowded vol trade on the Street; JPM dispersion index **−4.9% in March 2026, worst since 2011**; QVR flipped to reverse dispersion; premium "substantially thinner". Also 12–16 legs = too complex, and 1-day P&L is a coin flip.
- **Implementing Vilkov's conditional rules directly.** Net-negative post-correction; put ratio spreads carry a naked short leg and are **unexecutable on Alpaca Level 3**.
- **Pure execution/slippage-sniper (resting limit orders at mid).** Alpaca paper fills only **marketable** orders — a resting mid order may never fill, risking an empty account.

---

## 5. Environment (verified 2026-09-03)

| Tool | Status |
|---|---|
| Python | 3.14.0 (`python`, `py`) |
| Node / npm | v24.12.0 / 11.6.2 |
| git / gh | 2.52.0 / 2.93.0, authed as **ahammadshawki8** |
| Docker | 29.1.3 |
| **Alpaca CLI** | **`bin/alpaca.exe` v0.0.14** (Windows binary, no Go needed) |
| **uv / uvx** | `C:\Users\Shawki\AppData\Roaming\Python\Python314\Scripts\uvx.exe` (installed, **not on PATH**) |
| Missing | `jq` (use `alpaca --jq` or Python instead), `go` (not needed) |

### Alpaca platform facts
- **Paper accounts get options Level 3 automatically.** Spreads work with no approval.
- **Multi-leg:** `order_class: "mleg"` + `legs[]` (symbol, side, ratio_qty, position_intent). **No equity legs.** An mleg order is accepted **only if all legs are covered within that same order** — this blocks ratio spreads, naked shorts, and calendar rolls.
- **0DTE:** supported; orders on expiry day must be in **before 15:15 ET**; contracts very near expiry reject new opens.
- **Paper fills:** simulated against NBBO, **marketable orders only**, size **not** checked against NBBO liquidity, **10% random partial fills**.
- **Paper quirk:** expiry/assignment (NTAs) appear in the Activities endpoint only the **next day**; balances and positions update instantly.
- **Index options in paper:** SPX, SPXW, VIX, VIXW, DJX, XSP — European, cash-settled. ⚠️ **Market data availability for these is UNVERIFIED** — Alpaca's launch post said index data was not yet in their Market Data offering. **Tier 0 must settle this.**
- **Market data plan: Basic (free) = `indicative` feed for options.** Alpaca staff: *"The quotes are not actual OPRA quotes, they're just 'indicative' derivatives. The trades are also derivatives and they're delayed by 15 minutes."* 200 req/min. OPRA needs Algo Trader Plus ($99/mo) — **we do not buy it (R3)**.

### 5.1 Tier 0 measured findings (2026-09-03, ~11:15 UTC, market closed, quotes = 2026-09-02 close)

**Accounts**

| | DEV | COMP |
|---|---|---|
| Profile | `dev` | `comp` |
| Account no. | PA3WUMDUSE9N | PA31RB6YR1V6 |
| **Account ID** | — | **`0509a308-f1ef-44e2-8e8b-8a6d0893f84b`** ← submission form |
| Cash / equity | $100,000 | **$100,000 exactly** |
| Options level | 3 | 3 |
| Created | — | 2026-09-03 09:27:54Z |
| Orders / positions | — | **0 / 0 — pristine** |

Switch with `alpaca -p dev …` / `alpaca -p comp …`. Active profile is `dev`.

**Finding 1 — index option data IS available on the free tier.** The launch-post caveat is outdated.
`SPY` ✅ · `XSP` ✅ · `SPXW` ✅ · `SPX` returns empty (SPX is the AM-settled monthly root; **use SPXW** for weeklies/dailies).
Must pass `--feed indicative` — the CLI defaults to `--feed opra`, which we are not entitled to.

**Finding 2 — greeks and implied volatility are NOT provided.** Every contract at every expiry returns `greeks: {delta:0, gamma:0, rho:0, theta:0, vega:0}` and `impliedVolatility: null` on the indicative feed. Not a market-hours artifact — 30-day contracts behave the same.
➡️ **We compute our own.** `pricing.py` must solve implied vol from mid price (Black-Scholes, bisection/Newton) and derive delta/gamma/theta/vega. This is an asset, not a setback: strike selection rests on a pricing layer we own and can show.

**Finding 3 — the cost curve, measured. This reshapes the strategy.**
Half-spread as a percentage of mid, 0DTE puts, SPY spot 764.34:

| Moneyness | SPY half-spread | SPXW half-spread |
|---|---|---|
| ATM | **1.0%** | 1.9% |
| −1% OTM | **3.0%** | 4.6% |
| −2% OTM | **11.1%** | 10.2% |
| −3% OTM | **14.3%** | up to **70%** |

XSP is unusable: **15–25% half-spread even at the money.**

➡️ **Relative execution cost explodes as you go OTM.** The textbook "sell the 15–20Δ strike" plan lands exactly where the spread eats 10–15% of mid *per leg* — roughly 20–30% of the credit gone at entry, before any risk is taken.

➡️ **This is the project's core finding and it is our own measurement, not a citation.** There is a real, quantified tension: far-OTM = higher win rate but ruinous relative cost; near-ATM = cheap execution but lower win rate. Nobody in the field models it. **The agent's job is to find the strike that maximises net EV after measured entry cost — which will not be the strike a delta-only screen picks.**

**Instrument decision: SPY primary.** Cheapest at every moneyness, penny-wide near the money, deepest liquidity. Cost is the whole thesis, so picking a 2× costlier instrument for narrative points would be self-refuting.
**But the agent evaluates SPY, XSP and SPXW every cycle on net EV and journals the comparison**, letting measurement pick the winner. Same code path, keeps index options in play, and the comparison table is itself a demo asset.
Caveat: SPY is American-style and physically settled, so an ITM finish means assignment. That only bites when the short strike is breached — precisely the case where we would already be closing.

### 5.2b MCP inspection window

`uvx alpaca-mcp-server` (v3.4.7), configured in `.mcp.json`, pointed at COMP with
`ALPACA_TOOLSETS=account,trading,assets,news`. Keys come from the environment; nothing
is committed. Verified by speaking MCP over stdio directly.

**CLI is the agent's hands, MCP is the window.** Every order the agent places is an
`alpaca` invocation recorded verbatim in the journal and replayable by hand. Nothing is
executed through MCP.

### 5.3 Live-trading findings (2026-09-03, market open)

**mleg limit price is signed from the package's point of view.**
POSITIVE = maximum net **debit** you will pay. NEGATIVE = minimum net **credit** you require.
Proven: an order at `+0.16` filled at `-0.12` (behaved as a debit ceiling, i.e. a market order);
`-0.60` was accepted and correctly rested unfilled; `-0.08` filled at exactly `-0.08`.
**Credit spreads must be submitted negative.** `build_payload` now forces the sign.

**Decision-to-execution drift is larger than the bid-ask.** Scanning the universe takes seconds
and the market moves inside that window. One order: scan priced the credit at 0.13, a re-quote
seconds later showed 0.08 — **$5/contract of drift against a $1.00 bid-ask cost.** `execute.requote()`
now re-reads both legs immediately before submitting, sets the limit from those quotes, and
journals the drift.

**The edge is thin, and the write-up must say so.** Audited live candidates need breakeven win
rates of **83–97%** against modelled P(win) of **73–92%**. On a binary max-profit/max-loss view
almost every candidate is marginal or negative. The positive net EV the model reports comes from
the `VRP_HAIRCUT` assumption plus the continuous payoff between strikes — an assumption, not an
observation. **This is Vilkov's result reproducing in live quotes**, and it is the honest headline,
not something to hide.

**The veto scales size; it does not abstain.** It blocked a COMP entry over Strait of Hormuz
attacks and US-Iran escalation. Headlines real, response disproportionate: the position is already
defined-risk with a hard dollar cap, so the tail it feared was the one the structure had bounded.
Blocks are now converted to `VETO_FLOOR = 0.25` and logged as conversions.

**First COMP position (13:41 UTC):** SPY 765/763 put credit spread x3, short 765P @ 0.21,
long 763P @ 0.11, filled at exactly the -0.10 limit. Credit $30, max loss $567, SPY 769.51.
Order `81fd990e-a76b-4f7f-bba0-19d5c43e4d04`.

**Expected P&L is small and that is structural.** Credit/width runs 5-9%, so max profit is 5-9%
of max loss. A meaningful dollar P&L would need 6-10% of the account at risk; sizing for
survivability (1.4%/day cap) caps the day around +0.1-0.3%. Do not crank risk to chase a
headline number - a red account poisons every other criterion.

### 5.4 Two bugs that fabricated P&L (fixed 2026-09-03 14:20 UTC)

Caught because the published ledger showed **+$316 realised across 6 "settled" positions**
while every contract still had six hours to run. Both fixed; the fabricated records were
removed from the journal and a `journal_correction` entry appended in their place.

1. **`settle()` compared only the expiry DATE against today.** A contract expiring today is
   not expired until the close, so `expiry > today` was false all session and live positions
   were resolved hours early against a mid-session price. Same-day expiries now additionally
   require the market to be **closed**, and an unreachable clock fails closed.
2. **Journal records were not scoped by profile.** `open_spreads()` matched `order_intent`
   records from *any* profile against the positions of *one*, so DEV experiments were
   attributed to COMP. `open_spreads()`, `settle.report()` and `publish.build()` are now all
   profile-scoped, and settlement/emergency-close records carry their profile.

**Lesson worth keeping:** the dashboard is derived from the journal, so a journal bug becomes
a published lie. Any figure on that page must be reproducible from a broker call. When a number
looks good, check it against the account before believing it.

### Alpaca CLI command map
```
alpaca profile login [--api-key]     # OAuth (paper-only) or API keys
alpaca account get                   # account state
alpaca clock / calendar              # market open check
alpaca data option chain <UNDERLYING>
alpaca data option snapshot          # includes greeks + IV
alpaca data option latest-quotes     # bid/ask -> our cost measurement
alpaca option contracts              # contract discovery/filter
alpaca order submit | list | cancel
alpaca position list | close
alpaca api <METHOD> <path>           # raw escape hatch -> REQUIRED for mleg orders
```
Global flags: `--jq`, `--csv`, `--quiet`, `--schema`, `--debug`. JSON on stdout by default.
⚠️ **The CLI fires immediately — there are no confirmation prompts.**

⚠️ **Git Bash mangles API paths.** `alpaca api POST /v2/orders` becomes
`https://paper-api.alpaca.markets/C:/Program Files/Git/v2/orders` → 404. Export
`MSYS_NO_PATHCONV=1` for any shell call. Python's `subprocess` is unaffected, so
`agent/cli.py` does not need it.

⚠️ **Console encoding.** The Windows console is cp1252; printing non-ASCII raises
`UnicodeEncodeError`. Keep CLI output ASCII, or run with `PYTHONIOENCODING=utf-8`.

**Verified mleg payload for a put credit spread** (limit price is the net credit as a
*positive* number; Alpaca infers direction from the legs):
```json
{"order_class":"mleg","qty":"5","type":"limit","time_in_force":"day",
 "limit_price":"0.19",
 "legs":[{"symbol":"SPY260903P00759000","side":"sell","ratio_qty":"1","position_intent":"sell_to_open"},
         {"symbol":"SPY260903P00757000","side":"buy","ratio_qty":"1","position_intent":"buy_to_open"}]}
```

---

## 5.2 Deployment (zero cost, no card)

```
GitHub Actions  ->  runs agent/session.py (workflow_dispatch or cron 13:35 UTC)
      | commits
   the repo     ->  data/journal/*.jsonl = tamper-evident audit trail (git history)
      | serves
 GitHub Pages   ->  docs/index.html reads docs/data.json
```

- **Application URL: https://ahammadshawki8.github.io/halfspread/** (Pages source: `main` / `/docs`)
- Secrets in GitHub: `ALPACA_DEV_API_KEY`, `ALPACA_DEV_SECRET_KEY`, `ALPACA_COMP_API_KEY`, `ALPACA_COMP_SECRET_KEY`, `GROQ_API_KEY`
- **Featherless: dropped** — required a card, violates R3. Nothing depends on it.
- **LLM: Groq**, free tier, no card. `openai/gpt-oss-120b` primary, `qwen/qwen3.8-27b` fallback.
  Groq is behind Cloudflare and rejects urllib's default User-Agent with error 1010 — a
  `User-Agent` header is mandatory. Its JSON mode also requires the word "json" in the messages.
- Actions cron can fire late or be skipped, so the demonstrated session runs locally and CI is
  the autonomous-runtime proof.

## 6. Architecture

```
halfspread/
├── CLAUDE.md              # this file — persistent memory
├── bin/alpaca.exe         # Alpaca CLI (gitignored)
├── .env                   # DEV/COMP keys (gitignored)
├── agent/
│   ├── config.py          # profiles, thresholds, universe, account routing
│   ├── cli.py             # thin wrapper: run alpaca CLI, parse JSON, log invocation
│   ├── pricing.py         # ★ Black-Scholes: solve IV from mid, derive greeks (feed gives none)
│   ├── chain.py           # fetch chain, filter by DTE + moneyness band
│   ├── cost.py            # ★ half-spread measurement, net-EV, exit-cost counterfactual
│   ├── strategy.py        # candidate spread construction + ranking
│   ├── risk.py            # ES sizing, position/loss limits, pin-risk gate
│   ├── execute.py         # mleg order build + submit via `alpaca api`
│   ├── monitor.py         # pin-risk watch, emergency close (booked as cost event)
│   ├── settle.py          # expiry accounting, realized P&L, zero-exit-cost proof
│   ├── journal.py         # append-only JSONL: every decision, quote, cost, order
│   └── run.py             # main loop / entrypoint
├── dashboard/             # static site reading journal JSONL
└── data/journal/          # committed run artifacts (the evidence)
```

**Design principles**
1. **The CLI is the agent's hands.** Every broker action is a logged, replayable `alpaca` invocation. Never bypass it with raw HTTP unless the CLI genuinely cannot express the call.
2. **`cost.py` is the heart.** Nothing reaches the broker without a measured entry cost and a net-EV number attached.
3. **The journal is the product.** Append-only, one line per decision including refusals. It feeds the dashboard and the write-up.
4. **Deterministic core, bounded LLM.** Strike selection, sizing and exits are deterministic code. Any LLM role is narrow, optional, and can only shrink risk — never expand it.

### Linear flow (one cycle)
```
1  preflight    market open? account healthy? COMP vs DEV correct?
2  observe      underlying price + option chain (+ greeks/IV snapshot)
3  filter       target DTE (0–1); compute own IV + greeks (pricing.py); moneyness band
4  price        for each candidate: bid/ask both legs -> credit at realistic fill
5  cost         measure entry half-spread; compute net EV after cost
6  select       maximise net EV across strikes AND across SPY/XSP/SPXW
6b gate         net EV > threshold? ES sizing OK? position/loss limits OK?
                -> if NO: journal the refusal with the numbers, stop
7  execute      build mleg order, submit via CLI, journal invocation + fill
8  monitor      poll short-strike distance; breach -> emergency close (cost event)
9  settle       expiry: zero exit cost. Record realized P&L.
10 counterfact  what this trade WOULD have cost to close at 15:45 -> the headline
11 render       dashboard reads journal
```

---

## 7. Competitor analysis (~90 submissions, captured 2026-09-03)

| Territory | Count | Note |
|---|---|---|
| "LLM proposes, deterministic gates decide" | **~30** | **Saturated. Never lead with this.** |
| Credit spreads / VRP premium selling | ~12 | Crowded — our base trade lives here, so differentiate elsewhere |
| Multi-agent bull/bear/CIO debate | ~10 | Crowded |
| News / sentiment | ~8 | Crowded |
| Backtest-first research agents | ~5 | EdgeStack, Hindsight Alpha, Odysseus, DarkRoom |
| Human-in-the-loop approval | ~4 | BABIL, Vermilion, TradeMind, SolidRoute |
| **Execution cost / slippage** | **~4** | ⚠️ **Contested, not empty.** Lyceum ("execution-cost modeling"), Finly ("cost-modeled"), PrintRunner ("breaker at 2x costs"), "a continual learning agent" ("live execution quality") |
| Dealer gamma / GEX | 2 | Pin Desk, MSAR_HMM |
| Earnings vol crush | 2 | PrintRunner, ThetaTrap |
| Statistical arbitrage | 1 | Z-Gate |
| Correlation / dispersion · index options · VIX options · IV-surface/SVI · skew · term-structure carry | **0** | Genuinely empty |

**Where we actually differ:**
1. **Exit-cost avoidance as the design principle.** Nobody else. One competitor (Autobelay) explicitly *"closes every one before expiry"* — the literal anti-pattern.
2. **The Vilkov correction.** A 3-day-old reversal of a leading 2026 paper, caused by exactly the error the field is making. Nobody has it.
3. **Index options / cash settlement** as the mechanism enabling zero-cost exits. Zero competitors use index options.
4. **CLI as the execution path.** Most used MCP or the raw SDK. Alpaca's Trading API lead (Brandon Meyerowitz) is a judge.

**Judges:** Brandon Meyerowitz (Team Lead, Trading API, Alpaca) · Grace Gao (PM, Alpaca) · Tony Lee (Chief Brokerage Officer, Alpaca) · Chiranjeev Shah (Alpaca) · Pawel Czech (CEO, NativelyAI)

---

## 8. Strategy spec

| | |
|---|---|
| **Instrument** | **SPY primary** (measured cheapest, §5.1). Agent also prices XSP and SPXW each cycle and picks on net EV; the comparison is journalled. |
| **Structure** | Defined-risk put credit spread. **Strike chosen by net-EV maximisation, NOT by a delta target** — §5.1 Finding 3 shows the 15–20Δ strike is where relative cost is worst. Two legs, one `mleg` order. Both legs covered ⇒ Level 3 legal. |
| **Entry** | Cost-gated: measure half-spread per leg from live quotes, compute net EV, fire only above threshold. |
| **Exit** | **Settlement, not a trade.** Emergency close exists and is journalled explicitly as a cost event. |
| **Sizing** | Against expected shortfall, not mean P&L. Hard cap on max loss per position and per day. |
| **P&L posture** | High win-rate grind. Target a clean green day. A red account poisons every other criterion. |

**Known risks (state these honestly, never hide them):**
- **Pin risk** is the real exposure — a breached short strike forces a close into the widest spreads of the day.
- Cost measurement runs on the **indicative feed**: internally consistent (we pay what we measure in paper) but not real OPRA.
- **1–2 samples only.** An 80% win rate still loses one day in five.

---

## 9. Implementation tiers

### Tier 0 — Foundations & the blocking check ✅ COMPLETE
- [x] Verify toolchain (Python, Node, git, gh, Docker)
- [x] Install Alpaca CLI → `bin/alpaca.exe` v0.0.14
- [x] Install `uv`/`uvx`
- [x] Create GitHub repo `ahammadshawki8/halfspread`
- [x] Write CLAUDE.md
- [x] `.gitignore` (`.env`, `bin/`, `__pycache__`, venv)
- [x] DEV keys loaded; CLI profile `dev` authenticated
- [x] COMP keys loaded; CLI profile `comp` authenticated; account verified pristine
- [x] **BLOCKING CHECK RESOLVED — index option data IS available on the free tier** (see §5.1)
- [x] Greeks/IV availability checked — **NOT available** (see §5.1)
- [x] Measured real bid/ask widths across moneyness → instrument decision made (§5.1)

### Tier 1 — Read-only data layer ✅ COMPLETE
- [x] `cli.py` — CLI wrapper, JSON parse, invocation logging
- [x] `pricing.py` — Black-Scholes, IV solve, greeks (feed supplies none)
- [x] `chain.py` — OCC parsing, chain fetch, put-call-parity forward
- [x] `cost.py` — half-spread measurement + net-EV + admissibility gates
- [x] `journal.py` — append-only JSONL, fsynced
- [x] `scan.py` — read-only ranking. **Proved: 115 candidates priced, 16 admissible.**
- [x] `observe.py` — intraday widening recorder (measures the exit-cost claim)

### Tier 2 — Decision layer ✅ COMPLETE
- [x] Candidate construction + ranking (in `scan.py`, ranked by return on risk)
- [x] `risk.py` — sizing against max loss, daily budget, concurrency cap, pin-risk helper
- [x] Dry-run cycle producing a fully-costed proposal + journalled refusals

### Tier 3 — Execution ✅ CORE COMPLETE
- [x] `execute.py` — mleg build + submit via `alpaca api POST /v2/orders`
- [x] **mleg verified accepted on DEV** (order 561d6b22, status `accepted`, then cancelled)
- [x] mleg "all legs covered" constraint satisfied — a 2-leg vertical passes
- [x] COMP arming guard verified: submitting to COMP without the token raises
- [ ] Live fill during market hours (blocked until 13:30 UTC)

### Tier 3.5 — Orchestration ✅ COMPLETE
- [x] `run.py` — preflight → scan → size → veto → execute → journal
- [x] `llm.py` — bounded event-risk veto on Groq (clamped to [0,1] in code)
- [x] `monitor.py` — pin-risk watch, emergency close booked as a cost event
- [x] `settle.py` — expiry accounting, zero-exit-cost proof, counterfactual
- [x] `session.py` — one entrypoint running all three concurrently, local and CI

### Tier 4 — Live run on COMP (WAITING FOR THE OPEN)
- [x] COMP account created ($100,000 exactly), keys loaded, **untouched**
- [x] GitHub Secrets set (both profiles + Groq)
- [x] `.github/workflows/session.yml` — CI runtime, commits its own journal
- [ ] **Verify a real fill on DEV once the market opens (13:30 UTC)**
- [ ] Re-measure the cost curve during market hours before any COMP order
- [ ] **First live COMP entry**
- [ ] Confirm settlement and realized P&L

### Tier 5 — Dashboard & deploy ✅ CORE COMPLETE
- [x] `publish.py` — derives the payload from the journal; the page computes nothing
- [x] `docs/index.html` — ledger, cost curve, widening chart, decision log
- [x] **GitHub Pages live: https://ahammadshawki8.github.io/halfspread/**
- [ ] Re-verify rendering once real trades populate it

### Tier 6 — MCP layer ✅ COMPLETE
- [x] `.mcp.json` — Alpaca's official MCP server (v3.4.7) as the inspection window
- [x] Verified over stdio: initialises with COMP credentials, exposes **35 tools**
- [x] ⚠️ **Honest caveat recorded in `.mcp.json`:** the toolset filter does *not* remove
      `place_option_order` — order-placing tools are built-in overrides, not spec-driven
      operations. MCP is read-only *by convention*, not by enforcement. The real guarantee
      is `execute.py` refusing COMP without the arming token, plus the journal.

### Tier 7 — Submission (only on owner's instruction)
- [ ] Repo README · one-page write-up · audit scorecard vs arXiv:2606.08285 · cover image · slides · video · social posts

---

## 10. Session log

Newest first. One line per session. Keep it terse.

- **2026-09-03 (session 1, cont. 2)** — Tiers 3.5 and 5 done. Added the bounded Groq veto (it pulled US-Iran tensions and an oil surge out of live headlines, and independently flagged Friday's payrolls print), session runner, CI workflow, publisher and dashboard. Pages live. **Waiting on the 13:30 UTC open to verify a real fill on DEV, then go live on COMP.**
- **2026-09-03 (session 1, cont.)** — Tiers 1-3 core built and verified. Full pipeline runs end to end on DEV: scan prices 115 candidates and admits 16; best is SPY 759/757 at 0.19 credit, $181 max loss, P(win) 0.897, net EV $4.68; risk sizes it at 5 contracts for $905; mleg payload accepted by Alpaca then cancelled; COMP arming guard confirmed to refuse. Remaining before the 13:30 UTC open: `run.py`, `monitor.py`, `settle.py`.
- **2026-09-03 (session 1)** — Researched hackathon + ~90 competitors. Killed two candidates (dispersion; Vilkov's rules) on evidence. Locked HALFSPREAD. Installed Alpaca CLI + uv, created repo, wrote CLAUDE.md. DEV + COMP keys loaded and both profiles verified; COMP pristine at $100k. **Tier 0 complete** — index option data available, greeks NOT available (we compute our own), and the measured cost curve (§5.1 Finding 3) reshaped strike selection from delta-target to net-EV maximisation. Next: Tier 1.

---

## 11. Open questions / blockers

- ✅ ~~DEV keys~~ · ✅ ~~COMP account at exactly $100,000~~ · ✅ ~~index option data~~ — all resolved, see §5.1.
- 🟡 **Greeks must be computed in-house** (feed provides none). `pricing.py` is now on the critical path for Tier 1.
- 🟡 **Re-measure the cost curve during market hours.** §5.1 Finding 3 used 2026-09-02 closing quotes. Spreads widen intraday, especially after ~15:00 ET — confirm before the first COMP order.
- 🟡 Featherless AI ($25 free credits, no card) — optional partner integration; only if a bounded, honest role exists that doesn't contradict the deterministic-core design. Owner's call.
- 🟡 SPY assignment risk on an ITM finish (American, physically settled). Acceptable — only bites when the short strike is already breached — but `settle.py` must handle it.
