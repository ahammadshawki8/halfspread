# HALFSPREAD

**An autonomous options agent built on one finding: in short-dated options, the exit is where the money dies.**

Live dashboard -> **https://ahammadshawki8.github.io/halfspread/**
Alpaca paper account under judging -> `0509a308-f1ef-44e2-8e8b-8a6d0893f84b`

---

## The finding

Every premium-selling agent opens a position and later **closes** it. That closing trade is where the money goes, and almost nobody prices it.

Measured on this account, this session, and reproducible from the journal in this repository:

| | |
|---|---|
| SPY half-spread at the money | **1.04%** of mid |
| SPY half-spread 2-3% out of the money | **14.29%** of mid - **13.8×** worse |
| Near-the-money spread, now vs the session's first reading | **5.35×** |
| Largest decision-to-execution drift on a live order | **$4.00/contract**, against a $1.00 bid-ask cost |

Two consequences the agent is built around:

1. **The textbook strike is the expensive one.** "Sell the 15-20 delta" lands exactly where relative cost is worst. Strike selection here maximises net expected value *after* measured cost, so it does not go where a delta screen would send it.
2. **The exit costs multiples of the entry, and it is optional.** An out-of-the-money contract that simply expires costs nothing to exit - no closing trade, no spread, and Alpaca charges no commission. So the agent trades only defined-risk structures it intends to hold to settlement.

There is a third finding it did not want: **the edge is thin.** Admitted candidates need breakeven win rates of 83-97% against modelled win probabilities of 73-92%. That is Vilkov's 2026 result reproducing in live quotes, and it is why this agent is sized to survive rather than to produce a headline number.

## Verify it yourself

No API key, no account, no network:

```bash
git clone https://github.com/ahammadshawki8/halfspread && cd halfspread
python -m agent.verify
```

Nine claims, each re-derived from the committed append-only journal. Exit code is non-zero if any fails to reproduce.

## What it does

```
preflight -> observe -> price -> cost -> select -> gate -> review -> execute -> monitor -> settle
```

- **Prices its own greeks.** Alpaca's indicative feed returns zero greeks and null implied volatility at every strike, so the agent solves implied vol from mid by bisection and derives its own delta, gamma, theta and vega.
- **Finds its own reference level.** Alpaca publishes no index spot, so for XSP and SPXW the forward is recovered from put-call parity on the chain itself.
- **Measures cost before every order.** Credit at mid versus credit actually fillable, per leg, then net expected value after that cost. Nothing reaches the broker without both numbers attached.
- **Re-quotes immediately before submitting.** Scanning the universe takes seconds and the market moves inside that window; the limit is set from quotes taken seconds before the order goes out, and the drift is recorded.
- **Counts breach probability from history, not a diffusion.** Black-Scholes assumes lognormal returns. Measured SPY sessions are not - at 10:00 ET the 1st-percentile move to the close is −1.85% against a 0.70% standard deviation. `agent/empirical.py` builds the distribution of return-to-close by hour from **5,539 bars across 668 sessions**, and sizing takes the worse of model and history.
- **Chooses its structure and its expiry by measurement.** Vertical spreads and four-leg iron condors are scored onto one ranking; so are same-day and next-session expiries. Neither is a default.
- **Exits on arithmetic, not a trigger.** A distance trigger would pay a 5×-widened spread to escape an already-capped loss. The monitor instead compares what buying the package back costs *now* against the expected terminal intrinsic, and holds unless closing is materially cheaper. Holding through a breach is journalled with its reasoning.
- **Keeps an AI on a short leash.** A Groq-hosted open-weights model reviews live headlines for event risk and can only **scale size down**, never up - the multiplier is clamped in code, not requested in a prompt. If the model is unreachable the deterministic decision stands.

## Evidence, not assertion

The journal is append-only JSONL, committed to this repository, and records refusals with the same weight as fills. The dashboard computes nothing of its own - every figure on it is derived from that journal, so the page and the repository cannot drift apart.

When the ledger once showed P&L that had not happened, the bug, the removal and the reasoning were written into the journal as a `journal_correction` record and are visible in the decision log. Nothing is removed silently.

## Built on Alpaca

- **Trading API** - multi-leg (`mleg`) packages, two-leg verticals and four-leg condors, all legs covered within one order for Level 3.
- **CLI** - the agent's hands. Every broker action is an `alpaca` invocation recorded verbatim and replayable by hand.
- **MCP server** - the window onto the desk (`.mcp.json`), served through a stdio proxy that *enforces* read-only. Alpaca's toolset filter does not remove the order-placing tools, so `agent/mcp_readonly.py` strips every mutating tool from `tools/list` and refuses a call to one by name: **11 of 35 blocked, 24 reads pass through** (`python -m agent.mcp_readonly --audit`).
- **Market Data API** - chains, snapshots, news, and the intraday bar history behind the empirical distribution.

A note on the data: options quotes come from Alpaca's **indicative** feed, not OPRA. Every cost figure here is the cost this account was actually charged on that feed, which is also the feed paper fills are simulated against - the accounting is internally consistent. It is not a claim about the OPRA market spread, and where that distinction matters this project says so rather than rounding it away.

## Run it

```bash
pip install -r requirements.txt # standard library only; this is a no-op
cp .env.example .env # add your Alpaca paper keys

python -m agent.scan --curve # read-only: price every candidate, no orders
python -m agent.empirical --report # the measured intraday distribution
python -m agent.run --once # one full decision cycle, dry run
python -m agent.session --minutes 60 # observer + agent + monitor for a session
python -m agent.verify # re-derive every published claim
```

The competition account is refused by `agent/execute.py` unless an explicit arming token is passed at the call site, so it cannot be traded by accident.

## Layout

```
agent/
 config.py thresholds, universe, account routing
 cli.py Alpaca CLI wrapper; every invocation journalled
 pricing.py Black-Scholes, implied-vol solve, greeks
 empirical.py measured intraday move distribution (668 sessions)
 chain.py OCC parsing, chain retrieval, put-call-parity forward
 cost.py entry cost, exit cost, net EV, admissibility gates
 condor.py four-leg iron condors, scored onto the same ranking
 risk.py sizing, per-position and per-day loss caps
 llm.py bounded event-risk review; clamped to shrink-only
 execute.py mleg construction, re-quote, submission
 monitor.py pin-risk watch, net-of-cost close decision
 settle.py settlement accounting and the counterfactual
 session.py one session: observer, agent and monitor together
 verify.py re-derive published claims from the journal
docs/ the dashboard (GitHub Pages)
data/journal/ append-only decision record
```

Runs unattended on GitHub Actions (`.github/workflows/session.yml`), which commits its own journal back - no server, no cost.

---

Paper trading is a simulation. Hypothetical results do not represent actual trading and do not guarantee future results. Options carry substantial risk and are not suitable for every investor; see [Characteristics and Risks of Standardized Options](https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document). Nothing here is investment advice.

MIT licensed.
