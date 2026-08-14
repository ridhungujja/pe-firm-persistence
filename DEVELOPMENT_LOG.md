# DEVELOPMENT_LOG.md

Running record of the work, in order. Judgement calls, surprises, and
anything that looked wrong.

Running log from the unattended queue. Judgement calls, surprises, and
anything that looked wrong. Morning summary at the bottom.

Start: 130 tests passing, baseline commit `ca23a34`.

---

## 1. Oregon archive depth — done

**Result: 18 quarters, 2021-03-31 to 2026-03-31, all parsing cleanly.**
Previously 8 quarters (2023-12-31 to 2025-09-30).

**The judgement call: I replaced URL-templating with link discovery.**
The queue said to try the template back through 2015. I did, and it was the
wrong tool. Probing the current pattern across 2014–2026 (52 URLs) found 8
reports. Reading the Treasury holdings page found 18. Oregon has used at least
five naming conventions for the same quarterly report:

    OPERF-Private-Equity-Portfolio-Quarter-1-2021.pdf
    OPERF-Private-Equity-Q2-2022.pdf
    PrivateEquity-Q3-2023.pdf
    OPERF_Private_Equity_Portfolio_-_Quarter_4_2023.pdf
    OPERF-Private-Equity-Portfolio-Quarter-4-2025.pdf   (filed under /2026/)

`discover_reports()` now scrapes the holdings page. It degrades honestly: if
Oregon reorganises, it returns an empty list rather than a set of URLs that
404. `quarter_url()` and the template are kept for reference but no longer
drive the fetch.

**Surprise worth flagging:** the Q4 2025 report is filed in the **2026**
folder. Taking the year from the folder rather than the filename would date
that snapshot a year late and scramble the ordering that cash-flow
differencing depends on. There is a test pinning this.

**No layout failures.** All 18 parsed, including the 2021 reports, which I had
expected to break. Fund counts rise monotonically with time (386 → 453), which
is the right shape for a plan that keeps adding partnerships, and the parser's
published-total reconciliation holds on the sampled quarters.

**Nothing available before 2021-03-31.** The holdings page links no earlier PE
report. So the archive cannot be deepened further from this source; 2021Q1 is
the floor, not a stopping point I chose.

**Gaps in the archive:** 2022 Q1, 2022 Q3, 2023 Q1 are not published. Differencing
across a gap spans six months rather than three, so those flows are dated at the
end of a longer interval. Recorded here because it slightly worsens the
within-quarter timing approximation for the affected funds.

### Effect on the PME sample (the point of the task)

| | 8 quarters | 18 quarters |
|---|---|---|
| distinct funds | 473 | 490 |
| observed 2+ dates | 472 | 480 |
| **inception-observable** | **24** | **71** |

Inception-observable means the fund's first appearance shows zero paid-in, so
its whole call history is inside the window and PME is computable honestly.

Vintages of the 71: 2019 (2), 2020 (1), 2021 (21), 2022 (12), 2023 (24),
2024 (6), 2025 (5).

**Still marks-dominated.** Only 4 of the 71 have DPI above 0.5; 39 have any
distribution at all. Deepening the archive tripled the sample but did not
change its character — these are young funds carrying GP valuations. Task 5
should treat this as infrastructure, not a finding.

Tests: 130 → 137.

---

## 2. Snapshot provenance manifest — done

`data/snapshots/MANIFEST.csv`, 37 rows: 19 parsed snapshots and 18 raw PDFs.
Columns are filename, kind, source, as_of, download_timestamp, sha256, rows.

**Judgement call: the manifest covers raw PDFs too, not just the CSVs.** The
queue specified a row count, which only applies to snapshots, but the PDFs are
the irreplaceable half of the archive and a corrupted one would otherwise be
invisible. Raw rows carry an empty row count and a quarter-end `as_of` derived
from the filename, so no PDF has to be reopened to build the manifest.

**Judgement call: `download_timestamp` is preserved across rebuilds** for any
file whose hash is unchanged. Rebuilding is bookkeeping; if it restamped every
row with today's date it would destroy the provenance the file exists to hold.
Only a genuine byte change refreshes the timestamp. There is a test for this,
and one asserting that building the manifest never writes or deletes a
snapshot.

`verify_manifest()` reports `missing` / `untracked` / `changed`. The `changed`
case is the one that matters: a re-download returning different bytes for the
same quarter means the plan restated something, and a restatement changes
reconstructed cash flows. File size and mtime would not catch it.

Wired into both fetch scripts, so the manifest refreshes whenever the archive
does. The shipped archive currently verifies clean.

Tests: 137 → 156.

---

## 3. Core result — done

`analysis/run_real_analysis.py`. Outputs `data/real_specifications.csv`,
`data/mapping_robustness.csv`, `data/transition_test.csv`,
`data/transition_counts.csv`.

### Sample funnel (all merges)

| | |
|---|---|
| rows published by CalPERS | 462 |
| after share-class dedup | 462 |
| funds with a computable TVPI | 459 |
| distinct fund families | 330 |
| families with 2+ funds | 75 |
| **lagged pairs (estimation sample)** | **129** |
| of which adjacent (gap = 1) | 100 |
| **mature AND adjacent (headline)** | **65** |

### Specification table (y = log TVPI, SEs clustered on family)

| specification | beta | SE | 95% CI | p | p_boot | n | families |
|---|---|---|---|---|---|---|---|
| 1. All funds, vintage FE | 0.390 | 0.139 | [0.118, 0.663] | 0.005 | 0.006 | 129 | 75 |
| 2. Mature only, vintage FE | 0.248 | 0.109 | [0.035, 0.461] | 0.023 | 0.045 | 87 | 51 |
| **3. Mature, adjacent only [HEADLINE]** | **0.214** | **0.138** | **[−0.057, 0.485]** | 0.121 | **0.187** | 65 | 39 |
| 4. Row 3 + log commitment | 0.215 | 0.145 | [−0.069, 0.500] | 0.138 | 0.223 | 65 | 39 |
| 5. Row 3 + fund number | 0.193 | 0.136 | [−0.073, 0.459] | 0.156 | 0.212 | 65 | 39 |
| 6. Row 3, excl. vintage anomalies | 0.214 | 0.138 | [−0.057, 0.485] | 0.121 | 0.187 | 65 | 39 |
| 7. Row 3, dependent = net IRR | 0.123 | 0.110 | [−0.093, 0.339] | 0.263 | 0.320 | 63 | 37 |

**The headline confidence interval includes zero.** No interpretive prose here
— that belongs in task 9, written from these numbers.

Three things I want flagged for review:

1. **Beta falls monotonically as the specification tightens** (0.390 → 0.248 →
   0.214) and significance goes with it. Row 1 pools non-adjacent pairs, so a
   2007 fund can predict a 2021 one; that is the loose specification, not the
   headline, and it is the only row that looks decisive.
2. **Row 6 is identical to row 3 by construction.** There are zero vintage
   anomalies left after share-class dedup (task 1.1 absorbed all four
   Bridgepoint mis-stamps via the earliest-vintage rule), so "excluding
   anomalies" excludes nothing. The row is kept because its being a no-op is
   itself the finding, but it should not be read as independent evidence.
3. **The bootstrap p exceeds the analytic p in every single row.** Row 2 is
   the clean illustration: analytic 0.023 (significant at 5%) versus bootstrap
   0.045 (barely). In the regex-only mapping regime the gap is starker —
   analytic 0.037 versus bootstrap 0.129, i.e. the asymptotic would call it
   significant and the bootstrap does not.

### Mapping robustness

| regime | merges | families | pairs | beta | SE | p | p_boot | n |
|---|---|---|---|---|---|---|---|---|
| regex only | 0 | 383 | 79 | 0.270 | 0.129 | 0.037 | 0.129 | 40 |
| high-confidence only | 58 | 337 | 122 | 0.245 | 0.144 | 0.089 | 0.159 | 64 |
| all merges | 70 | 330 | 129 | 0.214 | 0.138 | 0.121 | 0.187 | 65 |

Spread in beta across regimes is 0.055, well inside one standard error
(~0.14). **The 70 merge decisions are not driving the estimate.** They do
drive the sample size: regex-only leaves 40 usable observations against 65,
which is the cost of leaving split series unmerged.

### Quartile transition permutation test

47 mature adjacent pairs survive within-vintage quartile assignment. Cell
counts (rows predecessor, columns successor):

```
                      1    2    3    4
predecessor 1         6    2    3    3
predecessor 2         4    3    3    1
predecessor 3         0    4    3    3
predecessor 4         4    2    1    5
```

Observed diagonal share 0.362; permutation null mean 0.259 (sd 0.068);
**p = 0.089** over 9999 within-vintage shuffles.

Shuffling within vintage preserves both the pairs-per-vintage count and the
marginal outcome distribution, so the null is exactly "the predecessor carries
no information", holding vintage structure fixed. There is a test asserting
that large vintage effects alone do not register as persistence.

### Code changes made for this task

- `build_panel(..., log=True)`. Row 7 needs net IRR in levels: an IRR is
  already a rate and can be negative, so `np.log(clip(lower=0.01))` would have
  silently mapped every losing fund to log(0.01).
- `_quartile_frame` factored out of `quartile_transitions` so the counts and
  the permutation test share one definition of a quartile pair.
- `fetch_calpers.py` now caches `data/calpers_raw.csv`, the un-normalised
  table. The three mapping regimes each need the full ingestion path re-run,
  and share-class dedup keys on `firm_id`, so a regime cannot be recovered
  from the processed snapshot.

Tests: 156 → 165.

---

## 4. Additional robustness — done

Appended to the specification table (`data/robustness_rows.csv`, and
`data/all_specifications.csv` combines rows 1–9). All against the headline
sample: mature, adjacent pairs.

| specification | beta | SE | 95% CI | p | p_boot | n | families |
|---|---|---|---|---|---|---|---|
| 8. Winsorised 1/99 | 0.214 | 0.138 | [−0.057, 0.485] | 0.122 | 0.187 | 65 | 39 |
| 8. Winsorised 5/95 | 0.222 | 0.158 | [−0.087, 0.532] | 0.158 | 0.219 | 65 | 39 |
| 9. Families with 3+ funds | 0.148 | 0.211 | [−0.265, 0.562] | 0.482 | 0.696 | 44 | 18 |

**Winsorising barely moves it.** 0.214 → 0.214 at 1/99 and → 0.222 at 5/95, so
the estimate is not an outlier artefact. Worth knowing given how skewed fund
multiples are.

**Restricting to families with 3+ funds nearly doubles the standard error**
(0.138 → 0.211) and halves beta. 18 families, 44 pairs. The queue's rationale
was that sequencing is most reliable there, and that is true, but the sample
is too small to say anything — this row is a precision loss, not evidence
against persistence.

### Leave-one-out

- **Family:** 39 refits, beta ranges **[0.138, 0.281]** around 0.214. No refit
  produces beta ≤ 0. Largest single influence is dropping
  `YUCAIPA CORPORATE INITIATIVES FUND`, which moves beta to 0.138 (−0.076).
- **Vintage:** 17 refits, beta ranges **[0.118, 0.308]**. No refit produces
  beta ≤ 0. Dropping vintage 2008 moves beta to 0.118 (−0.097) — the largest
  single influence anywhere in the robustness set, and worth noting that it is
  the financial-crisis vintage.

Neither exercise finds a family or a year the result depends on for its sign.
Both find that the magnitude moves by roughly half a standard error, which is
about what 65 observations should be expected to do.

**Correction made mid-task.** My first run reported 174 family refits and a
range of [0.138, 0.281]. The range was right but the refit count was not: I
was dropping every family in the mature panel, and only 39 of them contribute
to the adjacent-pairs regression. The other 135 refits returned the original
coefficient unchanged, which makes an estimate look far more robust than it is
by burying the informative refits in no-ops. `leave_one_out` now takes a
`levels` argument and the script passes the families actually in the
estimation sample. Same for vintages, 23 → 17.

### Spearman rank correlation within vintage

rho = **+0.230**, permutation p = **0.239**, 65 pairs. Same sign and rough
magnitude as beta, same conclusion — not distinguishable from zero. Because it
correlates within-vintage percentile ranks it is invariant to any monotone
transform of TVPI, so it independently rules out the linear-in-logs functional
form as the reason the regression finds what it finds.

### Buyout-only — NOT POSSIBLE

Neither source publishes a strategy field. CalPERS gives fund name, vintage,
and cash columns; Oregon adds a secondary-sale flag and a reported multiple.
Nothing classifies a fund as buyout, venture, growth or credit.

I considered classifying from fund names and rejected it: "Ares Corporate
Opportunities" and "GSO Energy Partners" are credit vehicles whose names say
nothing of the kind, and a keyword rule would produce a strategy column that
looks like data and is actually a guess. Left out rather than filled in.

Tests: 165 → 175.

---

## 5. PME on the enlarged archive — done, but still infrastructure

18 quarters instead of 8. PME computed for **63 funds** (up from 18).

| | 8 quarters | 18 quarters |
|---|---|---|
| funds in archive | 473 | 490 |
| inception-observable | 24 | 71 |
| PME actually computed | 18 | 63 |
| median KS PME | 0.956 | 0.957 |
| median direct alpha | −5.62% | −1.47% |
| median TVPI | 1.065 | 1.182 |
| median share unrealised | 100.0% | 98.7% |

Tripling the sample moved the median PME by 0.001. Direct alpha moved from
−5.6% to −1.5%, which is the more meaningful change and mostly reflects the
sample now including 2019–2021 vintages with a little more life behind them.

### Split by realisation, as the queue asked

| group | n | median PME | median DPI | median unrealised |
|---|---|---|---|---|
| DPI > 0.5 (realising) | 4 | 0.939 | 0.568 | 56.9% |
| DPI ≤ 0.5 (mostly marks) | 59 | 0.957 | 0.013 | 98.9% |

**Four funds is not a comparison.** The two medians are close, but with n = 4
on one side that is not evidence they agree. The honest read is that the
realised group is too small to be a check on the marked group, which was the
question worth asking.

**Verdict: this stays infrastructure, not a finding.** 59 of 63 funds have
returned essentially nothing (median DPI 0.013) and carry 98.9% of their value
as unrealised marks. A PME of 0.957 on that sample says the GPs' own carrying
values have grown slightly slower than the US market since the funds were
struck. It does not say anything about realised performance, and it should not
be quoted as if it did.

The gap between 71 inception-observable and 63 computed: 8 funds have no
non-zero reconstructed flow yet — committed and observed at multiple dates,
but no capital called during the window.

**What would change this.** Each additional year of archive both adds
inception-observable funds and ages the existing ones. The 2021 vintages in
this sample reach year seven or eight around 2028-29, at which point a
realised-versus-marked comparison becomes possible with a real n. The
machinery is built and tested; it needs time, not code.

---

## 6. CalPERS/Oregon overlap — done. Read the caveat before the number.

`analysis/run_overlap.py` → `data/overlap_pairs.csv`, `data/attenuation.csv`.

### A real bug found and fixed on the way in

**The CalPERS adapter was stamping `as_of` with today's date.** `load()` did
`pd.Timestamp.today()`, because the table has no date column. The reporting
date is in the page's prose — "As of September 30, 2025" — and the parser
never read it.

That made alignment impossible in exactly the way this task warns about: the
snapshot was labelled 2026-08-13 when it describes the quarter ending
2025-09-30, nearly a year earlier. Comparing it against any Oregon quarter
would have measured NAV growth and called it reporting error. `parse_as_of()`
now reads the date from the page, and `load()` raises rather than falling back
to today if it cannot find one.

Side effect: the archived snapshot `calpers_2026-08-13.csv` was misnamed and
has been replaced by `calpers_2025-09-30.csv`. The old file is deleted in this
commit — it is the same data under a wrong date, not a lost observation.

### Alignment

Both plans describe the quarter ending **2025-09-30**. 43 pairs matched on
(family stem, fund number), 9.6% of the smaller plan.

Matching uses the raw regex stem, not the override-corrected family id: the
overrides were hand-checked against CalPERS spellings, and applying them to
Oregon's slightly different names would map one side and not the other,
destroying matches rather than creating them.

### How far apart are two reports of the same fund?

| | |
|---|---|
| correlation of log TVPI across plans | 0.944 |
| median absolute difference | 1.41% |
| 90th percentile | 10.71% |
| largest | 68.30% |

The largest is Tailwind Capital Partners III: CalPERS 1.693, Oregon 1.006.
I have not been able to explain that one and it is worth a look — a 68% gap on
the same partnership is not fee terms. Candidates are a secondary purchase by
one plan, materially different close dates, or a genuine matching error where
the two plans hold different vehicles under one name. **Flagged as low
confidence.**

### An unexpected finding: the plans disagree on vintage year

**18 of 43 pairs assign different vintage years to the same fund.** The
disagreement is systematic, never random in sign:

| CalPERS minus Oregon | pairs |
|---|---|
| 0 | 25 |
| +1 | 14 |
| +2 | 4 |

CalPERS always dates a fund the same or later, never earlier. The natural
reading is that CalPERS records the year of its own first capital call while
Oregon records the fund's vintage, which would also explain why
vintage-disagreeing pairs have double the median reporting gap (0.0162 vs
0.0081 in logs) — the plans entered at different closes.

**This matters beyond this task.** Vintage fixed effects are the main control
in the specification table, and this says the vintage label itself carries
error of about a year for 40% of funds. Not fixable with the data available,
but it belongs in the limitations and I have not seen it discussed in the
project so far.

### Attenuation

| | lambda | n |
|---|---|---|
| all aligned pairs | **0.944** [0.828, 0.990] | 43 |
| excluding the single largest gap | 0.981 | 42 |
| vintage-agreeing pairs only | 0.980 | 25 |

    beta raw        0.2142
    beta corrected  0.2269   [0.2164, 0.2586] from the lambda interval
    correction      1.059x

Both sensitivities push lambda toward 0.98, i.e. a correction of ~1.02x rather
than 1.06x. So the headline correction is itself driven mostly by the one
unexplained outlier. The honest summary: **the correction is small, between
1.02x and 1.06x, and does not change any conclusion.**

### The caveat that matters more than the number

This is a **floor**, and the reason is structural. Both plans are LPs in the
same partnership receiving the same GP-reported valuation. They are not
independent appraisals. What differs between them is fee terms negotiated at
different closes, entry timing, each plan's own share, and rounding — CalPERS
reports whole dollars, Oregon reports millions to one decimal.

The error that actually matters for persistence — that GP carrying values are
stale and smoothed relative to what the assets would fetch — is *common to
both reports* and cancels exactly in the difference. So the true attenuation
is larger than 1.06x by an unknown amount, and overlap data cannot bound it.
The corrected beta above should be read as "the correction is at least this
big", never as the corrected truth.

Validation: `attenuation()` has tests recovering a known lambda from simulated
reports with a known error variance (0.30/0.10 → 0.90, recovered to ±0.03).

Tests: 175 → 181.

---

## 7. Figures — done

`analysis/make_figures.py` → six PNGs in `figures/`. Matplotlib only, no
seaborn, all readable at half size.

`coefficients.png`, `sample_funnel.png`, `vintage_coverage.png`,
`transition_heatmap.png`, `simulation_validation.png`, `leave_one_out.png`.

**Judgement call: vintage coverage is two stacked panels, not one panel with
two y-axes.** The queue asked for fund count and median TVPI in one figure.
Putting both on a twin axis is the single most common way to mislead with a
chart: the reader sees the two lines cross, or diverge, and reads a
relationship that is entirely an artefact of where the two scales were pinned.
Same x-axis, two panels, no false crossing available.

**Colours** are the first three slots of a palette I ran through a
colour-vision validator before using: worst all-pairs CVD deltaE 9.2, worst
normal-vision 24.0 on a light surface, all checks pass. Aqua sits below 3:1
contrast on white, so wherever it appears it carries a text label rather than
relying on colour. Blue is the estimate, orange is the headline row, and no
figure uses colour as the only cue.

The transition heatmap is a single-hue sequential ramp with counts printed in
every cell. A rainbow would imply the quartiles are unordered categories, and
percentages without counts are meaningless at n = 47 — "43%" is six funds.

**Two layout bugs I caught only by rendering and looking**, which is worth
recording as a habit: the leave-one-out annotation was printed on top of the
histogram bars and unreadable, and the funnel's x labels collided into each
other ("Rows published" / "After share-class" / "Computable" ran together).
Both fixed. Generating a figure is not the same as checking it.

`simulation_validation.png` is the one to look at first. Six DGP settings with
true beta from 0.00 to 0.44; every 95% interval covers the identity line. The
estimator recovers known persistence before it is pointed at real data.

Figures are committed rather than gitignored — they are a deliverable the
reader sees, not an intermediate artefact, and they total ~350KB.

---

## 8. Reproducibility harness — done

`./run_all.sh` runs tests → fetch both plans → family review → persistence
estimates → overlap → PME → simulation validation → figures.

`./run_all.sh --offline` skips only the two network fetches and analyses the
cached archive. Verified end to end: it reproduces beta = 0.2142 exactly.

**Why --offline is the important half.** The archive is the reproducible part
and the network is not. Oregon rotates old quarters off its site and CalPERS
publishes only the current table, so an online run six months from now
silently analyses a different sample and produces different numbers with no
warning. Offline mode pins the result to the committed archive.

`tests/test_repro.py`, 10 tests. Determinism for OLS, the bootstrap, both
permutation tests, and leave-one-out. Two are worth calling out:

- **A converse check on the seed.** Asserting two runs match is satisfied just
  as well by a resampler that never reaches the seed at all. So there is also
  a test that two *different* seeds produce different null draws while leaving
  the observed statistic unchanged. Without it the determinism test could pass
  for the wrong reason.
- **Row-order invariance.** Reading the same CSV elsewhere can return rows in
  a different order; the coefficient must not care. It does not.

Plus three tests on the shipped tables: all seven specification rows present
and estimated, exactly one row labelled headline, and all three mapping
regimes estimated with beta spread below one standard error. That last one is
a real assertion rather than a formality — if the family mapping ever starts
driving the estimate, it fails.

Tests: 181 → 191.

---

## 9. RESULTS.md — done

Drafted after the numbers existed, not before. 1,279 words excluding tables,
slightly over the 800–1,200 target; I stopped trimming because every remaining
paragraph carries content the brief asked for by name (six limitations, five
robustness checks, both flavours of inference). Cutting further would have
meant dropping required material to hit a word count.

Structure: estimand and why families → data and funnel → specification table →
inference → robustness → limitations in priority order → conclusion.

**The conclusion says the interval includes zero, plainly, in the first two
lines.** It then argues why that is a finding rather than a failure: it is what
the post-2000 literature predicts, and the same data yields a
decisive-looking 0.390 under the loose specification, so the gap between 0.390
and 0.214 is the methodological content.

Direction of bias is stated wherever it is known — stale marks attenuate toward
zero, outcome censoring cuts beta 37% in simulation while regressor truncation
leaves OLS consistent — and stated as unknown where it is (active-partnerships
selection).

Nothing in it is asserted that is not in a committed CSV.

---

## 10. README rewrite — done

Ninety-second section at the top: the question, β = 0.214 with its interval and
the plain statement that it includes zero, the specification-gap point, what
the data is, and an explicit "what it cannot support" list. Coefficient plot
directly under it.

Simulated results no longer lead. They now sit under "Validation on simulated
data", which is what they are — evidence the estimator works before it meets
real data — rather than the project's results. Real results are the results
section.

Test count 130 → 191. Repository map added.

**Limitations kept and expanded, not trimmed.** The rewrite added four
(vintage-label error, PME coverage, no strategy dimension, the overlap
correction being a floor) and kept every original one, including the two the
old README had that nothing in the queue touched — funds under five years old,
and parallel vehicles breaking the AR(1) ordering. Also carried over the "IRRs
do not aggregate" point, which was in the old results section and would
otherwise have been lost.

---

## 11. Hygiene pass — done, and it found a real break

Docstrings: all eight analysis scripts now state what they produce
(`run_analysis.py` was the one missing it). No network calls in the test suite
— the Oregon discovery test monkeypatches `urlopen`, the French tests use
inline CSV. `patsy` added to `requirements.txt`: `persistence.py` imports it
directly and was relying on statsmodels pulling it in transitively, which is
how a build breaks six months later for no visible reason.

**Then the ignore fix broke offline reproduction, and I only caught it by
actually cloning the repo and running it.** Two follow-up commits:

- `11b` — ignoring `data/calpers_raw.csv` left `run_real_analysis.py` with no
  input in a fresh clone. That file is *source data*, not a derived artefact:
  CalPERS publishes only the current quarter, so it cannot be re-fetched later,
  which is the same argument that keeps the Oregon PDFs. It is now archived
  under a dated, never-overwritten name in `data/snapshots/` and tracked.
- `11c` — three more scripts read the gitignored `calpers_snapshot.csv`.
  Added `resolve_snapshot()` to the package: prefer the working copy, fall back
  to the newest dated archive copy.

Verified by cloning into a temp directory and running `./run_all.sh --offline`
from scratch: reproduces beta = 0.2142 and lambda = 0.9443 exactly.

Tracked vs ignored, final state: `firm_overrides.csv`, the snapshot archive,
its `MANIFEST.csv`, and `figures/` are tracked, each with a stated reason in
`.gitignore`. All 20 generated result CSVs are ignored.

---

# MORNING SUMMARY

**All 11 queue tasks completed.** 14 commits, `ca23a34` → `HEAD`. Tests
130 → 191, all passing. No stop condition was hit.

## The headline

**β = 0.214, SE 0.138, 95% CI [−0.057, 0.485], bootstrap p = 0.187**, on 65
adjacent pairs of mature funds across 39 fund families. **The interval includes
zero.** Full write-up in `RESULTS.md`; ninety-second version at the top of
`README.md`.

The finding I would lead with in an interview is not that number but the
sequence: β falls 0.390 → 0.248 → 0.214 as the specification tightens from
"any earlier fund predicts any later one, including funds too young to have
realised anything" to "fund k predicts fund k+1, mature funds only". Only the
loosest row looks significant.

## Sample funnel

| step | n |
|---|---|
| rows published by CalPERS | 462 |
| after share-class dedup | 462 |
| computable TVPI | 459 |
| in families with 2+ funds | 204 |
| lagged pairs | 129 |
| adjacent pairs | 100 |
| **mature and adjacent — estimation sample** | **65** |

## Specification table

| specification | β | SE | 95% CI | p | p_boot | n |
|---|---|---|---|---|---|---|
| 1. All funds, vintage FE | 0.390 | 0.139 | [0.118, 0.663] | 0.005 | 0.006 | 129 |
| 2. Mature only, vintage FE | 0.248 | 0.109 | [0.035, 0.461] | 0.023 | 0.045 | 87 |
| **3. Mature, adjacent — HEADLINE** | **0.214** | **0.138** | **[−0.057, 0.485]** | 0.121 | **0.187** | 65 |
| 4. + log commitment | 0.215 | 0.145 | [−0.069, 0.500] | 0.138 | 0.223 | 65 |
| 5. + fund number | 0.193 | 0.136 | [−0.073, 0.459] | 0.156 | 0.212 | 65 |
| 6. Excl. vintage anomalies | 0.214 | 0.138 | [−0.057, 0.485] | 0.121 | 0.187 | 65 |
| 7. Dependent = net IRR | 0.123 | 0.110 | [−0.093, 0.339] | 0.263 | 0.320 | 63 |
| 8. Winsorised 1/99 | 0.214 | 0.138 | [−0.057, 0.485] | 0.122 | 0.187 | 65 |
| 8. Winsorised 5/95 | 0.222 | 0.158 | [−0.087, 0.532] | 0.158 | 0.219 | 65 |
| 9. Families with 3+ funds | 0.148 | 0.211 | [−0.265, 0.562] | 0.482 | 0.696 | 44 |

Mapping regimes: β = 0.270 (regex only) / 0.245 (high-confidence) / 0.214 (all
merges); spread 0.055, inside one SE. Leave-one-family-out [0.138, 0.281] over
39 refits; leave-one-vintage-out [0.118, 0.308] over 17; none reaches zero.
Spearman within vintage +0.230, permutation p 0.239. Transition diagonal 36.2%
vs 25.9% null, p = 0.089.

## What did not get done, and why

- **Buyout-only specification — impossible.** Neither plan publishes a strategy
  field. I considered classifying from fund names and rejected it: "Ares
  Corporate Opportunities" and "GSO Energy Partners" are credit vehicles whose
  names say nothing of the kind. A keyword rule would produce a column that
  looks like data and is a guess.
- **PME remains infrastructure, not a finding.** The archive tripled the
  eligible sample (24 → 71 funds, 63 computed) and moved the median PME by
  0.001. Only 4 of 63 have DPI above 0.5. It needs years, not code.
- **Nothing was deferred for time.** Every queue item was either completed or
  reported impossible with a reason.

## Judgement calls made unattended

1. **Replaced Oregon URL-templating with link discovery** (task 1). The queue
   said to try the template back to 2015; the template found 8 reports across
   52 probes, reading the holdings page found 18. Five naming conventions in
   use. This roughly tripled the PME sample.
2. **Manifest covers raw PDFs, not just CSVs** (task 2), and preserves
   `download_timestamp` across rebuilds — restamping it would destroy the
   provenance the file exists to hold.
3. **`build_panel(log=False)`** so row 7 can use net IRR in levels. Logging an
   IRR would have mapped every losing fund to log(0.01).
4. **`leave_one_out(levels=…)`** after my first run reported 174 refits when
   only 39 families are in the estimation sample. 135 no-op refits make an
   estimate look far more robust than it is.
5. **Vintage coverage is two panels, not a twin y-axis** (task 7). Two
   unrelated scales on one axis invites a reading of "crossing" that is an
   artefact of scale placement.
6. **Figures committed, generated CSVs not.** Figures are a deliverable the
   reader sees.
7. **`calpers_raw.csv` reclassified as source data** and archived dated, after
   the fresh-clone test showed offline reproduction broken.

## Two real bugs found and fixed

- **The CalPERS adapter stamped `as_of` with today's date.** It reports the
  quarter ending 2025-09-30 but the snapshot claimed 2026-08-13. Task 6 is
  impossible without fixing this — every cross-plan comparison would have
  measured eleven months of NAV growth and called it reporting error. The
  reporting date is in the page's prose; `parse_as_of()` now reads it and
  `load()` raises rather than defaulting to today.
- **Offline reproduction broken by my own hygiene pass**, caught only by
  cloning and running. Fixed in 11b/11c.

## Flagged — where to spend review time first

1. **Tailwind Capital Partners III, the 68% cross-plan outlier.** CalPERS
   reports TVPI 1.693, Oregon 1.006, same quarter, same fund name and number. I
   cannot explain it. Fee terms do not produce a 68% gap. Candidates: one plan
   bought in on the secondary, materially different closes, or a genuine
   matching error where the two plans hold different vehicles under one name.
   **This one drives the headline attenuation figure** — excluding it moves
   lambda from 0.944 to 0.981. Lowest-confidence item in the run.
2. **18 of 43 cross-plan pairs disagree on vintage year**, always with CalPERS
   dating equal or later (+1 in 14 cases, +2 in 4). My reading is that CalPERS
   records its own first capital call and Oregon the fund's vintage, but I have
   not confirmed it against either plan's methodology note. If it is right,
   vintage fixed effects — the main control in every specification — carry
   about a year of error for 40% of funds. Worth checking; it is a limitation I
   have not seen stated anywhere in the project.
3. **Row 6 is a no-op** and should not be read as independent evidence. Share-
   class dedup already absorbed every vintage anomaly via its earliest-vintage
   rule, so "excluding anomalies" excludes nothing.
4. **`lambda` on 43 pairs is a thin variance estimate.** The bootstrap interval
   [0.828, 0.990] is wide, and the correction (1.02–1.06×) changes no
   conclusion. Do not quote the corrected β as if it were precise.
5. **Medium-confidence merges in `firm_overrides.csv`** — the VIP, BDC,
   Lightspeed Inception/Ignite, General Catalyst Health Assurance and Genstar
   Opportunities rows. All are marked `confidence=medium` with reasons. The
   high-confidence-only regime gives β = 0.245 against 0.214, so they are not
   driving the result, but they are the rows a reviewer should check first.

## Suggested next step

More **families**, not more funds — precision is bounded by 39 clusters, not by
459 observations. CalSTRS and Washington State publish the same shape of data;
the Oregon adapter shows the PDF path costs about a day. Each new plan also
adds cross-plan overlap pairs, which is the only route to a measurement-error
estimate that is not a floor.

---

## Item 1. Sponsor-level clustering — done

New layer above family: `sponsor_id`. `derive_sponsor_ids()` takes the
family's leading token (stripping a leading "The"), and
`data/sponsor_overrides.csv` carries 22 hand-recorded corrections for the
cases the rule gets wrong. Fund family remains the estimation unit; only the
clustering dimension changes.

**Result — the change is real but small:**

| | β | SE | 95% CI | p | p_boot | clusters |
|---|---|---|---|---|---|---|
| headline, clustered on **family** | 0.2142 | 0.1381 | [−0.057, 0.485] | 0.121 | 0.187 | **39** |
| headline, clustered on **sponsor** | 0.2142 | 0.1398 | [−0.060, 0.488] | 0.125 | 0.177 | **33** |

β is identical to nine decimal places, as it must be — clustering is a
variance assumption and cannot move a point estimate. There is a test
asserting exactly that.

The SE widens 1.2%, from 0.1381 to 0.1398. **Smaller than I expected.** The
reason: only 6 of the 39 headline families share a sponsor with another
family in the sample — Blackstone, Bridgepoint, Carlyle, Permira, Silver Lake
and TPG, each contributing exactly two families. 27 sponsors are singletons,
so most of the clustering structure is unchanged. The estimate rests on
**33 sponsors rather than 39 families**.

Across the whole panel the compression is much larger: 330 families → 216
sponsors. It only fails to matter here because the multi-family sponsors
mostly sit outside the adjacent-and-mature subsample.

### Judgement calls in the mapping

The leading-token rule is deliberately crude, for the same reason
`normalise_firm_ids` is — a cleverer rule fails in ways nobody can audit. It
is wrong in four identifiable ways, all hand-recorded:

1. **Two firms sharing a first word.** General Atlantic and General Catalyst
   are unrelated; the rule pools them. Same for The Rise Fund and The Veritas
   Capital Fund once "The" is stripped.
2. **The Rise Fund is TPG-sponsored but recorded as its own sponsor**
   (`TPG RISE`, medium confidence). TPG raises it, but it is governed as a
   separate impact platform with its own investment committee, so pooling it
   with TPG's buyout families would overstate the dependence. Arguable either
   way; flagged as such.
3. **CalPERS programme labels are not manager names.** "California Asia
   Investors", "CalPERS Corporate Partners" and their siblings are named for
   the LP, not the GP, and are run by different outside managers. Each is
   recorded as its own sponsor so the rule does not invent a seven-family
   "CALIFORNIA" firm.
4. **Wigmore Street and BDC are both Bridgepoint.** The Wigmore Street
   vehicles co-invest alongside Bridgepoint Development Capital funds. Mapped
   to `BRIDGEPOINT`, which is what puts Bridgepoint into the headline sample's
   multi-family list.

`SILVER LAKE PARTNERS` and `SILVER LAKE TECHNOLOGY INVESTORS` derive to
sponsor `SILVER`, which groups correctly but reads badly in a table, so both
are relabelled `SILVER LAKE`.

Tests: 191 → 200.

---

## Item 2. Roman-numeral diagnostic — done. Pair count unchanged.

`analysis/diagnose_numerals.py` → `data/numeral_diagnostic.csv`. Run across
459 CalPERS names and 490 distinct Oregon names: **148 suspect names, 11 with
a share-class letter consumed as a numeral.**

### A correction to the override file's own reasoning

The three BDC override rows say the class letter was consumed "as roman
numeral 100 / 500". Half right. The strip uses the character class
**`[IVXLC]`**, so **C, I, L, V and X are at risk — D and M are not**, despite
being roman digits, because they are absent from the class. `BDC IV D LP`
keeps its D and strands the number for a different reason (the trailing letter
blocks the strip rather than being eaten by it). There are parametrised tests
pinning both halves of this.

### The 11 consumed-letter cases

| source | name | stem | ate |
|---|---|---|---|
| CalPERS | BDC III C LP | BDC III | C |
| CalPERS | BDC V C LP | BDC V | C |
| CalPERS | Blackstone Tactical Opportunities Fund II - C | …FUND II - | C |
| CalPERS | Genstar X Opportunities Fund I | GENSTAR X OPPORTUNITIES FUND | I |
| CalPERS | Genstar XI Opportunities Fund I | GENSTAR XI OPPORTUNITIES FUND | I |
| Oregon | Advent International GPE VII C | ADVENT INTERNATIONAL GPE VII | C |
| Oregon | Advent Latin American PE Fund VI C | …FUND VI | C |
| Oregon | Genstar VIII Opportunities Fund I | GENSTAR VIII OPPORTUNITIES FUND | I |
| Oregon | Genstar IX Opportunities Fund I | GENSTAR IX OPPORTUNITIES FUND | I |
| Oregon | Genstar X Opportunities Fund I | GENSTAR X OPPORTUNITIES FUND | I |
| Oregon | Pathway PE Fund III-Co Series C | …SERIES | C |

All five CalPERS cases were already fixed by existing overrides. The six
Oregon ones are new, but Oregon does not enter the persistence regression, so
they change no estimate.

### Pair count: unchanged at 129 lagged / 65 headline

68 stems still carry a stranded number and no override — 22 CalPERS, 46
Oregon. I checked every one of the 22 CalPERS stems for a sibling whose
de-numbered form matches, which is what a genuine split looks like.
**All 22 are singletons.** Merging any of them would produce a one-fund family
contributing zero pairs.

The one apparent exception is `WIGMORE STREET VI CO-INVESTMENT NO` and
`WIGMORE STREET CO-INVESTMENT NO`, which do share a de-numbered form. I left
them separate: the four Wigmore Street vehicles are co-investment sleeves each
tied to a *different* Bridgepoint fund (BDC III, BDC IV, Bridgepoint Europe
VI, and one unnamed), not consecutive funds in one series. Merging them would
manufacture a sequence out of four unrelated sleeves. Item 1's sponsor layer
already handles their dependence correctly by putting all four under
`BRIDGEPOINT`.

**So: no overrides added, and I am reporting that as the finding.** The
existing override file already catches every genuine CalPERS split this
diagnostic can find.

### One thing this did surface, for item 9

CalPERS writes `Advent International GPE VII-C` (hyphen) and Oregon writes
`Advent International GPE VII C` (space). The hyphen blocks the strip and the
space lets the C be eaten, so the two plans produce **different stems for the
same fund** — `ADVENT INTERNATIONAL GPE VII-C` against
`ADVENT INTERNATIONAL GPE VII`. The overlap matcher keys on the raw stem, so
Advent pairs are being silently lost from the cross-plan sample. Carried into
item 9.

Tests: 200 → 212.

---

## Item 3. VIP override — verified, upgraded to high confidence

The row's own reason said "confirm the sponsor before publishing", which is
not something to ship. Confirmed against Oregon PERS, which lists the same two
funds under their full name.

| | CalPERS | Oregon |
|---|---|---|
| fund IV name | VIP IV LP | Vitruvian Investment Partnership IV |
| fund IV vintage | 2020 | 2020 |
| fund IV TVPI | 1.378637 | 1.373163 |
| fund IV net IRR | 0.110 | 0.109 |
| fund V name | VIP V S.C.Sp. | Vitruvian Investment Partnership V |
| fund V TVPI | **0.974435** | **0.974642** |
| fund V net IRR | not reported | not reported |

**VIP is Vitruvian Investment Partnership.** The fund V multiples agree to
0.02% and fund IV to 0.4%; both plans put fund IV at vintage 2020 and both
decline to report a fund V IRR. Two unrelated partnerships do not agree on a
multiple to four decimals. The SCSp form matches Vitruvian's Luxembourg
domicile, as the queue suspected. CalPERS holds no other fund whose name
contains "Vitruvian", so there is no competing candidate.

Upgraded `medium` → `high` with the evidence written into the reason field.
The estimate does not move: VIP contributes one lagged pair either way, and it
was already being merged.

Incidental: CalPERS dates fund V to 2023 and Oregon to 2022 — another instance
of the +1 vintage disagreement pattern, relevant to items 4 and 5.

**11 medium-confidence merges remain** (BDC ×3, General Catalyst Health
Assurance ×2, Genstar Opportunities ×2, Lightspeed Inception/Ignite ×4). None
carries a "confirm before publishing" caveat; they are judgement calls about
whether paired vehicles form one series, stated as such.

---

## Item 4. Vintage-year methodology — half confirmed, half not reachable

### Neither plan publishes a definition

The Oregon PDF carries exactly two footnotes — one on secondary sales, one on
"NM" — and defines the other columns nowhere. "Vintage Year" is a bare column
header. The CalPERS page mentions vintage only in passing ("Funds with a
vintage year of 2021 or later are in the initial stages…") and never says what
it means. I tried the obvious CalPERS methodology and glossary pages
(`/private-equity-program`, `/asset-classes/private-equity`, `/glossary`):
404, 403 and 404 respectively. The Oregon holdings page contains no mention of
the word at all.

**So the documented answer does not exist in reachable sources.** Rather than
stop there, I tested the hypothesis against the data.

### Oregon: refuted, and cleanly

The snapshot archive contains 63 funds observed from inception — zero paid-in
at first appearance, so Oregon's own first capital call is *inside* the
observation window and can be dated by differencing. Comparing that against
Oregon's reported vintage:

| Oregon first-call year − reported vintage | funds |
|---|---|
| 0 | 31 |
| +1 | 22 |
| +2 | 6 |
| +3 | 2 |
| +6 | 1 |
| +7 | 1 |

**Oregon does not define vintage as its own first capital call.** If it did,
the gap would be identically zero; it is non-zero for 32 of 63 funds. The gap
is also never negative, which is what you would expect if the reported vintage
is the fund's own vintage or first close and Oregon draws capital at or after
it. So the Oregon half of the hypothesis is refuted, and the reported field
behaves like a genuine fund vintage.

### CalPERS: consistent with the hypothesis, not confirmable

Across the 43 aligned cross-plan pairs, CalPERS' vintage is **never earlier**
than Oregon's — 25 equal, 14 one year later, 4 two years later. Strict
one-sidedness is the point: if both plans were reporting the same quantity
with clerical noise, disagreements would be roughly symmetric. They are not,
so the difference is definitional rather than random.

Given Oregon reports the fund's vintage, CalPERS must be reporting something
systematically later — its own first capital call and its own commitment date
are both consistent with the pattern, and I cannot separate them. CalPERS
publishes cumulative totals only, with no dated flows and no archive of prior
quarters, so the test that worked for Oregon cannot be run.

**Stated conclusion: Oregon reports the fund's vintage; CalPERS reports
something one to two years later that cannot be identified from public data.**
That is enough for item 5 — the direction of the label error is established
even though its exact definition is not.

---

## Item 5. Vintage-error bias direction — the stated reasoning is WRONG

`analysis/simulate_vintage_error.py`. The queue's hypothesis was that
mislabelled vintages leave correlated market shocks in the residual, inflating
apparent persistence and making 0.214 an **upper** bound.

**The simulation says the opposite.** Displaced labels *attenuate* beta.

| true β | β with true labels | β with displaced labels | bias | share inflated |
|---|---|---|---|---|
| 0.00 | +0.017 | +0.016 | −0.001 (MC se 0.009) | 47.8% |
| 0.25 | +0.264 | +0.226 | **−0.038** (se 0.008) | 39.0% |
| 0.50 | +0.511 | +0.441 | **−0.070** (se 0.008) | 33.8% |

400 replications each, panel shaped like the real sample (39 families, mostly
two funds, four years apart), labels displaced by the observed CalPERS pattern
— 58% unchanged, 33% at +1, 9% at +2.

### Why the intuition fails

The argument tracks the residual and forgets the regressor. An imperfectly
absorbed vintage shock lands in **y_lag** as well as in y, and a noisy
regressor attenuates — classical errors-in-variables, which dominates the
correlated-residual channel.

This is the same mechanism the project already documents for *omitting*
vintage fixed effects entirely, where the README notes beta falls rather than
rises. Mislabelling is a partial version of omitting, and it behaves like one.
The two findings are consistent; the queue's hypothesis was not consistent
with either.

### Magnitude

Bias is **proportional, roughly −14% of beta** (−14.4% at β=0.25, −13.7% at
β=0.50), and essentially zero at β=0 — exactly the signature of multiplicative
attenuation, which has nothing to act on when there is no persistence.

Applied to the real estimate: 0.214 corrects to about **0.25**. That is a
quarter of one standard error (0.138) and changes no conclusion — the interval
still comfortably includes zero.

**So β = 0.214 is a LOWER bound with respect to vintage-label error, not an
upper bound.** RESULTS.md limitation 4 needs the direction stated this way.
There are five tests pinning it, including one asserting the sign of the bias,
so the write-up cannot drift back to the intuition.

Tests: 212 → 217.

---

## Item 6. Minimum detectable effect — the strongest result in the project

`analysis/minimum_detectable_effect.py` → `data/minimum_detectable_effect.csv`.

Power computed on the **actual** estimation sample: real y_lag values, real
vintage dummies, real family sizes. The outcome is rebuilt for each candidate
beta as `beta*y_lag + fitted_vintage + w_g*residual`, resampling the real
residuals with cluster-level Rademacher signs so the true within-family
dependence is preserved rather than assumed. Each replication is tested exactly
as the headline is tested — wild cluster bootstrap, 5%, two-sided.

| true β | power (family) | power (sponsor) |
|---|---|---|
| 0.0 | 0.057 | 0.057 |
| 0.1 | 0.067 | 0.090 |
| 0.2 | 0.187 | 0.257 |
| 0.3 | 0.457 | 0.470 |
| 0.4 | 0.723 | 0.743 |
| 0.5 | 0.940 | 0.933 |
| 0.6 | 0.997 | 0.997 |

**MDE at 80% power: β ≈ 0.435 (family clustering), 0.430 (sponsor).**

Size at β = 0 is 0.057 against a nominal 5%, so the curve is not flattered by a
miscalibrated test. Using the analytic p-value instead would have overstated
power, since it over-rejects at this cluster count.

### Why this is the most useful thing here

**Power at the coefficient actually estimated is ~19%.** If β really is 0.214,
failing to reject was the most likely outcome — roughly four times in five.

**The detectable effect is a pre-2000 magnitude.** Kaplan-Schoar-era
coefficients on log performance sit around 0.4–0.6; the post-2000 literature
(Harris-Jenkinson-Kaplan, Braun-Jenkinson-Stoff) puts persistence well below
0.15 and often cannot reject zero. Against 0.15 this design has roughly 8%
power.

So the finding is not "no persistence". It is **"this design could only have
detected persistence of the size reported before 2000, and had essentially no
chance of detecting the size the modern literature reports"** — a statement
about 39 clusters rather than about private equity. That is far stronger than
an imprecise null, exactly as the queue anticipated.

Sponsor clustering barely moves the curve (0.430 vs 0.435), consistent with
item 1: only 6 of 39 families share a sponsor.

### Caveat I want flagged

The literature figures are **from memory and approximate**, and the studies are
not strictly comparable — they differ in dependent variable, lag definition and
sample construction. I have used them to place an order of magnitude, and
RESULTS.md says so explicitly. Anyone relying on the comparison should check
the specific coefficients against the papers.

Added to RESULTS.md as its own section and to the README's ninety-second
summary. Limitation 1 now points at the power figure instead of just asserting
imprecision.

Tests: 217 → 221.

---

## Item 7. Three RESULTS.md corrections — done

**(a) Correlation and reliability were run together.** The old text said "log
TVPI correlates 0.944 across plans… the implied reliability ratio of 0.944",
as though the second followed from the first. They are different quantities.
They do coincide here, and not by accident — for two *parallel* measurements
the correlation equals the reliability ratio — but only if the two reports
have equal error variance and their errors are independent. **The independence
condition fails**: both plans receive the same GP valuation, so their errors
share a large common component, which inflates the correlation above the true
reliability. RESULTS.md now separates the two, states the assumptions, and says
which one is doubtful. λ is estimated from the variance of the paired
differences, never read off the correlation.

**(b) λ = 0.98 is now the headline, 0.944 the sensitivity.** The full-sample
figure is driven by a single pair in 43 — Tailwind Capital Partners III, a 68%
disagreement — and one observation should not set a variance estimate.
Correction is now stated as 1.02× (β 0.214 → 0.219) with 1.06× as the
sensitivity. The independent route, restricting to the 25 pairs that agree on
vintage, gives λ = 0.980 and corroborates it.

**(c) Row 9 relabelled as a precision loss.** Restricting to families with 3+
funds halves β to 0.148, which reads like evidence against persistence. It is
not: the restriction drops 21 of 39 families and nearly doubles the standard
error (0.138 → 0.211), so the interval is *wider in both directions*. New
paragraph says the sub-sample is too small to speak, rather than that
persistence is absent in it.

README updated to match on (a) and (b).

**Left inconsistent on purpose:** `run_overlap.py` still prints the
full-sample λ as its headline. Item 9 investigates Tailwind and may remove the
pair outright, in which case the full-sample figure *becomes* 0.98 and no
sensitivity framing is needed. Reconciling the script before knowing that
outcome would mean doing it twice.

---

## Item 8. Repo organisation — done

Root is now exactly: `README.md`, `RESULTS.md`, `DEVELOPMENT_LOG.md`,
`CLAUDE.md`, `run_all.sh`, `pyproject.toml`, `requirements.txt`, and five
folders (`analysis/`, `data/`, `figures/`, `src/`, `tests/`).

`WORK_BRIEF.md`, `OVERNIGHT_QUEUE.md` and `DATA_SOURCES.md` moved to
`.project/`. They are instructions to the assistant, not deliverables, and a
reader landing on the repo should not meet a task queue before the result.
`NOTES.md` renamed `DEVELOPMENT_LOG.md` and given a proper header.

**Before moving DATA_SOURCES, the genuinely useful half was folded into a new
README "Data" section** — it documented things a reader needs and nothing else
recorded:

- The Oregon URL problem. Five naming conventions for the same quarterly
  report, one filed under the wrong year's folder, and the finding that
  templating gets 8 reports where reading the holdings page gets 18. This is
  the reason `fetch_oregon.py` discovers rather than constructs URLs, and it
  was previously written down only in a file about to be hidden.
- Why the archive is committed: Oregon rotates quarters off the site, and two
  dated snapshots are the only route to cash flows.
- The French benchmark: why a total-return series rather than an S&P price
  index (roughly two points a year of dividends, ~22% of terminal wealth over
  a ten-year fund life), the `-99`/`-99.99` missing codes that destroy a
  compounded series if read literally, and the Korteweg-Nagel point that the
  market factor is not the right risk benchmark for levered buyout portfolios.
- CalPERS' active-partnerships-only selection and its two-quarter reporting lag.

Also: `run_all.sh` now points at `DEVELOPMENT_LOG.md`, README's footer links to
it, and `.DS_Store` / `.Rhistory` are gitignored — both were sitting untracked
in the root.

Cross-references checked: the only remaining mentions of the moved files are
inside `.project/` itself, plus two comments in `test_repro.py` citing "WORK
BRIEF 2.2" as the origin of the seven specification rows, which is still an
accurate historical reference.

---

## Item 9. Tailwind Capital Partners III — solved. It is a secondary sale.

Not a matching error, and not ambiguous. Both plans hold the same fund; Oregon
sold its position and CalPERS did not.

| | CalPERS | Oregon |
|---|---|---|
| name | Tailwind Capital Partners III, L.P. | Tailwind Capital Partners III |
| commitment | $200.0m | $200.0m |
| contributions | $224.0m | $156.8m |
| distributions | $120.2m | $157.7m |
| **NAV** | **$258.9m** | **$0.0m** |
| TVPI | 1.693 | 1.006 |
| net IRR | 17.4% | 0.4% |
| **sold in secondary** | not published | **yes** |
| vintage | 2018 | 2017 |

Identical $200m commitments and the same fund name settle identity; the
one-year vintage gap is the familiar CalPERS +1 pattern from item 4. Oregon's
NAV is *exactly* zero and its `sold_secondary` flag is set. So Oregon's 1.006
is the price it got in a secondary sale, and CalPERS' 1.693 is a live carrying
mark on a position still held. **The 68% gap is the secondary discount, not
reporting noise.**

### This generalises, and it is the better fix

7 of the 43 aligned pairs are Oregon secondary sales. Every one has NAV of
exactly zero. The separation is stark:

| | pairs | median disagreement |
|---|---|---|
| both plans still holding | 36 | **0.82%** |
| Oregon sold in secondary | 7 | **9.94%** |

Twelve times larger. So `run_overlap.py` now excludes secondary sales as a
**principled rule**, not as outlier trimming — a realised transaction price and
a live NAV mark are not two measurements of one quantity, and Oregon's own
footnote says exactly that. Only Oregon publishes the flag; CalPERS lists
active partnerships only, so a fund it had sold would be absent from its table
rather than present and mismarked.

### Effect

| | before | after |
|---|---|---|
| comparable pairs | 43 | 36 |
| cross-plan correlation | 0.944 | 0.986 |
| median disagreement | 1.41% | 0.82% |
| largest disagreement | 68.3% (Tailwind III) | 13.2% (KKR European III) |
| **λ** | 0.944 | **0.986**, CI [0.963, 0.995] |
| correction | 1.06× | **1.014×** |

β 0.214 → 0.217. The vintage-agreeing subset gives λ = 0.988 independently.

**This supersedes the ad-hoc sensitivity from item 7(b).** I no longer need a
"drop the single largest gap" rule — that was a symptom-level patch for a
problem with a principled cause. The three routes (exclude secondary sales,
drop largest gap, keep vintage-agreeing pairs) all land near 0.98, which is
reassuring, but only the first has a reason behind it. RESULTS.md and the
README now state the exclusion and why.

This also retires the run's largest flagged uncertainty: Tailwind was listed in
the previous morning summary as the lowest-confidence item and the thing
driving the headline attenuation figure. Both are now resolved.

Tests: 221 → 224.
