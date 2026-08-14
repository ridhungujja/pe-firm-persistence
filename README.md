# Private equity fund performance: measurement and persistence

Estimating whether private equity general partners show persistent skill,
and measuring how far the answer moves when you fix the sample problems that
the data usually hides.

This is deliberately not a dashboard. The deliverable is an estimate with a
standard error and an argument about what it identifies.

## Why this framing

"Do good funds stay good?" is a question with a real empirical literature and
a known trajectory: Kaplan and Schoar (2005) found strong persistence in
buyout and venture returns; later work using better data and more careful
timing found it had weakened substantially after the early 2000s. Replicating
that arc requires panel methods, a defensible benchmark, and an honest
treatment of selection — which is what an econometrics supervisor wants to
see. A returns calculator demonstrates none of it.

## Quickstart

```bash
pip install -r requirements.txt
python -m pytest -q          # 130 tests
python analysis/run_analysis.py
```

The analysis script simulates a fund universe with a *known* skill process,
measures it with the same code path real data would use, and estimates
persistence under seven specifications.

## What is implemented

**Measurement** (`src/pefund/metrics.py`)

| Metric | Notes |
| --- | --- |
| DPI, RVPI, TVPI | Decomposition of realised vs unrealised value |
| IRR (XIRR) | Brent's method on irregular dates; returns NaN rather than a fake root when no sign change exists |
| Kaplan-Schoar PME | Index-discounted wealth ratio |
| Direct Alpha | Annualised excess return, comparable across horizons |
| Long-Nickels PME | Included with its known failure mode guarded |

Every metric is tested against a case with an analytic answer.

**Estimation** (`src/pefund/persistence.py`)

AR(1) in fund sequence number with vintage fixed effects and standard errors
clustered two-way on firm and vintage. The two-way clustered covariance
matrix is not guaranteed positive semi-definite; when it fails the code warns,
falls back to one-way clustering, and labels the specification so the change
cannot vanish into a results table. Quartile transition matrices are computed
within vintage, so a strong vintage cannot masquerade as a strong GP.

**Simulation** (`src/pefund/ingest/synthetic.py`)

Takahashi-Alexander commitment model for cash flow timing, latent GP skill,
vintage shocks, market loading, and endogenous fundraising. Since the true
persistence coefficient is `var(skill) / (var(skill) + var(idiosyncratic))`,
the estimator can be checked rather than trusted.

**Ingestion** (`src/pefund/ingest/base.py`)

Canonical schema, GP-name normalisation, sequence numbering, validation
flags, and reconstruction of quarterly flows by differencing consecutive
snapshots. Adapters target public pension disclosures — CalPERS, CalSTRS,
Oregon PERS, WSIB, TRS Texas — which are the free substitute for Preqin.

## Results on simulated data

True β = 0.219 by construction.

| Specification | β | SE | n |
| --- | --- | --- | --- |
| 1. No selection, final lag, vintage FE | 0.233 | 0.042 | 748 |
| 2. Selected sample, no vintage FE | 0.148 | 0.054 | 503 |
| 3. Selected sample, vintage FE | 0.232 | 0.059 | 503 |
| 4. + fund size control | 0.230 | 0.060 | 503 |
| 5. Lag known at fundraise | 0.261 | 0.064 | 503 |
| 6. Dependent variable = log PME | 0.232 | 0.059 | 503 |
| 7. Bottom quartile of outcome undisclosed | 0.147 | 0.047 | 367 |

Three things worth defending in an interview:

**Selection on the regressor is harmless; selection on the outcome is not.**
Spec 3 conditions the sample on the *predecessor* fund clearing a bar, and β
barely moves (−0.002). That is not a null result — truncating on a regressor
restricts its range but leaves E[y | y_lag] intact, so OLS stays consistent.
Spec 7 censors the *outcome* instead and β falls 37%. Most informal talk about
"survivorship bias in PE data" does not distinguish these, and the distinction
determines whether your estimate is usable.

**Omitting vintage fixed effects attenuates here rather than inflating.**
A GP's successive funds sit in different vintages, so the vintage shock enters
the lagged regressor as classical measurement error. The intuition that
omitted common shocks always flatter apparent skill is wrong in this DGP; the
sign depends on how vintage effects correlate across a firm's funds. Simulate
before asserting a direction.

**IRRs do not aggregate.** Averaging fund IRRs answers a different question
than pooling cash flows, and the script reports equal-weighted against
capital-weighted PME to make the gap visible.

## Roadmap for real data

1. Download fund tables from two or three plans. Run this locally — sandboxes
   with domain allowlists will block state pension domains.
2. Normalise GP identity. `normalise_firm_ids` is a first pass; hand-check the
   fifty largest firms and keep corrections in a version-controlled CSV. The
   persistence estimate is only as good as this mapping, and it is the single
   most labour-intensive step.
3. Build the benchmark from a total-return series, not a price index. A price
   index drops roughly two points a year of dividends and inflates every PME
   in the panel over a ten-year fund life.
4. Reconstruct quarterly flows by differencing snapshots if no cash flow file
   exists, and state in the write-up that within-quarter timing is lost.
5. Re-run the seven specifications and compare against the published
   literature estimates.

## Known limitations

- Funds younger than about five years are mostly unrealised GP marks; they are
  flagged, not dropped, and results should be shown both ways.
- Interim NAVs are stale and smoothed, which attenuates any estimate using
  early-life performance as the regressor.
- Public plan samples observe only funds those LPs committed to, so the
  universe is conditioned on ex-ante institutional attractiveness. This cannot
  be fixed with the available data and belongs in the limitations section, not
  in a footnote.
- The AR(1) framing assumes a clean fund ordering. Parallel vehicles raised in
  the same vintage break it and are flagged by `add_sequence_numbers`.

## References

- Kaplan, S. and Schoar, A. (2005). Private equity performance: returns,
  persistence, and capital flows. *Journal of Finance* 60(4).
- Harris, R., Jenkinson, T. and Kaplan, S. (2014). Private equity performance:
  what do we know? *Journal of Finance* 69(5).
- Korteweg, A. and Nagel, S. (2016). Risk-adjusting the returns to venture
  capital. *Journal of Finance* 71(3).
- Braun, R., Jenkinson, T. and Stoff, I. (2017). How persistent is private
  equity performance? Evidence from deal-level data. *Journal of Financial
  Economics* 123(2).
- Gredil, O., Griffiths, B. and Stucke, R. (2014). Benchmarking private
  equity: the direct alpha method.
- Takahashi, D. and Alexander, S. (2002). Illiquid alternative asset fund
  modeling. *Journal of Portfolio Management* 28(2).
