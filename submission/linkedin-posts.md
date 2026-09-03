# HALFSPREAD - LinkedIn posts

Five posts, five different angles. Written to be read by a person, not by an algorithm.

Every number below is real and is reproducible from the journal in the repository. If a figure
has moved by the time you post, run `python -m agent.publish` and read the current one off the
README, or check the live page. Do not post a number you have not checked.

Tag **@lablab.ai** and **@Alpaca** on each. Post them a few hours apart rather than all at once.

---

## Post 1 - the finding

**Attach:** `assets/01-cost-of-the-exit.png`

> I spent a week building an options trading agent and the most useful thing I found had nothing
> to do with predicting anything.
>
> I measured what it costs to *leave* a trade.
>
> Thirteen tickers, quoted at the same minute. NVDA cost 0.52% of the contract's value to cross.
> AAPL 1.27%. Then the same measurement on contracts with 26 minutes left to expiry: SPY 14.29%,
> QQQ 33.33%, IWM 100%.
>
> Same market. Same afternoon. The only difference is how long the contract had left.
>
> Almost every agent I looked at optimises the entry signal and treats the spread as a rounding
> error. It is not a rounding error. Near expiry it is the whole trade.
>
> So I built the thing backwards from that: measure execution cost before every order, rank
> structures by what is left after that cost, and then refuse to pay it a second time by letting
> positions settle instead of closing them.
>
> #Options #QuantitativeFinance #AlgorithmicTrading #BuildInPublic

---

## Post 2 - the bug

**Attach:** `assets/02-verification.jpg`

> My dashboard told me I had made $316.
>
> I had made nothing. Every position was still open with six hours to run.
>
> The bug was one line. My settlement code compared the expiry *date* to today, and a contract
> expiring today passes that check all day long. So it resolved live positions against a
> mid-session price and booked profit that did not exist.
>
> What bothered me was not the bug. It was that I nearly shipped it, because the number looked
> good and I did not check a good number as hard as I would have checked a bad one.
>
> Two things came out of it. The eleven fabricated records were deleted and a correction record
> was written into the journal in their place, so the removal is part of the permanent record
> rather than a quiet edit. And I wrote a command that re-derives every published claim from that
> journal with no API key, no account and no network, which now runs on every push and fails the
> build if a number stops reproducing.
>
> If you are building anything that reports its own performance, I would genuinely recommend
> that second one. It is not hard to write and it changes how you feel about your own numbers.
>
> #BuildInPublic #SoftwareEngineering #FinTech #DataIntegrity

---

## Post 3 - the AI

**Attach:** `assets/03-ai-on-a-leash.png`

> My trading agent has a language model in it. It is allowed to do exactly one thing: make a
> position smaller.
>
> It cannot pick a strike. It cannot size a trade. It cannot overrule a risk gate. It cannot
> enlarge anything. The multiplier it returns is clamped between 0 and 1 in code, not requested
> politely in a prompt, so a model that decides to double the position gets its answer truncated
> to "no change".
>
> That is a deliberately small job. It is also the one job here that a human is genuinely worse
> at automating: reading unstructured event risk off the wire. On its first live session it
> pulled Strait of Hormuz attacks out of the headlines and cut the position.
>
> It then tried to block the trade entirely, and I overruled it. The position was already
> defined-risk with a hard dollar cap, so the tail it was worried about was the one the structure
> had already bounded. Refusing a capped-loss trade because of tail risk is the wrong response,
> and the fix was to let the model shrink but never abstain.
>
> Everything else is arithmetic. If the model is unreachable, the deterministic decision stands
> and the desk keeps trading.
>
> I am not sure "give the LLM less to do" is the popular position right now. I am fairly sure it
> is the right one when there is money involved.
>
> #AI #LLM #RiskManagement #FinTech #AlgorithmicTrading

---

## Post 4 - the result *(live site link)*

**Link:** https://ahammadshawki8.github.io/halfspread/

> The agent settled its first two positions today, and the result is small enough to be honest
> about.
>
> Two defined-risk spreads on SPY and XSP. Both expired out of the money. Realised P&L $71.00 on
> $69.00 of credit collected, with $7.00 paid to the bid-ask on the way in and **$0.00 on the way
> out**, because there was no way out. They simply expired.
>
> The interesting number is the counterfactual. Had the agent closed those positions the way most
> systems do, the same two trades would have returned $61.00. Not paying to leave was worth 14%
> of the gain.
>
> Every figure on the page below is derived from an append-only journal in the repository, and
> the page computes nothing of its own, so it cannot drift from the record. You can also price a
> trade yourself against the live chain: pick a strike, and the same engine that decides the
> agent's orders will tell you what it costs to enter, what leaving would cost right now, and
> which gate rejects it.
>
> Most combinations get rejected. That is the point of it.
>
> Built for the Alpaca AI Trading Agents hackathon with @lablab.ai and @Alpaca.
>
> #AlgorithmicTrading #Options #Hackathon #FinTech #BuildInPublic

---

## Post 5 - the build *(repo link)*

**Link:** https://github.com/ahammadshawki8/halfspread

> `requirements.txt` in this project is empty, and that was not a stunt.
>
> The data feed returns zero greeks and a null implied volatility at every single strike. So the
> agent solves implied vol itself by bisection and derives its own delta, gamma, theta and vega.
> Alpaca publishes no spot price for cash indices, so for XSP and SPXW the forward is recovered
> from put-call parity on the option chain itself. Black-Scholes assumes lognormal returns, and
> measured sessions are not lognormal, so breach probability is counted from 668 real trading
> sessions and the agent sizes on whichever of the two is worse.
>
> None of that needed a framework. It needed the Python standard library and a willingness to
> write the maths.
>
> The parts I did not expect to be the hard bits: Alpaca signs a multi-leg limit price from the
> package's point of view, so a credit spread submitted with a positive limit silently behaves
> as a market order. And the gap between scanning and submitting cost more than the bid-ask did,
> $7 a contract against $1, so every order now re-prices both legs seconds before it goes out.
>
> Repo is below. Clone it and run `python -m agent.verify` and it will re-derive every claim I
> have made from the committed journal, with no keys and no network. If any of them stops
> reproducing it exits non-zero.
>
> #OpenSource #Python #QuantitativeFinance #SoftwareEngineering #BuildInPublic

---

## Assets

| File | Used by | What it is |
|---|---|---|
| `assets/01-cost-of-the-exit.png` | Post 1 | Thirteen tickers, cost to cross, sorted, with hours to expiry. 1200x630. |
| `assets/02-verification.jpg` | Post 2 | The verification panel on the live site, 10 of 10 claims reproducing. |
| `assets/03-ai-on-a-leash.png` | Post 3 | The model's boundary: what it may do and what it cannot. 1200x630. |

Posters are generated from `assets/poster-cost.html` and `assets/poster-leash.html`. To refresh
them with newer numbers, edit the figures in those files, serve the folder
(`python -m http.server 8777`) and screenshot at 1200x630.

## A note on order

Post 1 first: it is the hook and it stands alone without any link. Post 4 and 5 carry the links,
so put them after people already know what this is. Post 2 and 3 are the ones most likely to be
shared by other engineers, so give them their own day rather than burying them.
