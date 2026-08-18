# Does a good private equity fund predict a good successor?

**Answer, in one line: yes, and the reason the earlier version of this study
said otherwise is the finding.** The headline estimate is a persistence
coefficient of 0.344 with a 95% confidence interval of [0.168, 0.521] and a
wild cluster bootstrap p of 0.004, on 220 fund pairs drawn from 116 families.

An earlier version of this study used one pension plan, had 65 pairs across 39
families, estimated β = 0.214 and could not reject zero. It also computed, in
advance, that a design with 39 families had a minimum detectable effect of
0.43 and about 19% power at the coefficient it was estimating — so a null was
the likely outcome whatever the truth. Adding a second plan raised the design
to 116 families, dropped the minimum detectable effect to 0.283, and the same
estimator on the same specification now rejects zero. The point estimate moved
by less than one standard error. **The precision moved; the finding was a
power problem, and it was diagnosed as one before the data arrived to fix it.**

## What is estimated

    y_{i,k} = α + β·y_{i,k−1} + γ'X_{i,k} + δ_v + u_{i,k}

`y` is log TVPI, `i` a fund family, `k` the fund's number within that family,
`δ_v` a vintage fixed effect. β is the object of interest: how much of a
predecessor fund's performance carries into the next fund.

**The unit is the fund family, not the firm.** Blackstone Capital Partners
V–IX is one family; Blackstone Tactical Opportunities is another, run by a
different team against a different mandate. Pooling everything a firm manages
would credit a buyout team with a credit team's results. This follows Kaplan
and Schoar (2005), and it is the most consequential modelling choice here;
`data/firm_overrides.csv` records all 99 merge decisions by hand, each with a
reason and a confidence.

## Data and sample

Two US public pension plans, both publishing under statutory disclosure rules.

CalPERS publishes its private equity programme as an HTML table, 462 rows as
of the quarter ending 30 September 2025, covering **active partnerships only**.
Oregon PERS publishes the same shape as quarterly PDFs and does not remove
funds that have wound up; 18 quarters back to March 2021 are archived here, and
the March 2026 file carries 453 funds going back to vintage 1981.

The two plans are not interchangeable, and the difference is the reason for
pooling rather than a nuisance:

| | funds | earliest vintage | vintages before 2000 | median vintage | flagged "not meaningful" |
|---|---|---|---|---|---|
| CalPERS | 462 | 1998 | 1 | 2021 | 43% |
| Oregon | 453 | 1981 | 68 | 2011 | 9% |

CalPERS alone is a table of mostly young funds carrying manager valuations
rather than realisations. Oregon supplies the old, realised half of the sample
that CalPERS structurally cannot.

The funnel from published rows to usable observations:

| step | n |
|---|---|
| rows published by both plans | 915 |
| funds held by both plans, collapsed | 61 |
| after share-class deduplication | 844 |
| funds with a computable TVPI | 839 |
| distinct fund families | 513 |
| families with 2+ funds | 167 |
| lagged pairs | 326 |
| of which adjacent (fund k → k+1) | 270 |
| **mature and adjacent — the estimation sample** | **220** |

Three steps deserve a sentence. **Cross-plan collapsing** matches on
(family, fund number) — not on fund name, because the plans spell the same
fund differently often enough that a name key finds no overlap at all — and
keeps the CalPERS report where both plans hold a fund. That rule is fixed in
`PLAN_PRIORITY` so the result cannot depend on concat order, and it barely
matters: the two plans' log TVPIs correlate at 0.986. **Deduplication**
collapses rows like "Bridgepoint Europe III 'C'" and "III 'D'", one fund
reported twice, and sums their capital; it runs after cross-plan collapsing,
because reversing the order would add CalPERS' and Oregon's stakes in the same
partnership together and invent a fund twice the size. The drop from 326 pairs
to 270 is **adjacency**: a single LP holds an arbitrary subset of any series,
so without it the regression treats a 2007 fund as the immediate predecessor
of a 2021 one.

## Results

All standard errors cluster on family. Every row carries a wild cluster
bootstrap p-value beside the analytic one.

| specification | β | SE | 95% CI | p | p (boot) | n |
|---|---|---|---|---|---|---|
| 1. All funds, vintage FE | 0.420 | 0.068 | [0.288, 0.553] | 0.000 | 0.000 | 326 |
| 2. Mature only, vintage FE | 0.414 | 0.069 | [0.279, 0.549] | 0.000 | 0.000 | 266 |
| **3. Mature, adjacent only — headline** | **0.344** | **0.090** | **[0.168, 0.521]** | 0.000 | **0.004** | **220** |
| 4. + log commitment | 0.343 | 0.090 | [0.166, 0.520] | 0.000 | 0.003 | 220 |
| 5. + fund number | 0.346 | 0.091 | [0.167, 0.525] | 0.000 | 0.005 | 220 |
| 6. Excluding vintage anomalies | 0.344 | 0.090 | [0.168, 0.521] | 0.000 | 0.004 | 220 |
| 7. Dependent = net IRR | 0.148 | 0.063 | [0.026, 0.271] | 0.018 | 0.044 | 217 |
| 3s. Headline, clustered on sponsor | 0.344 | 0.091 | [0.166, 0.523] | 0.000 | 0.003 | 220 |
| 8. Winsorised 5/95 | 0.413 | 0.060 | [0.295, 0.531] | 0.000 | 0.000 | 220 |
| 9. Families with 3+ funds | 0.370 | 0.084 | [0.205, 0.534] | 0.000 | 0.000 | 166 |

**Row 3 is the headline** because adjacency is what makes β the LP's actual
decision problem: fund k has just been raised, fund k+1 is being marketed, and
the question is whether the first tells you anything about the second.

β still falls as the specification tightens, 0.420 → 0.414 → 0.344, exactly as
it did in the one-plan version. What changed is that it no longer falls
through zero on the way. Row 6 is identical to row 3 by construction:
deduplication keeps the earliest reported vintage, which already discarded
every mis-stamped date, so "excluding anomalies" excludes nothing. It is kept
because that is informative.

Row 7 is the weakest row and is reported as such. Net IRR in levels gives
0.148. IRR is not a linear function of the multiple, is sensitive to the
timing of early distributions, and Oregon's own report says its IRRs "SHOULD
NOT be used to assess the investment success of a partnership". The row
survives the null but at a much smaller magnitude, and it is the one result a
reader should discount.

## Where the estimate comes from

Pooling could have moved β for two very different reasons. Either the estimate
was always around 0.3 and 39 families were never enough to separate it from
zero (**precision**), or Oregon's older and mostly realised funds come from a
different regime and the pooled number is a weighted average of two (
**population**). These have opposite implications, and they are separable.

Each plan estimated on its own rows, with the same family definitions:

| split | β | SE | 95% CI | p (boot) | pairs | families |
|---|---|---|---|---|---|---|
| **pooled, both plans** | **0.344** | 0.090 | [0.168, 0.521] | 0.004 | 220 | 116 |
| CalPERS alone | 0.214 | 0.138 | [−0.057, 0.485] | 0.187 | 65 | 39 |
| Oregon alone | 0.358 | 0.112 | [0.139, 0.578] | 0.014 | 170 | 90 |
| vintage before 2000 | 1.151 | 0.377 | [0.414, 1.889] | 0.056 | 16 | 13 |
| vintage 2000 or later | 0.308 | 0.087 | [0.137, 0.479] | 0.007 | 204 | 108 |
| vintage 2010 or later | 0.385 | 0.079 | [0.230, 0.540] | 0.000 | 146 | 85 |
| all funds, incl. immature | 0.384 | 0.095 | [0.199, 0.570] | 0.001 | 270 | 136 |

**The CalPERS-alone row reproduces the earlier study exactly** — 0.2142, SE
0.1381, 65 pairs, 39 families, to four decimal places. That is a reproduction
check on the whole pooling rewrite, not a coincidence: the new pipeline, given
the old data, returns the old answer.

**The answer is precision.** CalPERS alone gives 0.214, Oregon alone 0.358.
They differ by 0.144, which is about one standard error of either. The data
are consistent with one common β that both plans are measuring, and the pooled
estimate is that common value. What separates the two rows is not the number
but the interval: 39 families cannot exclude zero at β ≈ 0.3, and 90 can.

**The pre-2000 row should not be quoted.** β = 1.151 on 16 pairs is above 1,
which would mean performance amplifies across funds rather than decaying, and
no one believes that. It is a small-sample artefact and it is printed here
because leaving it out would be selective. The useful reading is that the
pre-2000 subsample is too small to test the era hypothesis, not that
persistence was explosive.

**Post-2000 persistence is intact here, and that agrees with the literature
rather than contradicting it.** Post-2000 gives 0.308 and post-2010 gives 0.385,
both comfortably off zero.

That needs care, because "persistence died after 2000" is the usual summary of
the modern literature and it is a summary of the wrong specification. Harris,
Jenkinson, Kaplan and Stucke (2020) draw the distinction that matters. Using
**ex post performance** — the predecessor's return as measured today — they
write that they "confirm the previous findings on persistence overall as well
as for pre-2001 and post-2000 funds". Using instead the predecessor's
**interim performance as it stood when the successor was being marketed**, they
find little or no persistence for buyouts. Their post-2000 buyout regression on
previous-fund PME at fundraising gives a coefficient of 0.194, or 0.173 with
controls, which they call economically modest.

**This study estimates the ex post version.** Both plans publish the
predecessor's performance as of the current quarter, not as of the date the
successor closed, so the at-fundraising specification cannot be run on this
data at all. So 0.308 post-2000 belongs beside the finding HJKS confirm, not
beside the one they overturn, and it should not be read as evidence against
them.

Three further cautions. The sample is two LPs' holdings, not the universe. Most
post-2010 funds still carry unrealised marks, and a manager valuing a live fund
has the prior fund's record in view. And this design has power of only 0.13 at
β = 0.1, so it can detect the 0.3 it found but could not distinguish a true 0.1
from zero — it does not have the resolution to adjudicate the low end.

## Inference

With 116 families, cluster-robust asymptotics are on firmer ground than the 39
of the earlier version — Cameron, Gelbach and Miller put the rule of thumb near
40 — but the bootstrap remains the primary inference because cluster sizes are
unbalanced. Simulation confirms the concern is real at small cluster counts: at
20 clusters the analytic p-value rejects a true null 9–13% of the time against
a nominal 5%, while the wild cluster bootstrap holds 4–6%.

**The bootstrap p exceeds the analytic p in every row of the table**, as it did
before. The disagreement always runs the same way: the asymptotic manufactures
persistence rather than hiding it. At this sample size the gap no longer
changes any conclusion — headline analytic 0.0001 against bootstrap 0.0039 —
but the ordering is the same property it always was.

## Robustness

**Family mapping is not driving the result.** Re-running the headline under
three regimes — raw regex stems, high-confidence merges only, all merges —
gives β of 0.368, 0.353 and 0.344. The spread of 0.023 is well inside one
standard error, and it is *smaller* than the 0.055 spread in the one-plan
version. The merges drive sample size: regex-only leaves 189 usable
observations against 220.

**Row 9 is no longer a precision loss.** Restricting to families with three or
more funds gives 0.370 on 166 pairs — slightly above the headline, with a
*smaller* standard error. In the one-plan version this restriction halved β and
nearly doubled the SE, and the write-up said that indicated the sub-sample was
too small to speak rather than that persistence was absent. With 62 families in
the restricted sample instead of 18, that reading is confirmed.

**No single family or year carries it.** Dropping each family in turn spans
[0.309, 0.438] over 116 refits; each vintage, [0.319, 0.432] over 29. No refit
produces β ≤ 0, and no refit even approaches it. The most influential single
exclusion moves β by 0.094.

**It is not a functional-form artefact.** Spearman rank correlation within
vintage is +0.381, permutation p 0.0001 — same sign and magnitude as the
regression coefficient, and invariant to any monotone transform of TVPI.

**The quartile transition matrix now agrees.** Over 205 mature adjacent pairs
the diagonal holds 38.1% of the mass against a within-vintage permutation null
of 25.6%, p = 0.0001. The corners are where the mass is: a bottom-quartile fund
is followed by another bottom-quartile fund 43% of the time, a top-quartile
fund by another top-quartile fund 46%. In the one-plan version this was the
single suggestive result at p = 0.089; it is now the clearest one, and it is
non-parametric.

**Measurement error is small and does not change the estimate.** 43 funds
appear in both plans at the same reporting date, which is a direct read on
reporting noise. Two distinct quantities come out of it and should not be run
together:

- the **cross-plan correlation** of log TVPI — a description of how closely the
  two reports track each other;
- the **reliability ratio** λ = var(true) / (var(true) + var(error)), which is
  what actually divides into β.

For two parallel measurements of the same quantity the correlation *equals* the
reliability ratio, provided the two reports have equal error variance and their
errors are independent of each other and of the truth. The first condition is
plausible; **the second is not**, because both plans receive the same
GP-reported valuation. Their errors share a large common component, which
inflates the correlation above the true reliability. So λ is estimated
separately from the variance of the paired differences rather than read off the
correlation.

Estimated that way on the 36 comparable pairs, **λ = 0.986** (95% CI
[0.963, 0.995]), a 1.014× correction — it moves β by less than a hundredth.

The seven remaining pairs are funds Oregon **sold in the secondary market**,
and they are excluded on principle rather than trimmed as outliers. A sold
position's reported multiple is a realised transaction price with NAV of
exactly zero, while CalPERS still carries the same fund at a live mark; the gap
between them is the secondary discount, which is real economics and not
reporting noise. Oregon says as much in its own footnote — such performance "is
not representative of the performance of that fund if it were held until its
natural liquidation". The separation is stark: median disagreement is 0.82%
among held pairs and 9.94% among sold ones, twelve times larger. Including
them drops λ to 0.944.

Restricting instead to the 22 pairs where the plans also agree on vintage gives
λ = 0.988, the same answer by an independent route.

## What this design could have detected

Power was computed on the actual estimation sample — the real y_lag values,
real vintage dummies, real family sizes — with the outcome rebuilt for a grid
of true coefficients and each replication tested exactly as the headline is
tested, by wild cluster bootstrap at 5%.

| true β | power, 116 families (this study) | power, 39 families (one plan) |
|---|---|---|
| 0.0 | 0.037 | 0.057 |
| 0.1 | 0.130 | 0.067 |
| 0.2 | 0.447 | 0.187 |
| 0.3 | 0.870 | 0.457 |
| 0.4 | 1.000 | 0.723 |
| 0.5 | 1.000 | 0.940 |
| 0.6 | 1.000 | 0.997 |

**The minimum detectable effect at 80% power is β ≈ 0.283, down from 0.43.**
Rejection at β = 0 is 0.037, so the test is correctly sized and the curve is
not flattered by over-rejection. Clustering on sponsor instead of family gives
the same 0.283.

This is the part worth keeping. The one-plan version of this study concluded:

> this design could only ever have detected persistence of the magnitude
> reported before 2000, and had essentially no chance of detecting the
> magnitude the post-2000 literature reports. A null result was close to
> guaranteed regardless of the truth, and that is a fact about 39 clusters
> rather than about private equity.

That was a prediction, and it was testable. The design now has 116 clusters, an
MDE of 0.283, and roughly 93% power at the coefficient it estimates. The null
did not survive. **The earlier null was a statement about the sample, and it
correctly said so at the time.**

One correction to that quotation, since it is reproduced here rather than
quietly reworded: its second clause rested on a misreading of the modern
literature. The post-2000 papers do not report near-zero persistence in the
specification this study runs; they report it in the at-fundraising
specification this study cannot run. The first clause — that 39 clusters could
not detect a Kaplan-Schoar-magnitude effect — is the part that was right, and
it is the part the new sample tested.

One limit is unchanged. At β = 0.1 power is still only 0.13, and at 0.2 it is
0.45. The coefficient HJKS report for the investable, at-fundraising
specification is 0.194 — squarely in the range this design would miss more
often than not. So even with 116 families, this study can speak to ex post
persistence and cannot speak to the version an investor could act on. That is a
limit of the design and of the data, not a finding.

## Limitations

**This measures ex post persistence, not what an investor could act on.**
β relates the successor's return to the predecessor's return *as reported
today*. When the successor was actually being raised, the predecessor was
part-way through its life and its interim number was different — and Harris,
Jenkinson, Kaplan and Stucke (2020) show that swapping final for interim
performance is what kills persistence for post-2000 buyouts. Neither plan
publishes a historical performance series per fund, only the current quarter,
so the investable specification cannot be constructed here. This is the single
largest qualification on the headline: it is the right coefficient for "does
skill persist" and the wrong one for "should I back fund IX".

**Survivorship, reduced but not removed.** CalPERS drops fully exited funds, so
its old vintages are survivors in a specific, non-random sense. Oregon does not,
which is why 68 of the 69 pre-2000 funds in the sample come from Oregon. The
pooled sample is therefore much less survivorship-affected than the one-plan
version, but it is not clean: Oregon's own coverage begins where its reporting
begins.

**The two plans do not flag maturity the same way.** "Not meaningful" is each
plan's own judgement. On their own published tables CalPERS applies it to 43%
of its funds against Oregon's 9%; inside the estimation panel, after the
overlap funds are attributed to CalPERS, Oregon's share falls to 5%. Either way
the maturity filter is looser on the Oregon half. The
unfiltered row is reported above for exactly this reason: it gives 0.384, above
the headline, so the filter is not manufacturing the result.

**Unrealised marks.** Most funds in both tables still carry GP valuations rather
than realisations, and those valuations are known to be smoothed and stale. The
direction is not obvious: smoothing pulls a coefficient toward zero as
measurement error, but a manager who marks the new fund with an eye on the old
one would push it up. The cross-plan comparison measures only the part of the
error where the two plans differ; the shared part cancels and stays invisible.

**Vintage year is measured with error.** The two plans disagree for 14 of 36
shared funds. Simulation on the observed displacement pattern shows the bias is
*downward*, about −14%, so β is a lower bound with respect to this error. That
result reversed the sign of the argument originally written down here; see
`DEVELOPMENT_LOG.md`.

**LP selection.** Only funds these two plans chose to back are observed. Both
are large, sophisticated investors, and the sample is conditioned on a fund
having looked attractive to them beforehand. Nothing in public data fixes this.

**Strategy is unobserved.** Neither plan publishes what strategy a fund
follows, so buyout, venture and credit cannot be separated. Classifying by
keywords in the fund name would be a guess presented as data — "Ares Corporate
Opportunities" and "GSO Energy Partners" are credit funds whose names do not
say so — so the row is left out rather than filled. WSIB publishes a strategy
field and is the obvious next source.

**PME is mostly not computable here, by design.** PME needs dated cash flows;
both plans publish running totals. Flows are recovered by differencing
consecutive snapshots, which only works for funds that had drawn nothing when
the archive starts — 63 funds out of 490, of which 59 still hold about 99% of
their value unsold. That subsample describes managers' valuations against the
market, not realised returns.
