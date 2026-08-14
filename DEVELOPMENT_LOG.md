# Development log

Design decisions, things that turned out to be wrong, and findings that do not
belong in the write-up but would cost someone a day to rediscover. Organised by
topic rather than chronologically.

---

## Family matching

### The regex fails in one direction only

`normalise_firm_ids` strips one trailing entity token and then a trailing
numeral. The numeral only disappears when it is the last thing in the name, so
anything following it — a share class `(A)`, a feeder tag `L.P.1`, a domicile
`SCSp`, a spelled-out `Limited Partnership` — leaves the number welded into the
stem and scatters one series across several stems.

Measured on the CalPERS table: templated stems give 383 families; hand-checked
merges give 330. **Usable lagged pairs go from 79 to 129.** The failure is
essentially never in the other direction — the rule does not remove strategy
words, so it cannot pool Silver Lake Partners with Silver Lake Technology
Investors. Two detectors were run for over-merges (members disagreeing after
numeral removal; sidecar tokens mixed with flagship names) and both came back
empty.

Consequence for design: corrections live in `data/firm_overrides.csv` as an
explicit stem→family lookup, never as a looser regex. No pattern distinguishes
a share class from a strategy suffix, which is exactly why the decisions are
recorded by hand with a stated reason and confidence. `keep_separate` rows are
no-ops that record a family was inspected and deliberately left alone, so a
later pass does not "helpfully" merge it.

### Splits invisible to prefix similarity

The first wave of splits was findable by looking for a clean stem plus numbered
fragments — CVC, Permira, Welsh Carson/WCAS, Insight's 2019 rename. The second
wave was not, because **every** vintage carried a class suffix so no unnumbered
stem existed to anchor on:

- **Advent International GPE** — `V-D, VI-A, VII-C, VIII-B, IX, X` as six
  separate stems, six apparent first-time funds, one clean 2005→2022 series.
- **Cerberus CAL II/III/IV Partners** — the number sits *before* "Partners",
  and the rule strips only one trailing token, so `<name> <number> Partners`
  never collapses.
- TowerBrook Investors (onshore feeder tags), Forbion (Dutch `Cooperatief
  U.A.`), EQT (`(No.2) USD SCSp`), Summit, TA.

### Traps: same prefix, different answer

Permira Europe merges into the Permira flagship; Permira Growth Opportunities
does not. CVC European Equity merges; CVC Asia does not. Lightspeed XIV-A/XV-A
(Inception) and XIV-B/XV-B (Ignite) are two series, not one. General Catalyst
XII splits into Creation / Endurance / Health Assurance / Ignition, and only
Health Assurance has a predecessor to pair with.

### The strip class is `[IVXLC]`, not the roman digits

A diagnostic over 459 CalPERS and 490 Oregon names found 148 suspect stems, 11
with a share-class letter eaten as a numeral. The important correction: because
the character class is `[IVXLC]`, **C, I, L, V and X are at risk and D and M
are not**, despite being roman digits. `BDC IV D LP` keeps its D and strands
the number for a different reason — the trailing letter blocks the strip rather
than being consumed by it. Parametrised tests pin both halves.

All 22 CalPERS stems that still carry a stranded number and no override are
singletons, so no further merge would create an observation. The Wigmore Street
vehicles share a de-numbered form but are co-invest sleeves of four *different*
Bridgepoint funds, not one series; merging them would manufacture a sequence.

### Sponsor sits above family

Two families under one firm share an investment committee and deal flow, so
their residuals are not independent. `derive_sponsor_ids` takes the family's
leading token (stripping a leading "The"), with hand-recorded corrections in
`data/sponsor_overrides.csv` for the four ways that rule fails:

1. Two firms sharing a first word — General Atlantic and General Catalyst; The
   Rise Fund and The Veritas Capital Fund once "The" is stripped.
2. Programme labels that are not manager names — "California Asia Investors",
   "CalPERS Corporate Partners" are named for the LP and run by different
   outside managers.
3. Co-invest vehicles named after the street — Wigmore Street and BDC are both
   Bridgepoint.
4. Correct grouping but a poor label — Silver Lake derives to `SILVER`.

Effect on the estimate is small: SE 0.138 → 0.140, 39 families → 33 sponsors,
because only 6 of 39 headline families share a sponsor. Across the whole panel
the compression is much larger, 330 → 216.

---

## Data integrity

### Share classes are one fund, not two

"Bridgepoint Europe III 'C'" and "III 'D'" are one partnership reported twice.
Counting them separately invents a sequence step and double-counts capital.
Dedup groups on (family, fund number), sums cash columns, and takes the
**earliest** vintage — which also repairs the case where one class is stamped
with the LP's commitment date instead of the fund's vintage. Three funds
collapse from six rows.

`net_irr` is set to NaN on every collapsed row and never averaged. An IRR is
the root of a polynomial in dated cash flows; a weighted mean of two class IRRs
is not the IRR of the combined position and can sit outside the range of its
inputs. Bridgepoint III's two classes reported 0.042 and 0.024.

### Vintage anomalies: flag, never correct

Two independent checks — fund-number order contradicting vintage order, and
residuals beyond three years from the family's own fundraising cadence. The
diagnostic reports zero anomalies on the current data, but only because dedup's
earliest-vintage rule already absorbed all four Bridgepoint mis-stamps; running
it on pre-dedup data catches every one. Nothing is ever rewritten: a vintage is
either right or unknown, and a fabricated replacement would enter the fixed
effects indistinguishable from a reported one.

### `sequence` is not the fund's number

`sequence` ranks a family's funds; `fund_number` is the fund's own designator.
They differ whenever a plan holds a subset of a series, which is the normal
case. Without the distinction the regression treats a 2007 fund as the
immediate predecessor of a 2021 one. `max_gap=1` restricts to genuinely
adjacent funds and is what makes the headline row the LP's actual decision
problem. It costs 35 of 100 adjacent-eligible pairs.

### The CalPERS reporting date was the download date

`load()` stamped `as_of` with `pd.Timestamp.today()` because the table has no
date column. The date is in the page's prose — "As of September 30, 2025" — and
was never read. The snapshot therefore claimed a date nearly a year after the
quarter it describes, which makes cross-plan alignment impossible: any
comparison would have measured eleven months of NAV growth and called it
reporting error. `parse_as_of()` now reads it and `load()` raises rather than
falling back to today.

---

## Sources

### Oregon URLs cannot be templated

Oregon has used at least five naming conventions for the same quarterly report
and files at least one under the folder for the wrong year. Probing the current
pattern across 2014–2026 (52 URLs) found 8 reports; reading the links off the
Treasury holdings page found **18**, spanning 2021-03-31 to 2026-03-31. The
fetcher discovers rather than constructs, and takes the year from the filename.
It returns an empty list if the page is reorganised rather than emitting URLs
that 404.

### Vintage year means different things to the two plans

Neither plan defines the term. Oregon's PDF footnotes only secondary sales and
"NM"; CalPERS mentions vintage in passing and never defines it, and its
methodology and glossary pages return 404/403.

Tested empirically instead. For 63 Oregon funds observed from inception — zero
paid-in at first appearance, so the first call is inside the window and can be
dated by differencing — Oregon's first call is *later* than its reported
vintage for 32 of them and **never earlier**. So Oregon does not report its own
first call; the field behaves like the fund's own vintage.

CalPERS is never earlier than Oregon across the 43 aligned pairs (25 equal, 14
at +1, 4 at +2). Strict one-sidedness makes the difference definitional rather
than clerical. CalPERS publishes no dated flows, so which later convention it
uses cannot be identified from public data.

### PME is mostly not computable, by design

Differencing recovers flows that happen *between* snapshots.
`reconstruct_flows_from_snapshots` dates the whole opening balance at the first
snapshot, which is harmless for a multiple and fatal for PME — it prices twenty
years of capital calls at one index level and fails silently, returning a
plausible ratio.

So PME is computed only for funds whose first appearance shows zero paid-in.
That is 63 of 490. Deepening the archive from 8 quarters to 18 tripled the
eligible sample and moved the median PME by 0.001. 59 of the 63 carry ~99% of
value as unrealised marks, so the number describes GP carrying values against
the market, not realisations. Treated as infrastructure, not a finding.

---

## Estimation

### Cluster-robust asymptotics over-reject here

At 20 clusters the analytic p-value rejects a true null 9–13% of the time
against a nominal 5%; the wild cluster bootstrap holds 4–6%, with p-values
essentially uniform. The error is one-directional — it manufactures persistence
rather than hiding it. The bootstrap p exceeds the analytic p in every row of
the specification table.

Implementation note: the clustered variance of a single coefficient is
`Σ_g (Σ_{i∈g} h_i e_i)²` with `h = X (X'X)⁻¹ e_j`, so only one n-vector is
recomputed per replication. 9,999 draws run in ~0.02s, which is what makes
bootstrap-based power curves affordable.

### Mislabelled vintages attenuate, they do not inflate

The intuitive argument: a fund assigned to the wrong year keeps part of its own
year's shock in the residual; a family's consecutive funds sit in nearby
vintages and carry correlated leftovers; correlated residuals are what beta
picks up; therefore mislabelling inflates persistence.

**Simulation says the opposite.** Displacing labels by the observed pattern
(58% unchanged, 33% +1, 9% +2) gives bias −0.038 at true β = 0.25 and −0.070 at
0.50, and ~0 at β = 0. The argument tracks the residual and forgets the
regressor: the same unabsorbed shock enters `y_lag`, and errors-in-variables in
the regressor dominates. This matches the project's existing finding that
*omitting* vintage FE attenuates — mislabelling is a partial version of
omitting.

Bias is proportional at about −14%, so the reported β is a **lower** bound with
respect to this error. Five tests pin the direction so the write-up cannot drift
back to the intuition.

### What the design could detect

Power computed on the actual estimation sample, resampling real residuals with
cluster-level signs and testing each replication exactly as the headline is
tested. Size at β = 0 is 0.057, so the curve is not flattered by a
miscalibrated test.

**MDE at 80% power is β ≈ 0.43.** Power at the estimated 0.214 is ~19%; against
the post-2000 literature's sub-0.15 estimates it is ~8%. This is the single
most useful result in the project — the finding is not "no persistence" but
"this design could only have detected pre-2000-magnitude persistence".

Caveat: the literature figures place an order of magnitude and are not strictly
comparable (different dependent variables, lag definitions, samples).

---

## Cross-plan measurement error

### Secondary sales are not a second measurement

Tailwind Capital Partners III showed a 68% disagreement between plans. It is
not a matching error: identical $200m commitments, same fund. Oregon's NAV is
*exactly zero* with its `sold_secondary` flag set, while CalPERS carries a
$258.9m live mark. Oregon sold; CalPERS did not. The gap is the secondary
discount.

This generalises — 7 of 43 aligned pairs are Oregon secondary sales, all with
zero NAV, and they disagree twelve times more than held pairs (median 9.94% vs
0.82%). They are excluded on principle: a realised transaction price and a live
mark are not two measurements of one quantity, as Oregon's own footnote states.
Only Oregon publishes the flag; CalPERS lists active partnerships only, so a
fund it had sold would be absent rather than mismarked.

λ goes from 0.944 on 43 pairs to **0.986 on 36**, correction 1.06× → 1.014×.
Restricting instead to the 22 vintage-agreeing pairs gives 0.988 independently.

### Correlation is not reliability

For two *parallel* measurements the cross-plan correlation equals the
reliability ratio — but only if the two reports have equal error variance and
their errors are independent. **The independence condition fails here**, because
both plans receive the same GP-reported valuation, so their errors share a large
common component that inflates the correlation above true reliability. λ is
estimated from the variance of paired differences, never read off the
correlation.

The whole exercise gives a **floor**, not the correction. The error that matters
most for persistence — stale, smoothed GP marks — is common to both reports and
cancels exactly in the difference.

---

## Reproducibility

`run_all.sh --offline` skips the network and analyses the cached archive. That
mode is the reproducible one: Oregon rotates quarters off its site, so an online
run later analyses a different sample without saying so.

Two things this caught that nothing else would have. First, gitignoring the
generated CSVs left four scripts with no input in a fresh clone —
`calpers_raw.csv` is *source data* (CalPERS publishes only the current quarter,
so it cannot be re-fetched), and it now lives dated in `data/snapshots/`.
Second, three consumers read the gitignored working copy directly;
`resolve_snapshot()` prefers the working copy and falls back to the newest dated
archive copy.

Determinism is asserted for OLS, the bootstrap, both permutation tests and
leave-one-out, plus a converse check that different seeds really do change the
null draw — otherwise the determinism tests could pass because the seed never
reaches the resampler.

---

## Smaller things worth knowing

- **Leave-one-out must iterate over the estimation sample**, not the panel. An
  early version dropped every family in the mature panel; 135 of the 174 refits
  returned the original coefficient unchanged, which makes an estimate look far
  more robust than it is by burying the informative refits in no-ops.
- **`build_panel(log=False)`** exists because an IRR is already a rate and can
  be negative. Logging it would map every losing fund to log(0.01).
- **Uncalled funds are kept, not dropped.** A fund with zero paid-in has no
  multiple but is the only kind whose entire cash-flow history can be recovered
  from a snapshot archive. Dropping it in the parser is silent data loss exactly
  where it costs most — and keeping it is why commitments now reconcile to the
  published total exactly.
- **Two figure bugs were caught only by rendering and looking at the output**:
  an annotation printed on top of histogram bars, and colliding x-axis labels.
  Generating a figure is not the same as checking it.
- **No strategy field exists** in either source. Classifying by fund-name
  keywords was considered and rejected — "Ares Corporate Opportunities" and
  "GSO Energy Partners" are credit vehicles whose names say nothing of the kind,
  and the result would be a guess presented as data.

---

## Open questions

1. **CalPERS' vintage definition** is systematically later than Oregon's but
   remains unidentified. Needs a methodology note or dated flows, neither
   public.
2. **11 medium-confidence merges** remain (BDC ×3, General Catalyst Health
   Assurance ×2, Genstar Opportunities ×2, Lightspeed Inception/Ignite ×4). The
   high-confidence-only regime gives β = 0.245 against 0.214, so they are not
   driving the estimate.
3. **λ = 0.986 rests on 36 pairs** and is a floor, not the correction.
4. **Precision is bounded by 39 clusters**, not by 459 observations. More
   *families* is the only thing that moves it — CalSTRS and Washington State
   publish the same shape of data, and each new plan also adds overlap pairs.
