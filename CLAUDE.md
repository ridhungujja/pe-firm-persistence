# CLAUDE.md

Context for Claude Code sessions on this repository.

## What this project is

An empirical study of performance persistence among private equity general
partners. The deliverable is **an estimate with a standard error and an
argument about what it identifies** — not a dashboard, not a calculator.
Anything that makes this look more like a finance tool and less like an
empirical paper is moving in the wrong direction.

Explain econometric reasoning rather than assuming it; explain terminal and
git mechanics rather than assuming them.

## The estimand

    y_{i,k} = alpha + beta * y_{i,k-1} + gamma' X_{i,k} + delta_v + u_{i,k}

`i` indexes the fund family, `k` the fund's sequence number within that
family, `delta_v` a vintage fixed effect. `y` is log TVPI (or log PME). Beta
is the object of interest: does a strong fund predict a strong successor?

Standard errors cluster on family (funds of one GP share a skill component)
and, where there are enough vintages, on vintage too. With roughly 75 families
the cluster-robust asymptotics are borderline, so the wild cluster bootstrap
is the primary inference — see `wild_cluster_bootstrap`.

## Repository map

```
src/pefund/
  metrics.py            TVPI/DPI/RVPI, XIRR, Kaplan-Schoar PME, Direct Alpha,
                        Long-Nickels PME. Tested against analytic cases.
  persistence.py        The estimator: vintage FE, clustered SEs, fund-number
                        gaps, wild cluster bootstrap, quartile transitions.
  ingest/base.py        Canonical schema; family matching (normalise_firm_ids,
                        firm overrides); parse_fund_number; share-class dedup;
                        vintage-anomaly diagnostic; flow reconstruction;
                        funds_observed_from_inception.
  ingest/calpers.py     Live CalPERS HTML table.
  ingest/oregon.py      Oregon PERS quarterly PDFs (pdfplumber).
  ingest/french.py      Kenneth French factors -> total-return index for PME.
  ingest/synthetic.py   Takahashi-Alexander simulation with known skill, used
                        to validate the estimator.

analysis/
  fetch_calpers.py      Live CalPERS pull -> data/calpers_snapshot.csv
  fetch_oregon.py       Oregon PDF archive -> data/snapshots/
  build_family_review.py  Family-matching worksheet -> data/family_review.csv
  run_analysis.py       Validation run on SIMULATED data.
  run_pme.py            Cash-flow reconstruction and PME on the Oregon archive.
```

Note there is no `ingest/firms.py`: family matching lives in `ingest/base.py`.

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
  substitute. A bracketing failure in IRR is not a zero return. PME on a fund
  whose early cash flows predate the snapshot archive is not a number.
- Money is stored in dollars. Oregon publishes millions and the adapter
  converts, so the two plans are unit-compatible.

## Rules

1. **Run `pytest -q` after every change.** 130 tests currently pass. A change
   that breaks one is wrong until proven otherwise.
2. **Do not weaken a test to make it pass.** If a test is wrong, say so and
   explain why before changing it.
3. **Do not delete the limitations.** The README's "Known limitations", the
   Oregon disclaimer carried in `ingest/oregon.py`, and the warnings printed by
   the analysis scripts are the intellectual content of this project, not
   boilerplate to tidy away.
4. **New estimators need a validation path.** If you add one, add a case where
   the true answer is known and check that it is recovered. The bootstrap's
   validation is its size under a true null; the parsers' is the published
   total each report prints for itself.
5. Preserve the docstrings' explanations of *why*. They are what makes the
   repo legible to someone evaluating it.

## data/firm_overrides.csv

Hand-checked corrections to `normalise_firm_ids`, keyed on the **raw regex
stem** rather than the fund name, so one row repairs a whole series.

    firm_id_raw,firm_id_canonical,decision,confidence,reason

`decision` is `merge` or `keep_separate`. A `keep_separate` row maps a stem to
itself; it is a no-op that records the family was inspected and deliberately
left alone, so a later pass does not "helpfully" merge it. The loader rejects
duplicate stems and chained merges (A→B and B→C), which would make the result
depend on row order. Comment lines start with `#`.

The regex fails almost entirely in one direction: share classes, feeder tags
and domicile suffixes sitting after the fund number block the numeral strip
and scatter one series across several stems. It essentially never merges two
distinct strategies. Overrides are therefore mostly merges.

## data/snapshots/ is committed

Unusually for generated data, the snapshot archive is tracked in git. Oregon
rotates old quarters off its site — 8 of 52 probed URLs were still live — so a
dated snapshot that is lost cannot be re-fetched. Two or more snapshots of the
same funds are also the only route to cash flows, since both plans publish
cumulative totals rather than dated flows. Never overwrite one. The raw PDFs
live in `data/snapshots/raw/`.

Everything else generated (`calpers_snapshot.csv`, `family_review.csv`,
`fund_metrics.csv`, `persistence_results.csv`, `share_class_dedup.csv`,
`vintage_anomalies.csv`, `oregon_pme.csv`) is gitignored and rebuilt by the
analysis scripts. `firm_overrides.csv` is an input and is committed.

## Known sample problems, in priority order

1. **Active partnerships only.** CalPERS drops fully exited funds, so old
   vintages that remain are survivors in a specific, non-random sense.
2. **Small n.** Roughly 130 lagged pairs across ~75 families. Confidence
   intervals are wide enough to be consistent with both strong persistence and
   none. Report the interval, do not bury it.
3. **Unrealised marks.** Most funds in both tables are 2020s vintages carrying
   GP valuations rather than realisations. `not_meaningful` flags each plan's
   own view; specifications should be run with and without them.
4. **LP selection.** Only funds these particular plans chose to back are
   observed.
5. **PME coverage.** The Oregon archive starts 2023-12-31, so only funds that
   had drawn no capital by then have a recoverable flow history. That is a
   small, young subsample; the rest are NaN by design.
6. **Secondary sales.** Oregon flags funds sold in the secondary market. Their
   performance is a transaction outcome, not a realisation.

## Useful commands

```bash
source .venv/bin/activate
pytest -q
python analysis/fetch_calpers.py         # refresh CalPERS
python analysis/fetch_oregon.py          # refresh the Oregon PDF archive
python analysis/build_family_review.py   # family-matching worksheet
python analysis/run_pme.py               # PME on the Oregon archive
python analysis/run_analysis.py          # validation on simulated data
```

## Not done

- No real-data specification table yet; `run_analysis.py` is simulation-only.
- No cross-plan measurement-error estimate from the CalPERS/Oregon overlap.
- No figures, no write-up.
