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
