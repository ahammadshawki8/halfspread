/* HALFSPREAD decision engine, in the browser.
 *
 * This is a direct port of agent/pricing.py, agent/cost.py and agent/risk.py.
 * It exists so the page can price a trade a visitor invents, against the same
 * live chain the desk is trading, through the same arithmetic and the same
 * gates. A dashboard that only reports what already happened cannot be told
 * apart from a screenshot of one.
 *
 * Anything this file computes is reproducible by running the Python.
 */
(function (global) {
  "use strict";

  // ---- Black-Scholes ------------------------------------------------------
  const SQRT2 = Math.SQRT2, SQRT2PI = Math.sqrt(2 * Math.PI);

  function erf(x) {
    // Abramowitz and Stegun 7.1.26, accurate to about 1.5e-7.
    const s = x < 0 ? -1 : 1; x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t
      - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  const ncdf = x => 0.5 * (1 + erf(x / SQRT2));
  const npdf = x => Math.exp(-0.5 * x * x) / SQRT2PI;

  const MIN_T = 1 / (365 * 24 * 60);

  function d1d2(S, K, T, r, sig) {
    const v = sig * Math.sqrt(T);
    const a = (Math.log(S / K) + (r + 0.5 * sig * sig) * T) / v;
    return [a, a - v];
  }

  function bsPrice(S, K, T, r, sig, kind) {
    T = Math.max(T, MIN_T);
    if (sig <= 1e-9 || S <= 0 || K <= 0) {
      const intr = kind === "put" ? K - S : S - K;
      return Math.max(intr, 0) * Math.exp(-r * T);
    }
    const [a, b] = d1d2(S, K, T, r, sig), disc = Math.exp(-r * T);
    return kind === "put"
      ? K * disc * ncdf(-b) - S * ncdf(-a)
      : S * ncdf(a) - K * disc * ncdf(b);
  }

  function impliedVol(price, S, K, T, r, kind) {
    T = Math.max(T, MIN_T);
    if (!(price > 0) || S <= 0 || K <= 0) return null;
    const disc = Math.exp(-r * T);
    const intrinsic = Math.max(kind === "put" ? K - S : S - K, 0) * disc;
    const upper = kind === "put" ? K * disc : S;
    if (price <= intrinsic + 1e-9 || price >= upper - 1e-9) return null;
    let lo = 1e-4, hi = 6;
    if (bsPrice(S, K, T, r, hi, kind) < price) return null;
    for (let i = 0; i < 80 && hi - lo > 1e-7; i++) {
      const m = 0.5 * (lo + hi);
      if (bsPrice(S, K, T, r, m, kind) < price) lo = m; else hi = m;
    }
    return 0.5 * (lo + hi);
  }

  function greeks(S, K, T, r, sig, kind) {
    T = Math.max(T, MIN_T);
    if (sig <= 1e-9) return { delta: 0, gamma: 0, theta: 0, vega: 0 };
    const [a, b] = d1d2(S, K, T, r, sig);
    const sq = Math.sqrt(T), disc = Math.exp(-r * T), pdf = npdf(a);
    const delta = kind === "put" ? ncdf(a) - 1 : ncdf(a);
    const thetaYr = kind === "put"
      ? -(S * pdf * sig) / (2 * sq) + r * K * disc * ncdf(-b)
      : -(S * pdf * sig) / (2 * sq) - r * K * disc * ncdf(b);
    return {
      delta, gamma: pdf / (S * sig * sq),
      theta: thetaYr / 365, vega: S * pdf * sq * 0.01,
    };
  }

  function probItm(S, K, T, r, sig, kind) {
    T = Math.max(T, MIN_T);
    if (sig <= 1e-9) return ((kind === "put") === (S < K)) ? 1 : 0;
    const [, b] = d1d2(S, K, T, r, sig);
    return kind === "put" ? ncdf(-b) : ncdf(b);
  }

  // Undiscounted E[max(K - S_T, 0)] with the terminal mean at the forward.
  function expectedPut(K, F, T, sig) {
    T = Math.max(T, MIN_T);
    if (sig <= 1e-9 || F <= 0 || K <= 0) return Math.max(K - F, 0);
    const v = sig * Math.sqrt(T);
    const a = (Math.log(F / K) + 0.5 * v * v) / v, b = a - v;
    return K * ncdf(-b) - F * ncdf(-a);
  }

  // ---- measured breach probability ---------------------------------------
  function empiricalBreach(samples, spot, strike, hourET) {
    if (!samples || spot <= 0 || strike <= 0) return null;
    let key = String(hourET);
    if (!samples[key]) {
      const have = Object.keys(samples).map(Number).sort((x, y) => x - y);
      if (!have.length) return null;
      key = String(have.reduce((p, c) =>
        Math.abs(c - hourET) < Math.abs(p - hourET) ? c : p));
    }
    const vals = samples[key], needed = Math.log(strike / spot);
    let hits = 0;
    for (const v of vals) if (v <= needed) hits++;
    return { prob: hits / vals.length, n: vals.length };
  }

  // ---- the trade ----------------------------------------------------------
  const MULT = 100;

  function yearFraction(expiry, now) {
    // Options stop trading at 16:00 New York on the expiry date. -4 in
    // September, which is the whole window this desk operates in.
    const close = Date.parse(expiry + "T16:00:00-04:00");
    return Math.max((close - (now || Date.now())) / (365 * 24 * 3600 * 1000), MIN_T);
  }

  function nowHourET(now) {
    const d = new Date(now || Date.now());
    return Number(new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", hour: "numeric", hour12: false,
    }).format(d));
  }

  /* Price one put credit spread exactly as agent/cost.py does.
   * chain: {spot, puts:[{k,b,a}]}  gates: the published thresholds. */
  function priceSpread(chain, shortK, width, gates, samples, expiry, qty, now) {
    const by = new Map(chain.puts.map(p => [p.k, p]));
    const S = chain.spot, longK = shortK - width;
    const sh = by.get(shortK), ln = by.get(longK);
    if (!sh || !ln) return { ok: false, why: "no two-sided quote at one of those strikes" };

    const shMid = (sh.b + sh.a) / 2, lnMid = (ln.b + ln.a) / 2;
    const creditMid = shMid - lnMid;
    const creditFill = sh.b - ln.a;              // sell the bid, buy the ask
    const entryCost = creditMid - creditFill;
    const exitNow = (sh.a - shMid) + (lnMid - ln.b);

    if (!(creditFill > 0)) return { ok: false, why: "no credit available after crossing both legs" };
    if (creditFill >= width) return { ok: false, why: "credit exceeds the width" };

    const r = gates.risk_free_rate, T = yearFraction(expiry, now), F = S * Math.exp(r * T);
    const iv = impliedVol(shMid, S, shortK, T, r, "put");
    if (iv == null) return { ok: false, why: "the short leg does not solve for an implied volatility" };

    const sig = iv * (1 - gates.vrp_haircut);
    const lossIfHeld = (expectedPut(shortK, F, T, sig) - expectedPut(longK, F, T, sig)) * MULT;
    const maxProfit = creditFill * MULT, maxLoss = (width - creditFill) * MULT;
    const netEv = creditFill * MULT - lossIfHeld;
    const netEvAtMid = creditMid * MULT - lossIfHeld;

    const modelBreach = probItm(S, shortK, T, r, sig, "put");
    const emp = empiricalBreach(samples, S, shortK, nowHourET(now));
    const breach = emp ? Math.max(modelBreach, emp.prob) : modelBreach;
    const g = greeks(S, shortK, T, r, iv, "put");
    const probWin = 1 - breach;

    // The gates, in the order agent/cost.py applies them.
    const checks = [
      ["short strike is out of the money", shortK < S,
        `${shortK} against a reference of ${S.toFixed(2)}`],
      ["win probability clears the floor", probWin >= gates.min_prob_win,
        `${(probWin * 100).toFixed(1)}% against a floor of ${(gates.min_prob_win * 100).toFixed(0)}%`],
      ["credit is a sane share of the width", creditFill / width >= gates.min_credit_to_width
        && creditFill / width <= gates.max_credit_to_width,
        `${((creditFill / width) * 100).toFixed(1)}% of width, wanted ${(gates.min_credit_to_width * 100).toFixed(0)} to ${(gates.max_credit_to_width * 100).toFixed(0)}%`],
      ["credit is worth collecting", creditFill >= gates.min_credit_fill,
        `${creditFill.toFixed(2)} against a floor of ${gates.min_credit_fill.toFixed(2)}`],
      ["risk is large enough to matter", maxLoss >= gates.min_max_loss,
        `$${maxLoss.toFixed(0)} against a floor of $${gates.min_max_loss.toFixed(0)}`],
      ["risk is inside the per-position cap", maxLoss <= gates.max_loss_per_position,
        `$${maxLoss.toFixed(0)} against a cap of $${gates.max_loss_per_position.toFixed(0)}`],
      ["expected value survives the measured cost", netEv >= gates.min_net_ev,
        `$${netEv.toFixed(2)} per contract against a floor of $${gates.min_net_ev.toFixed(2)}`],
    ];
    const failed = checks.filter(c => !c[1]);

    const n = Math.max(1, Math.floor(Math.min(
      gates.max_loss_per_day, gates.max_loss_per_position) / Math.max(maxLoss, 1)));
    const sized = qty || n;

    return {
      ok: true, shortK, longK, width, spot: S, expiry,
      shortQuote: sh, longQuote: ln,
      creditMid, creditFill, entryCost: entryCost * MULT,
      entryCostPctOfCredit: creditMid > 0 ? (entryCost / creditMid) * 100 : Infinity,
      exitCostNow: exitNow * MULT,
      maxProfit, maxLoss, netEv, netEvAtMid,
      returnOnRisk: maxLoss > 0 ? netEv / maxLoss : 0,
      iv, sigmaUsed: sig, delta: g.delta, theta: g.theta,
      probWin, modelWin: 1 - modelBreach,
      empiricalWin: emp ? 1 - emp.prob : null, empiricalN: emp ? emp.n : 0,
      boundBy: (emp && emp.prob > modelBreach) ? "measured history" : "model",
      hoursToExpiry: T * 365 * 24,
      checks, failed, admissible: failed.length === 0,
      suggestedQty: sized,
      totalRisk: sized * maxLoss, totalNetEv: sized * netEv,
    };
  }

  /* Rank every strike and width the chain supports, the way the agent does. */
  function rankAll(chain, gates, samples, expiry, widths, now) {
    const out = [];
    for (const p of chain.puts) {
      for (const w of widths) {
        const res = priceSpread(chain, p.k, w, gates, samples, expiry, null, now);
        if (res.ok) out.push(res);
      }
    }
    out.sort((a, b) => b.returnOnRisk - a.returnOnRisk);
    return out;
  }

  global.HS = { bsPrice, impliedVol, greeks, probItm, expectedPut,
                empiricalBreach, priceSpread, rankAll, yearFraction, nowHourET };
})(window);
