# CLAUDE.md

Context for Claude Code sessions on this repository.

## What this project is

An empirical study of performance persistence among private equity general
partners, built as a portfolio piece for econometrics internship applications.
The deliverable is **an estimate with a standard error and an argument about
what it identifies** — not a dashboard, not a calculator. Anything that makes
this look more like a finance tool and less like an empirical paper is moving
in the wrong direction.

The owner is an undergraduate applying to econometrics internships. Explain
econometric reasoning rather than assuming it; explain terminal and git
mechanics rather than assuming them.

## The estimand

    y_{i,k} = alpha + beta * y_{i,k-1} + gamma' X_{i,k} + delta_v + u_{i,k}

`i` indexes the fund family, `k` the fund's sequence number within that
family, `delta_v` a vintage fixed effect. `y` is log TVPI (or log PME). Beta
is the object of interest: does a strong fund predict a strong successor?

Standard errors cluster on family (funds of one GP share a skill component)
and, where there are enough vintages, on vintage too.

## Current state

Working:
- `src/pefund/metrics.py` — TVPI/DPI/RVPI, XIRR, Kaplan-Schoar PME, Direct
  Alpha, Long-Nickels PME. Tested against analytically known cases.
- `src/pefund/persistence.py` — the estimator, vintage FE, clustered SEs,
  quartile transition matrices.
- `src/pefund/ingest/synthetic.py` — Takahashi-Alexander cash flow simulation
  with a known skill process, used to validate the estimator.
- `src/pefund/ingest/calpers.py` — scrapes and parses the live CalPERS table.
- `src/pefund/ingest/firms.py` — fund-family matching.
- `analysis/run_analysis.py` — validation run on simulated data.
- `analysis/fetch_calpers.py` — pulls real data to `data/calpers_snapshot.csv`.
- `analysis/run_real_analysis.py` — estimates on the real sample.

Not done:
- Only one data source. Oregon PERS, WSIB, and CalSTRS are the next targets.
- No PME on real data — CalPERS publishes cumulative totals, not dated flows.
- No write-up.

## Conventions

- Cash flows are signed from the LP's perspective: calls negative,
  distributions positive.
- Benchmarks must be **total-return** series. A price index silently inflates
  every PME.
- Performance enters regressions in logs.
- Persistence is measured within a **fund family** (Blackstone Capital
  Partners V-IX), not across everything a firm manages (Blackstone Tactical
  Opportunities is a separate series). This follows Kaplan-Schoar and it is
  deliberate — do not "fix" it by merging all of a firm's products.
- Metrics that cannot be computed return `NaN`, never a plausible-looking
  substitute. A bracketing failure in IRR is not a zero return.

## Rules

1. **Run `pytest -q` after every change.** 59 tests currently pass. A change
   that breaks one is wrong until proven otherwise.
2. **Do not weaken a test to make it pass.** If a test is wrong, say so and
   explain why before changing it.
3. **Do not delete the limitations.** The README's "Known limitations" and the
   warnings printed by the analysis scripts are the intellectual content of
   this project, not boilerplate to tidy away.
4. **New estimators need a validation path.** If you add one, add a case where
   the true answer is known and check that it is recovered.
5. Preserve the docstrings' explanations of *why*. They are what makes the
   repo legible to someone evaluating it.

## Known sample problems, in priority order

1. **Active partnerships only.** CalPERS drops fully exited funds, so old
   vintages that remain are survivors in a specific, non-random sense.
2. **Small n.** Roughly 100 lagged pairs. Confidence intervals are wide enough
   to be consistent with both strong persistence and none. Report the interval,
   do not bury it.
3. **Unrealised marks.** Most funds in the table are 2020s vintages carrying GP
   valuations rather than realisations. `not_meaningful` flags CalPERS' own
   view; specifications should be run with and without them.
4. **LP selection.** Only funds CalPERS chose to back are observed.
5. **Family matching.** `data/family_review.csv` needs a hand audit; corrections
   go in `data/firm_overrides.csv` with columns `fund_name,firm_id`.

Known matching issue: "Insight Venture Partners" and "Insight Partners" are
the same firm after a rename, and currently resolve to different families.

## Useful commands

```bash
source .venv/bin/activate
pytest -q
python analysis/fetch_calpers.py       # refresh real data
python analysis/run_real_analysis.py   # estimates on real data
python analysis/run_analysis.py        # validation on simulated data
```

## Next steps

1. Audit `data/family_review.csv`; write corrections to `firm_overrides.csv`.
2. Add a second pension plan to raise n and cross-check NAVs on overlapping
   funds.
3. Save dated snapshots each quarter so cash flows can be reconstructed by
   differencing, which unlocks PME on real data.
4. Write the paper: 800-1200 words, a regression table, and a limitations
   section that states plainly what the estimate does and does not identify.
