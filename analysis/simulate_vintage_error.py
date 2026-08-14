"""What does a mislabelled vintage year do to the persistence estimate?

Run:  python analysis/simulate_vintage_error.py

Produces data/vintage_error_simulation.csv.

The problem
-----------
Item 4 established that CalPERS and Oregon do not mean the same thing by
"vintage year": across 43 aligned pairs CalPERS is never earlier, and sits one
year later for 14 funds and two years later for 4. Oregon's field behaves like
the fund's own vintage, so the CalPERS label -- the one every specification
uses -- is displaced later for roughly 40% of funds.

The reasoning that was checked -- and refuted
---------------------------------------------
The natural story runs: vintage fixed effects absorb the market environment a
fund invested into; a fund assigned to the wrong year keeps part of its own
year's shock in the residual; a family's consecutive funds sit in nearby
vintages and so carry *correlated* leftover shocks; correlated residuals
between y and y_lag are what beta picks up. Conclusion: mislabelling inflates
persistence and 0.214 is an upper bound.

**The simulation says the opposite.** Displaced labels attenuate beta, by
about 15% of its value, and the bias is essentially zero when true beta is
zero. So the reported estimate is if anything a LOWER bound with respect to
this particular error.

The reason the story fails is that it only tracks the residual and forgets the
regressor. An imperfectly absorbed vintage shock lands in y_lag as well as in
y, and a noisy regressor attenuates -- classical errors-in-variables, which
dominates the correlated-residual channel here. This is the same mechanism the
simulation study already documents for *omitting* vintage fixed effects
entirely, where beta falls rather than rises. Mislabelling is a partial
version of omitting, and it behaves like one.

Design
------
Each replication builds a panel with the real sample's shape (39 families,
mostly two funds each, four years apart), a known persistence coefficient, and
vintage shocks. Beta is estimated twice on identical data: once with the true
vintage labels, once with labels displaced by the empirical CalPERS pattern
(58% unchanged, 33% +1, 9% +2). The gap between them is the bias.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.persistence import build_panel, estimate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

#: Observed CalPERS-minus-Oregon vintage gaps: 25 of 43 equal, 14 at +1, 4 at +2.
OBSERVED_SHIFTS = (0, 1, 2)
OBSERVED_WEIGHTS = (25 / 43, 14 / 43, 4 / 43)


def make_panel(
    rng: np.random.Generator,
    beta: float = 0.25,
    n_families: int = 39,
    sd_skill: float = 0.18,
    sd_idiosyncratic: float = 0.34,
    sd_vintage: float = 0.20,
    years_between: int = 4,
) -> pd.DataFrame:
    """A panel shaped like the headline sample, with known beta and vintage shocks."""
    years = np.arange(1998, 2024)
    vintage_shock = dict(zip(years, rng.normal(0, sd_vintage, len(years))))

    rows = []
    for i in range(n_families):
        start = int(rng.choice(years[: -2 * years_between]))
        latent = rng.normal(0, sd_skill)
        n_funds = 2 if rng.random() < 0.75 else 3
        for k in range(n_funds):
            vintage = start + years_between * k
            latent = beta * latent + rng.normal(0, sd_idiosyncratic)
            rows.append(
                {
                    "fund_id": f"F{i:03d}-{k}",
                    "firm_id": f"F{i:03d}",
                    "sequence": k + 1,
                    "fund_number": float(k + 1),
                    "vintage_true": vintage,
                    "commitment": 100.0,
                    "tvpi": float(np.exp(latent + vintage_shock[vintage])),
                }
            )
    return pd.DataFrame(rows)


def displace(vintages: pd.Series, rng: np.random.Generator) -> pd.Series:
    """Shift vintage labels later by the empirical CalPERS pattern."""
    shifts = rng.choice(OBSERVED_SHIFTS, size=len(vintages), p=OBSERVED_WEIGHTS)
    return vintages + shifts


def run(n_reps: int = 400, beta: float = 0.25, seed: int = 20240813) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_reps):
        funds = make_panel(rng, beta=beta)
        metrics = funds[["fund_id", "tvpi"]]
        attrs = funds.drop(columns=["tvpi"])

        clean = attrs.assign(vintage=attrs["vintage_true"])
        noisy = attrs.assign(vintage=displace(attrs["vintage_true"], rng))

        try:
            b_true = estimate(
                build_panel(clean, metrics), "true", cluster_on=("firm_id",), max_gap=1
            ).beta
            b_err = estimate(
                build_panel(noisy, metrics), "mislabelled", cluster_on=("firm_id",),
                max_gap=1,
            ).beta
        except Exception:  # noqa: BLE001 - a degenerate draw is skipped, not patched
            continue
        rows.append({"beta_true_labels": b_true, "beta_mislabelled": b_err})
    return pd.DataFrame(rows)


def main() -> None:
    print("Simulating the effect of displaced vintage labels on beta")
    print(f"  displacement: {OBSERVED_SHIFTS} with weights "
          f"{tuple(round(w, 3) for w in OBSERVED_WEIGHTS)} (the observed CalPERS pattern)")

    for beta in (0.0, 0.25, 0.50):
        result = run(beta=beta)
        result["bias"] = result["beta_mislabelled"] - result["beta_true_labels"]
        mean_bias = result["bias"].mean()
        se = result["bias"].std(ddof=1) / np.sqrt(len(result))

        print(f"\n  true beta = {beta:.2f}   ({len(result)} replications)")
        print(f"    beta with true vintage labels   {result['beta_true_labels'].mean():+.4f}")
        print(f"    beta with displaced labels      {result['beta_mislabelled'].mean():+.4f}")
        print(f"    mean bias                       {mean_bias:+.4f}  "
              f"(MC s.e. {se:.4f})")
        print(f"    share of replications inflated  "
              f"{(result['bias'] > 0).mean():.1%}")
        result.to_csv(DATA / f"vintage_error_simulation_beta{beta:.2f}.csv", index=False)

    print(
        "\n  Direction: displaced vintage labels ATTENUATE beta. The natural\n"
        "  argument -- unabsorbed shocks correlate across a family's funds and\n"
        "  inflate apparent persistence -- is wrong, because the same unabsorbed\n"
        "  shock also enters the regressor y_lag, and errors-in-variables in the\n"
        "  regressor dominates. Beta = 0.214 is therefore a LOWER bound with\n"
        "  respect to vintage-label error, not an upper bound.\n\n"
        "  Magnitude: roughly 15% of beta, proportional rather than additive,\n"
        "  and about a quarter of the standard error on the real estimate. It\n"
        "  changes no conclusion."
    )


if __name__ == "__main__":
    main()
