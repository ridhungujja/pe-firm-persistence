# Does a good private equity fund predict a good successor?

**Answer, in one line: not in this sample, and the reason is worth more than
the number.** The headline estimate is a persistence coefficient of 0.214 with
a 95% confidence interval of [−0.057, 0.485]. It includes zero.

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
`data/firm_overrides.csv` records all 70 merge decisions by hand, each with a
reason and a confidence.

## Data and sample

CalPERS publishes its private equity programme quarterly as an HTML table,
462 rows as of the quarter ending 30 September 2025. Oregon PERS publishes the
same shape as quarterly PDFs; 18 quarters back to March 2021 are archived here
and used for the cross-plan work and for PME.

The funnel from published rows to usable observations:

| step | n |
|---|---|
| rows published by CalPERS | 462 |
| after share-class deduplication | 462 |
| funds with a computable TVPI | 459 |
| funds in families with 2+ funds | 204 |
| lagged pairs | 129 |
| of which adjacent (fund k → k+1) | 100 |
| **mature and adjacent — the estimation sample** | **65** |

Two steps deserve a sentence. Deduplication collapses rows like "Bridgepoint
Europe III 'C'" and "III 'D'", one fund reported twice; counting them
separately invents a sequence step and double-counts capital. The drop from
129 pairs to 100 is adjacency: a single LP holds an arbitrary subset of any
series, so without it the regression treats a 2007 fund as the immediate
predecessor of a 2021 one.

## Results

All standard errors cluster on family. Every row carries a wild cluster
bootstrap p-value beside the analytic one.

| specification | β | SE | 95% CI | p | p (boot) | n |
|---|---|---|---|---|---|---|
| 1. All funds, vintage FE | 0.390 | 0.139 | [0.118, 0.663] | 0.005 | 0.006 | 129 |
| 2. Mature only, vintage FE | 0.248 | 0.109 | [0.035, 0.461] | 0.023 | 0.045 | 87 |
| **3. Mature, adjacent only — headline** | **0.214** | **0.138** | **[−0.057, 0.485]** | 0.121 | **0.187** | **65** |
| 4. + log commitment | 0.215 | 0.145 | [−0.069, 0.500] | 0.138 | 0.223 | 65 |
| 5. + fund number | 0.193 | 0.136 | [−0.073, 0.459] | 0.156 | 0.212 | 65 |
| 6. Excluding vintage anomalies | 0.214 | 0.138 | [−0.057, 0.485] | 0.121 | 0.187 | 65 |
| 7. Dependent = net IRR | 0.123 | 0.110 | [−0.093, 0.339] | 0.263 | 0.320 | 63 |
| 8. Winsorised 5/95 | 0.222 | 0.158 | [−0.087, 0.532] | 0.158 | 0.219 | 65 |
| 9. Families with 3+ funds | 0.148 | 0.211 | [−0.265, 0.562] | 0.482 | 0.696 | 44 |

**Row 3 is the headline** because adjacency is what makes β the LP's actual
decision problem: fund k has just been raised, fund k+1 is being marketed, and
the question is whether the first tells you anything about the second. Row 1
answers a looser question — whether any earlier fund predicts any later one —
and it is the only row that looks decisive. That ordering is the finding: β
falls monotonically as the specification tightens, 0.390 → 0.248 → 0.214, and
significance goes with it.

Row 6 is identical to row 3 by construction: deduplication keeps the earliest
reported vintage, which already discarded every mis-stamped date, so
"excluding anomalies" excludes nothing. It is kept because that is informative.

## Inference

With 39 families, cluster-robust asymptotics are borderline — Cameron, Gelbach
and Miller put the rule of thumb near 40 — and the distortion is worst when
cluster sizes are unbalanced, which they are here. Simulation confirms it: at
20 clusters the analytic p-value rejects a true null 9–13% of the time against
a nominal 5%, while the wild cluster bootstrap holds 4–6%.

**The bootstrap p exceeds the analytic p in every row of the table.** Row 2 is
the clean illustration — analytic 0.023, bootstrap 0.045 — and in the
regex-only mapping regime the gap is starker still, 0.037 against 0.129. Where
they disagree, the bootstrap is the one to believe, and the disagreement always
runs the same way: the asymptotic manufactures persistence rather than hiding
it.

## Robustness

**Family mapping is not driving the result.** Re-running the headline under
three regimes — raw regex stems, high-confidence merges only, all merges — gives
β of 0.270, 0.245 and 0.214. The spread of 0.055 is well inside one standard
error. The merges do drive sample size: regex-only leaves 40 usable
observations against 65.

**Row 9 is a precision loss, not a finding.** Restricting to families with
three or more funds halves β to 0.148, which invites reading it as evidence
against persistence. It is not. The restriction drops 21 of 39 families and
nearly doubles the standard error, from 0.138 to 0.211, so the interval
[−0.265, 0.562] is wider than the unrestricted one in both directions. The row
says the sub-sample is too small to speak, not that persistence is absent in
it.

**No single family or year carries it.** Dropping each family in turn spans
[0.138, 0.281] over 39 refits; each vintage, [0.118, 0.308] over 17. No refit
produces β ≤ 0. The most influential exclusion is vintage 2008 (β → 0.118).

**It is not a functional-form artefact.** Spearman rank correlation within
vintage is +0.230, permutation p 0.239 — same sign and magnitude, and
invariant to any monotone transform of TVPI.

**The quartile transition matrix is the one suggestive result.** Over 47 mature
adjacent pairs the diagonal holds 36.2% of the mass against a within-vintage
permutation null of 25.9%, p = 0.089. Suggestive, not significant, and on cell
counts as small as six funds.

**Measurement error is small and does not rescue the estimate.** 43 funds
appear in both plans at the same reporting date, which is a direct read on
reporting noise. Two distinct quantities come out of it and should not be run
together:

- the **cross-plan correlation** of log TVPI, 0.944 — a description of how
  closely the two reports track each other;
- the **reliability ratio** λ = var(true) / (var(true) + var(error)), which is
  what actually divides into β.

They coincide numerically here, and not by accident: for two parallel
measurements of the same quantity the correlation *equals* the reliability
ratio, provided the two reports have equal error variance and their errors are
independent of each other and of the truth. The first condition is plausible;
**the second is not**, because both plans receive the same GP-reported
valuation. Their errors share a large common component, which inflates the
correlation above the true reliability. So the correlation is reported as a
description and λ is estimated separately from the variance of the paired
differences, rather than read off the correlation.

Estimated that way on the 36 comparable pairs, **λ = 0.986** (95% CI
[0.963, 0.995]), correcting β from 0.214 to 0.217 — a 1.014× adjustment.

The seven remaining pairs are funds Oregon **sold in the secondary market**,
and they are excluded on principle rather than trimmed as outliers. A sold
position's reported multiple is a realised transaction price with NAV of
exactly zero, while CalPERS still carries the same fund at a live mark; the
gap between them is the secondary discount, which is real economics and not
reporting noise. Oregon says as much in its own footnote — such performance
"is not representative of the performance of that fund if it were held until
its natural liquidation". The separation is stark: median disagreement is
0.82% among held pairs and 9.94% among sold ones, twelve times larger.
Including them drops λ to 0.944.

Restricting instead to the 22 pairs where the plans also agree on vintage
gives λ = 0.988, the same answer by an independent route.

## What this design could have detected

An imprecise null invites the reader to conclude the study was merely
inconclusive. The sharper question is what size of persistence this sample
*could* have found. Power was computed on the actual estimation sample — the
real y_lag values, real vintage dummies, real family sizes — with the outcome
rebuilt for a grid of true coefficients and each replication tested exactly as
the headline is tested, by wild cluster bootstrap at 5%.

| true β | power (family clusters) | power (sponsor clusters) |
|---|---|---|
| 0.0 | 0.057 | 0.057 |
| 0.1 | 0.067 | 0.090 |
| 0.2 | 0.187 | 0.257 |
| 0.3 | 0.457 | 0.470 |
| 0.4 | 0.723 | 0.743 |
| 0.5 | 0.940 | 0.933 |
| 0.6 | 0.997 | 0.997 |

**The minimum detectable effect at 80% power is β ≈ 0.43.** Rejection at β = 0
is 0.057, so the test is correctly sized and the curve is not flattered by
over-rejection.

Two consequences follow, and they matter more than the point estimate.

**At the coefficient actually estimated, power was about 19%.** A true β of
0.214 would have been detected roughly one time in five. Failing to reject was
the most likely outcome even if that value is exactly right.

**The detectable effect is a Kaplan-Schoar-era magnitude, not a modern one.**
Kaplan and Schoar (2005) reported persistence coefficients on log performance
in the region of 0.4–0.6 for pre-2000 funds. The later literature — Harris,
Jenkinson and Kaplan (2014), Braun, Jenkinson and Stoff (2017) — finds the
effect much weaker after the early 2000s, generally well below 0.15 and often
not distinguishable from zero. Against that, this design has power of roughly
0.07–0.09.

So the honest summary is not "we found no persistence". It is: **this design
could only ever have detected persistence of the magnitude reported before
2000, and had essentially no chance of detecting the magnitude the post-2000
literature reports.** A null result was close to guaranteed regardless of the
truth, and that is a fact about 39 clusters rather than about private equity.

These literature figures are approximate and not strictly comparable — the
studies differ in dependent variable, lag definition and sample — so they are
used to place an order of magnitude, not to test against a specific number.

## Limitations, in priority order

1. **Small n dominates everything.** 65 pairs, 39 families, 33 sponsors. The
   interval is wide enough to contain both the Kaplan-Schoar-era estimates and
   zero. This is not a precise null; it is an imprecise estimate, and the
   power calculation above quantifies how imprecise: nothing below β ≈ 0.43
   was reliably detectable.
2. **Active partnerships only.** CalPERS removes fully exited funds, so old
   vintages that survive are those still holding unsold assets. Direction of
   bias unknown but not ignorable: a pre-2010 fund appears here only if it is
   still open twenty years in.
3. **Unrealised marks.** Most funds are 2020s vintages carrying GP valuations
   rather than realisations. Interim NAVs are stale and smoothed — classical
   measurement error in the regressor, which **attenuates β toward zero**. The
   overlap correction bounds only the part that differs between two LPs of one
   fund; the stale-marks component is common to both reports and cancels in
   the difference, so true attenuation is larger by an unknown amount.
4. **The vintage label itself carries error.** 18 of 43 cross-plan matches
   disagree on vintage year, always with CalPERS dating equal or later
   (+1 in 14 cases, +2 in 4). Vintage fixed effects are the main control in
   every specification, so roughly 40% of funds are being assigned to a
   neighbouring year's effect.
5. **LP selection.** Only funds CalPERS chose to back are observed, so the
   universe is conditioned on ex-ante attractiveness to a large institution.
   Not fixable with public data.
6. **Survivorship on the regressor is benign; on the outcome it is not.**
   Simulation shows truncating on the *predecessor* leaves E[y | y_lag] intact
   and OLS consistent, while censoring the *outcome* cuts β by 37%. Informal
   talk about "survivorship bias in PE data" rarely distinguishes these, and
   the distinction determines whether the estimate is usable.

## Conclusion

This sample cannot distinguish persistence from noise. β = 0.214 with a 95%
interval of [−0.057, 0.485] is consistent with meaningful persistence and
consistent with none, and no robustness exercise narrows it.

That is a finding rather than a failure, for two reasons. First, it is what the
later literature predicts: Kaplan and Schoar (2005) found strong persistence
pre-2000; Harris, Jenkinson and Kaplan (2014) and Braun, Jenkinson and Stoff
(2017) found it substantially weaker afterwards. A sample dominated by
post-2010 vintages landing on an imprecise 0.21 sits in that arc. Second, the
specification ordering is informative in itself: the same data yields a
decisive-looking 0.390 if you pool non-adjacent pairs and keep immature funds.
The gap between that and 0.214 is the methodological content of this project,
and it is why the headline row is the restrictive one.

The single change that would most improve this estimate is more families, not
more funds — precision here is bounded by 39 clusters. Adding CalSTRS or
Washington State, both of which publish the same shape of data, is the obvious
next step.
