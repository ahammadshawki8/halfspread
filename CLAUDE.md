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

---

## 6. Architecture

```
halfspread/
├── CLAUDE.md              # this file — persistent memory
├── bin/alpaca.exe         # Alpaca CLI (gitignored)
├── .env                   # DEV/COMP keys (gitignored)
├── agent/
│   ├── config.py          # profiles, thresholds, universe, account routing
│   ├── cli.py             # thin wrapper: run alpaca CLI, parse JSON, log invocation
│   ├── chain.py           # fetch chain, filter by DTE + delta band
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
3  filter       target DTE (0–1) and delta band (~15–20Δ short strike)
4  price        for each candidate: bid/ask both legs -> credit at realistic fill
5  cost         measure entry half-spread; compute net EV after cost
6  gate         net EV > threshold? ES sizing OK? position/loss limits OK?
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
| **Instrument** | SPXW / XSP 0DTE–1DTE (European, cash-settled, no assignment). **Fallback: SPY/QQQ** if index data unavailable — an OTM expiry still costs nothing. |
| **Structure** | Far-OTM defined-risk credit spread. Short strike ~15–20Δ. Two legs, one `mleg` order. Both legs covered ⇒ Level 3 legal. |
| **Entry** | Cost-gated: measure half-spread per leg, compute net EV, fire only above threshold. |
| **Exit** | **Settlement, not a trade.** Emergency close exists and is journalled explicitly as a cost event. |
| **Sizing** | Against expected shortfall, not mean P&L. Hard cap on max loss per position and per day. |
| **P&L posture** | High win-rate grind. Target a clean green day. A red account poisons every other criterion. |

**Known risks (state these honestly, never hide them):**
- **Pin risk** is the real exposure — a breached short strike forces a close into the widest spreads of the day.
- Cost measurement runs on the **indicative feed**: internally consistent (we pay what we measure in paper) but not real OPRA.
- **1–2 samples only.** An 80% win rate still loses one day in five.

---

## 9. Implementation tiers

### Tier 0 — Foundations & the blocking check
- [x] Verify toolchain (Python, Node, git, gh, Docker)
- [x] Install Alpaca CLI → `bin/alpaca.exe` v0.0.14
- [x] Install `uv`/`uvx`
- [x] Create GitHub repo `ahammadshawki8/halfspread`
- [x] Write CLAUDE.md
- [ ] Receive DEV API key + secret; `alpaca profile login --api-key`
- [ ] **BLOCKING: verify index option data on the free tier** (`alpaca data option chain SPXW…`). Decides SPXW/XSP vs SPY. Nothing downstream is final until this returns.
- [ ] Verify chain returns greeks + IV on Basic plan
- [ ] Measure real bid/ask widths on target strikes; sanity-check the cost model's inputs
- [ ] `.gitignore` (`.env`, `bin/`, `__pycache__`, venv)

### Tier 1 — Read-only data layer
- [ ] `cli.py` — CLI wrapper, JSON parse, invocation logging
- [ ] `chain.py` — chain fetch, DTE + delta filtering
- [ ] `cost.py` — half-spread measurement + net-EV calculation
- [ ] `journal.py` — append-only JSONL
- [ ] Prove it: dump a live chain with measured costs, no orders placed

### Tier 2 — Decision layer (dry run, no execution)
- [ ] `strategy.py` — candidate construction + ranking
- [ ] `risk.py` — ES sizing, limits, pin-risk gate
- [ ] Dry-run cycle producing a fully-costed trade proposal + journalled refusals

### Tier 3 — Execution (DEV account first)
- [ ] `execute.py` — mleg build + submit via `alpaca api POST /v2/orders`
- [ ] Place a real DEV paper spread end-to-end; confirm fill and journal
- [ ] Verify the mleg "all legs covered" constraint is satisfied by our builder

### Tier 4 — Live run on COMP
- [ ] COMP account created ($100,000 exactly), keys loaded, **never touched by hand**
- [ ] `monitor.py` — pin-risk watch + emergency close
- [ ] `settle.py` — expiry accounting, zero-exit-cost proof, counterfactual
- [ ] **Thursday session: first live COMP entry**
- [ ] Confirm settlement and realized P&L

### Tier 5 — Dashboard & deploy
- [ ] Static dashboard reading journal JSONL (cost ledger + counterfactual as the hero)
- [ ] Deploy free (GitHub Pages / Vercel free tier) → Application URL

### Tier 6 — MCP layer
- [ ] Alpaca MCP server configured (`uvx alpaca-mcp-server`) as the judge's read-only window

### Tier 7 — Submission (only on owner's instruction)
- [ ] Repo README · one-page write-up · audit scorecard vs arXiv:2606.08285 · cover image · slides · video · social posts

---

## 10. Session log

Newest first. One line per session. Keep it terse.

- **2026-09-03 (session 1)** — Researched hackathon + ~90 competitors. Killed two candidates (dispersion; Vilkov's rules) on evidence. Locked HALFSPREAD. Installed Alpaca CLI + uv, created repo, wrote CLAUDE.md. **Blocked on: DEV API keys → index-option data check.**

---

## 11. Open questions / blockers

- 🔴 **DEV API key + secret** — needed to start Tier 0's blocking check.
- 🔴 **COMP account** must be created with **exactly $100,000** (balance is fixed at creation; only a reset changes it, which muddies the "brand-new account" claim).
- 🟡 Index option market data on the free tier — unverified, decides the instrument.
- 🟡 Featherless AI ($25 free credits, no card) — optional partner integration; only if a bounded, honest role exists that doesn't contradict the deterministic-core design.
