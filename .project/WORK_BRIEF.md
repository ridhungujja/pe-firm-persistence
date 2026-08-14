# WORK BRIEF

Staged plan to take this repository from "working pipeline" to "defensible
empirical study." Work the stages in order. Stage 1 blocks everything after
it, because every later estimate inherits its errors.

**Standing rules for all stages**

- Run `pytest -q` after every change. Never weaken a test to make it pass.
- Every new estimator or correction needs a validation path: a case where the
  true answer is known, and a test that checks it is recovered.
- Every judgement call goes in a docstring explaining *why*, not just what.
- Do not remove or soften limitations sections. They are the deliverable.
- When something cannot be done honestly with the available data, say so in
  the code and in the README rather than approximating it silently.
- Update the README's test count and results tables when they go stale.

---

## Stage 1 — Data integrity (blocking)

### 1.1 Share-class deduplication

Rows like `Bridgepoint Europe III 'C'` and `Bridgepoint Europe III 'D'` are
share classes of one fund, not two funds. Counting them separately invents
sequence steps and double-counts capital.

Write a dedup pass that runs **before** sequence numbering:

- Group by (family stem, fund number). Where a group has more than one row,
  aggregate: sum `commitment`, `contributions`, `distributions`,
  `total_value`; take the earliest `vintage`; recompute `nav` and `tvpi` from
  the aggregated columns.
- Do **not** average the reported `net_irr` across classes — IRRs are not
  additive. Set it to NaN on aggregated rows and note that the recomputed
  multiple is the usable figure.
- Record `n_share_classes` on each output row so the collapse is auditable.
- Emit a report of every collapsed group to `data/share_class_dedup.csv`.

Tests: two share classes collapse to one row with summed cash and earliest
vintage; a single-class fund passes through untouched; `net_irr` is NaN on
collapsed rows only.

### 1.2 True fund numbers

`sequence` is currently a rank within family, not the fund's actual number.
If CalPERS holds Silver Lake III and VII, those become sequence 1 and 2 and
the regression treats a 2007 fund as the immediate predecessor of a 2021
fund. That is a different estimand than "does fund k predict fund k+1."

- Parse the series designator into an integer `fund_number` (roman and arabic;
  the matcher already locates it). Leave NaN where no number exists.
- In `build_panel`, add `fund_number_gap` = the predecessor's gap in fund
  number, and `vintage_gap` = years between the two vintages.
- Add a `max_gap` argument to `estimate` (default: no restriction) so
  specifications can require adjacent funds.

Tests: roman and arabic numerals parse; gap computes correctly; `max_gap=1`
drops non-adjacent pairs.

### 1.3 Vintage integrity diagnostic

CalPERS sometimes stamps a row with the commitment date rather than the
fund's vintage — Bridgepoint Europe III (a 2005 fund) appears at 2015. Bad
vintages misassign the fixed effects.

- Write a panel-wide check flagging families where `fund_number` order
  contradicts `vintage` order, plus any fund whose vintage is more than three
  years from the family's implied trend.
- Write flagged rows to `data/vintage_anomalies.csv` and print the count.
- Add a `drop_vintage_anomalies` option to the analysis so the estimate can
  be shown with and without them.

Do not silently correct vintages. Flag, report, and let the specification
choose.

---

## Stage 2 — Specification and inference

### 2.1 Mapping robustness table

64 merge decisions are researcher degrees of freedom. Show they are not
driving the result.

Run the main specification three times: regex-only (no overrides),
high-confidence merges only, and all merges. Report β, SE, and n for each in
one table. If β moves materially across regimes, that is a finding to report,
not a problem to hide.

### 2.2 Core specification table

One table, these rows, all with SEs clustered on family:

1. All funds, vintage FE
2. Mature only (excluding CalPERS `not_meaningful`), vintage FE
3. Mature only, adjacent funds only (`max_gap=1`), vintage FE
4. Row 3 + `log_commitment` control
5. Row 3 + `fund_number` control (tests whether later funds in a series
   systematically differ — the "size and sequence" story)
6. Row 3, excluding vintage anomalies
7. Row 3 with `net_irr` as the dependent variable instead of log TVPI

Row 3 is the headline. State that explicitly in the README and say why:
adjacency is what makes β the LP's actual decision problem.

### 2.3 Wild cluster bootstrap

With 74 clusters, cluster-robust asymptotics are borderline; Cameron, Gelbach
and Miller put the rule of thumb near 40 and the finite-sample distortion is
worst exactly where clusters are unbalanced, which ours are.

Implement a wild cluster bootstrap-t with Rademacher weights:

- Estimate the restricted model under H0: β = 0.
- Resample cluster-level weights in {-1, +1}, rebuild y, re-estimate, collect
  the t-statistic on `y_lag`.
- Report the bootstrap p-value alongside the analytic one, 9999 replications.

Validate it: on simulated data from `run_analysis.py` with true β = 0, the
bootstrap p-value should be roughly uniform. Write a test that checks
rejection rates at the 5% level land near 5% across repeated samples.

This is the single most credibility-raising addition available. Where the
analytic and bootstrap p-values disagree, report the bootstrap.

### 2.4 Transition matrix test

Replace eyeballing the quartile matrix with a permutation test: shuffle
successor quartiles within vintage, recompute the diagonal mass, and report
where the observed diagonal sits in the null distribution. Report the exact
p-value and the cell counts, not just the proportions.

---

## Stage 3 — Second data source (highest value remaining)

### 3.1 Add another plan

Build an adapter for one more public plan — Oregon PERS, Washington State
Investment Board, or CalSTRS. Same canonical schema, its own parser and
tests. Check the published format first: some publish HTML tables, some PDFs.
If it is a PDF, say so before building rather than fighting it.

### 3.2 Cross-LP measurement error — the interesting part

Funds appearing in two plans give something rare: **the same underlying fund
reported twice, independently.**

- Match overlapping funds across plans and compare reported TVPI and NAV.
- The variance of the difference estimates reporting noise directly. Under
  classical measurement error, the attenuation factor for β is
  `var(true) / (var(true) + var(error))`, so this gives an empirically
  grounded correction rather than a hand-wave.
- Report the raw β, the estimated attenuation factor, and the corrected β.

State the assumptions plainly: the two LPs' reports are for the same fund but
their cash flows differ by commitment size and timing, so the difference
mixes true reporting noise with genuine differences in each LP's position.
That caveat belongs in the write-up. Even bounded, this is a far stronger
treatment of measurement error than simply naming it as a limitation.

---

## Stage 4 — PME infrastructure

CalPERS publishes cumulative totals, not dated flows, so PME is unavailable
from one snapshot. Build the machinery now so it works later.

- Add a snapshot archive: `data/snapshots/calpers_YYYY-MM-DD.csv`, written on
  every fetch, never overwritten.
- Wire `reconstruct_flows_from_snapshots` to that archive and compute PME
  where two or more snapshots exist.
- Add a benchmark loader for a total-return series and document exactly where
  to get one. Total return, not price — a price index inflates every PME.
- Where fewer than two snapshots exist, PME columns must be NaN, never
  approximated from a single observation.

---

## Stage 5 — Presentation

### 5.1 Figures

Save to `figures/`, matplotlib, no seaborn:

- Coefficient plot: β with 95% CIs across all specifications in one panel.
- Vintage coverage: fund count and median TVPI by vintage, with unrealised
  share shaded.
- Quartile transition heatmap with cell counts printed.
- Simulated validation: estimated β against true β across the DGP settings in
  `run_analysis.py`, showing the estimator is unbiased before it meets real
  data.

### 5.2 Results write-up

Draft `RESULTS.md`, 800-1200 words:

- What is estimated and why fund families, not firms.
- Data, with the sample funnel from 462 rows to the final pair count.
- The specification table and which row is the headline.
- Inference: analytic and bootstrap.
- Robustness: mapping regimes, anomaly exclusion.
- Limitations, in priority order, each with its direction of bias where known.
- An honest conclusion. If the CI includes zero, say so plainly — the correct
  finding is "this sample cannot distinguish persistence from noise, and here
  is precisely why," not a number dressed up as significant.

Draft it from the actual numbers. Do not write the conclusion before the
estimates exist.

### 5.3 Repository presentation

- README: current test count, results table, a "what this project shows"
  section at the top for a reader who will spend ninety seconds.
- Docstring at the top of every analysis script saying what it produces.
- `data/.gitkeep` retained; generated CSVs stay gitignored except
  `firm_overrides.csv`, which is an input and must be committed.

---

## Priority if time runs short

Stage 1 and 2.3 are non-negotiable — the first because everything inherits
it, the second because it is what makes the standard errors trustworthy at
this sample size. Stage 3.2 is the most distinctive thing in the plan and the
one most likely to be asked about in an interview. Stage 4 can wait for the
next quarterly snapshot. Stage 5 is what the reader actually sees.
