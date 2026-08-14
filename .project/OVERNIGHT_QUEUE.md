# OVERNIGHT_QUEUE.md

Work this file top to bottom. Tasks are ordered by dependency — later ones
consume outputs of earlier ones. If a task is blocked, record why in NOTES.md
and move to the next one rather than stopping.

## Operating rules for unattended work

1. **Do not wait for decisions.** Make the call, do it, record the reasoning
   in a docstring or NOTES.md.
2. **`pytest -q` after every change.** Never weaken a test to make it pass. If
   a test is genuinely wrong, fix it and write down why in NOTES.md.
3. **Commit after each numbered task**, message prefixed with the task number,
   so the sequence is reviewable in the morning.
4. **Report what cannot be done.** If a specification has too few clusters or
   pairs to estimate, print that plainly. Never drop a row, loosen a spec, or
   pool categories to make something estimable. A missing row with a stated
   reason is correct; a fabricated row is not.
5. **No conclusions before numbers.** Do not write interpretive prose about
   results that do not yet exist.
6. **Keep NOTES.md running** — every judgement call, every surprise, every
   thing that looked wrong. That file is the morning briefing.
7. Do not refactor working code for style. Only touch what a task requires.

---

## 1. Oregon archive depth

Try the quarterly URL pattern back through 2015. Pull everything that exists
into `data/snapshots/`. Older reports may use a different layout — if the
parser breaks on them, record which years fail and how, then move on.

More history means more funds observed from their first capital call, which is
the binding constraint on the PME sample. Report the new inception-observable
count against the current 24.

## 2. Snapshot provenance manifest

`data/snapshots/MANIFEST.csv`: filename, source, as-of date, download
timestamp, SHA-256, row count. Regenerating must be idempotent and must never
overwrite an existing snapshot. A test that the manifest matches the directory
contents.

## 3. Stage 2.2 + 2.1 + 2.4 — the core result

Build the real-data analysis script. All seven specification rows from
WORK_BRIEF 2.2, run under the three mapping regimes from 2.1 (regex-only,
high-confidence merges, all merges). Analytic and wild-bootstrap p-values
throughout. Add the transition permutation test from 2.4 with cell counts.

Print the sample funnel from raw rows to final pair count. This is the
headline output of the project.

## 4. Additional robustness

Each as a row appended to the specification table:

- Winsorise log TVPI at 1/99 and at 5/95.
- Leave-one-family-out: refit dropping each family in turn, report the range
  of beta. Names the families the estimate depends on.
- Leave-one-vintage-out, same idea for time.
- Spearman rank correlation of successor on predecessor performance within
  vintage — a nonparametric check that does not assume linearity in logs.
- Restrict to families with three or more funds, where sequencing is most
  reliable.
- Buyout-only if a strategy field is recoverable from either source.

## 5. PME, if task 1 deepened the archive

Recompute PME and Direct Alpha on the enlarged inception-observable sample.
Report separately for funds with meaningful realisation (DPI above, say, 0.5)
versus those still carrying mostly marks. If the sample is still dominated by
unrealised 2022+ vintages, say so and leave it as infrastructure rather than
a finding.

## 6. Stage 3.2 — CalPERS/Oregon overlap

**Alignment first, and this is the part that makes or breaks it.** Compare
only reports with the same `as_of` quarter. Mismatched dates measure NAV drift
over time, not reporting error, and would produce an attenuation correction
built on the wrong variance. Report how many pairs survive alignment.

Then: match funds across plans by family stem and fund number, compare
reported TVPI and NAV, estimate the variance of the difference, derive the
attenuation factor `var(true) / (var(true) + var(error))`, and report raw and
corrected beta.

State the limitation explicitly: both LPs are in the same partnership
receiving the same GP-reported NAV, so differences arise from fee terms,
different closes, and rounding rather than independent valuation. The estimate
is a **floor** on reporting noise, not the whole of it. Do not present it as
more than that.

## 7. Figures

`figures/`, matplotlib, no seaborn, readable at half size:

- Coefficient plot: beta with 95% CIs across every specification, one panel.
- Sample funnel: raw rows to final pairs, as a waterfall.
- Vintage coverage: fund count and median TVPI by vintage, unrealised share
  shaded.
- Transition heatmap with cell counts printed in the cells.
- Simulation validation: estimated beta against true beta across DGP settings,
  showing the estimator is unbiased before it meets real data.
- Leave-one-out beta distribution from task 4.

## 8. Reproducibility harness

`run_all.sh` executing the full path from raw data to figures and tables, with
a `--offline` flag using only cached snapshots. Seeds fixed everywhere. Add a
test asserting that two runs of the estimation produce identical numbers.

## 9. RESULTS.md

Draft from the actual numbers, 800–1200 words: what is estimated and why fund
families; data and sample funnel; specification table with the headline row
identified; inference, analytic and bootstrap; robustness; limitations in
priority order with direction of bias where known; conclusion.

If the confidence interval includes zero, say so plainly. "This sample cannot
distinguish persistence from noise, and here is precisely why" is the correct
finding in that case, and stronger than a number dressed up as significant.

## 10. README rewrite

Ninety-second version at the top: what the project shows, headline number with
its interval, what the data is, what it cannot support. Then current test
count, real results table replacing the simulated one, and a repository map.

## 11. Hygiene pass

Docstring at the top of every analysis script stating what it produces. Verify
`firm_overrides.csv` is committed and generated CSVs are ignored. Confirm no
network calls in the test suite. Update `requirements.txt`.

---

## Stop conditions

Stop and leave the summary if: the test suite goes red and cannot be fixed
within the task that broke it; a data source stops responding; or you reach
task 11.

Do not begin anything not on this list.

## Morning summary

Leave in NOTES.md: what completed, what did not and why, the specification
table, the sample funnel, every judgement call made unattended, and anything
that looked wrong or surprising. Flag anything you are less than confident in
explicitly — that list is where review time should go first.
