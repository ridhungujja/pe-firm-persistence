# NOTES.md — overnight run

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
