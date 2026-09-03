# HALFSPREAD - demo video script

**Runtime:** about 4:40 at a natural speaking pace.
**Format:** screen recording with voiceover. No talking head required, though three
seconds of your face at the very end helps the "a real person built this" read.

## The shape of it

This follows the Veritasium structure, and the ordering is the whole point. Read this
before you record:

1. **Open on a misconception, not a topic.** A judge who believes they already
   understand options trading will watch the rest on autopilot. The first twenty
   seconds exist to break that belief. We show a real quote that makes no sense
   until it does.
2. **Ask the question before giving the answer.** School gives you the answer and
   then tests you. This gives you the problem and lets you want the answer. Section 3
   is a question on purpose. Do not move it later.
3. **Alternate story and technical.** Two technical sections back to back and people
   scrub forward. Every dense stretch here is bracketed by a human one: the corrected
   paper, the AI on a leash, the bug that published a lie. That alternation is load
   bearing, not padding.

Every figure spoken here is real and comes from the journal. If one has moved by the
time you record, run `python -m agent.publish` and read the current value. Do not
narrate a number you have not checked.

---

## 0:00 - 0:22 | The hook

**ON SCREEN**

Cold open. No logo, no title card, no introduction. Straight into a terminal that is
already filled, cursor blinking. Run the quote live so the numbers read as real:

    alpaca data option latest-quotes IWM260904P00238000 --feed indicative

Let the JSON print. As the voiceover names them, push two large text overlays onto the
frame, one at a time, sitting directly on the terminal:

- `BID 0.00`
- `ASK 0.08`

Hold on black for a beat after the last line before cutting.

**VOICEOVER**

> This is a real options contract, quoted by a real broker, a few minutes ago.
>
> The market says it is worth four cents.
>
> If I tried to sell it right now, I would get nothing. Zero.
>
> That is not a glitch, and it is not some exotic contract. It is a normal Wednesday
> afternoon. And almost every trading agent in this hackathon is about to find that
> out the expensive way.

---

## 0:22 - 1:05 | The measurement

**ON SCREEN**

Cut to `submission/assets/01-cost-of-the-exit.png`, the thirteen ticker chart, full frame.

Do not simply hold on it. Build it. Bring the eight green rows up first while the
voiceover covers NVDA and Apple, then let the five red rows slam in on the words
"twenty six minutes". The contrast between those two blocks is the entire point of the
shot, so give the edit that beat. Highlight each figure as it is spoken.

**VOICEOVER**

> So I measured it properly. Thirteen tickers, every one of them quoted in the same
> minute.
>
> On NVDA, crossing the spread costs half a percent of what the contract is worth. On
> Apple, one and a quarter percent. Those are fine. Those are what everybody assumes
> the number looks like.
>
> Now the same measurement, on contracts with twenty six minutes left to live.
>
> SPY, fourteen percent. QQQ, thirty three percent. IWM, one hundred percent.
>
> Same market. Same afternoon. Same broker. The only thing that changed is how long the
> contract had left.
>
> Near expiry, the spread is not a rounding error. It is the trade.

---

## 1:05 - 1:25 | The question

**ON SCREEN**

Go quiet and plain. Black screen, or the chart heavily dimmed. One line of type at a
time, nothing else moving. The visual restraint is what makes the question land.

The last line appears as type and stays up through the cut:

`What happens if you never get out?`

**VOICEOVER**

> Which raises a question this whole field seems to skip.
>
> Every agent out there optimises when to get in. What if the expensive decision was
> always getting out?
>
> And if getting out costs that much, what happens if you simply never do it?

---

## 1:25 - 2:00 | The solution

**ON SCREEN**

Now the logo, once, briefly. Then a simple payoff diagram: the two strikes, the credit
collected, the capped loss, and the underlying finishing above both. Animate price
drifting sideways into expiry and the position decaying to nothing.

On the word "expires", stamp `EXIT COST $0.00` across the frame.

**VOICEOVER**

> That is HALFSPREAD.
>
> It sells defined risk option spreads. Two legs, a hard cap on the loss, no naked
> exposure anywhere. But it chooses its strikes with one goal in mind: that the
> contracts expire worthless.
>
> Because an option that expires costs nothing to close. There is no closing trade. No
> spread to cross. No commission.
>
> Most agents pay that cost twice, once going in and once coming out. This one pays it
> once.

---

## 2:00 - 2:35 | The research

**ON SCREEN**

Screen recording of the actual `KNOWN-ISSUES.md` in the Vilkov replication repository,
scrolled to the correction itself. Then cut to the before and after Sharpe table from
the research section of the live site.

Animate the numbers flipping from the old column to the new one. Every single one
crosses zero. That one visual does more work than the narration does.

**VOICEOVER**

> And this is not my hunch.
>
> Last month, one of this year's leading zero day options studies was corrected. The
> bug was this: it had been charging the bid-ask spread at one hundredth of its real
> size.
>
> Every strategy in that paper flipped from profitable to unprofitable. Iron condors
> went from minus zero point nine to minus two point seven.
>
> The author's own conclusion was that no strategy retained a positive net Sharpe.
>
> Those are the exact structures most options agents are running right now.

---

## 2:35 - 3:25 | How it works

**ON SCREEN**

The densest stretch, so it needs the most visual help. Four quick beats, roughly twelve
seconds each, and each one a real artifact rather than a diagram of an artifact:

1. Terminal showing the snapshot response with `"delta": 0` and
   `"impliedVolatility": null` highlighted, then cut to `pricing.py` solving for it.
2. `chain.py`, the put-call parity line, with the recovered forward printing beside it.
3. The tails chart on the live site: the measured distribution sitting over the
   lognormal one.
4. A real `alpaca api POST /v2/orders` invocation pulled from the journal, then
   `python -m agent.mcp_readonly --audit` printing the 11 blocked and 24 allowed split.

Keep the cuts tight. If a shot needs longer than twelve seconds to read, it is the
wrong shot.

**VOICEOVER**

> So here is how it actually works.
>
> Alpaca's free data feed returns zero greeks and no implied volatility. At every
> single strike. So the agent solves Black-Scholes itself, and derives its own delta,
> gamma and theta.
>
> For index options there is no published spot price at all, so it recovers the forward
> from put-call parity, out of the option chain itself.
>
> And because real markets are not lognormal, it counts how often price actually
> breached, across six hundred and sixty eight real trading sessions, and it sizes on
> whichever of the two numbers is worse.
>
> Every order goes out through the Alpaca CLI, so each one is a command you can replay
> by hand. And the MCP server is wired in as the inspection window, behind a proxy that
> physically blocks all eleven tools capable of placing a trade.

---

## 3:25 - 3:45 | The AI, on a leash

**ON SCREEN**

`submission/assets/03-ai-on-a-leash.png`, full frame. Strike through each item in the
"cannot" list as it is spoken.

Then the real journal record from the Hormuz session, with the returned multiplier visible.

**VOICEOVER**

> There is an AI in here. It gets exactly one job: read live headlines, and make the
> position smaller.
>
> It cannot pick a strike. It cannot size a trade. It cannot overrule a risk gate. And
> it cannot enlarge anything, because that clamp is written in code, not asked for
> politely in a prompt.
>
> On its first live session it pulled Strait of Hormuz attacks off the wire and cut the
> position.

---

## 3:45 - 4:10 | The bug

**ON SCREEN**

The fabricated `+$316.00` on screen, large. Hold it one second longer than is comfortable.

Then the one line diff of the settlement fix, then the `journal_correction` record itself
scrolling past in the raw JSONL.

This is the honesty beat. No music under it. Let it be quiet.

**VOICEOVER**

> One more thing, and it is the part I would most want a judge to see.
>
> My dashboard once showed three hundred and sixteen dollars of profit. It never
> happened. A one line bug was settling positions that were still open.
>
> I did not quietly fix it. The deletion, and the reasoning behind it, went into the
> journal permanently.
>
> Because when your dashboard is built from your journal, a journal bug is a published
> lie.

---

## 4:10 - 4:35 | The result

**ON SCREEN**

The live ledger on the site, real, scrolling. Then the four figures as overlays, one at
a time, in the order they are spoken. Land hard on the zero.

Then, in the last few seconds, actually use the page: pick a strike in the price-a-trade
panel and let the gate reject it on camera. That single interaction proves the thing is
operable rather than a report.

**VOICEOVER**

> So here is the account.
>
> Two spreads settled. Seventy one dollars realised. Seven dollars paid getting in. And
> zero dollars paid getting out, because there was no getting out. They expired.
>
> Closed the way everybody else closes, those same two trades return sixty one.
>
> Not paying to exit was worth fourteen percent of the gain.

---

## 4:35 - 4:55 | The close

**ON SCREEN**

Run it live, one unbroken shot, no cuts:

    python -m agent.verify

Let all ten checks print and let the exit code show. Then the site URL and the repo on a
clean card, held long enough to read and type.

Optional and worth it: three seconds of your face for the last line.

**VOICEOVER**

> Every number you just saw re-derives from a committed journal with one command. No API
> key. No account. No network. It runs on every push, and it fails the build if a number
> stops reproducing.
>
> Most agents will tell you what they made.
>
> This one can show you what it paid.

---

## Production notes

**Capture the footage before you record narration.** The market closes at 20:00 UTC, so
the live quote in the hook and the ledger shot have to exist as recordings already. Get
them first, cut them to length, then voice over the picture. Voicing first and then
hunting for footage to fit is how a four minute video becomes a six minute one.

**Every spoken number needs a text overlay.** People do not retain numbers they only
hear. This is the highest value thing an editor can do to this video.

**No music under the measurement, the bug, or the result.** Music under numbers reads as
a sales pitch, and the whole argument of this project is that it is not one. Music is
fine under the solution section and the close.

**Pace.** Around 155 words per minute, which is slower than feels natural in the room.
Leave a full beat of silence after "zero" at 0:22, after "It is the trade" at 1:05, and
after "a published lie" at 4:10. Those three pauses are doing real work.

**Screen recording.** 1920x1080, 60fps if your capture allows it. Terminal font at 18pt
or larger, because a judge may watch this in a browser tab at half size on a laptop. Use
the light theme on the site: it is the mode the design was built for and it survives
compression better.

**What to cut if you run long,** in this order: the MCP proxy line at 3:25, then the
put-call parity beat, then the Hormuz example. Do not cut the hook, the question at
1:05, the bug, or the zero at 4:10. Those four carry the argument.

**Title and description.** Lead the title with the misconception, not the project name.
"What it costs to get out of an options trade" pulls better than "HALFSPREAD demo". Put
the live site and the repo in the first two lines of the description.
