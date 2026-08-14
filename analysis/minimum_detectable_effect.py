"""What size of persistence could this design actually have detected?

Run:  python analysis/minimum_detectable_effect.py

Produces data/minimum_detectable_effect.csv.

Why this matters more than the point estimate
---------------------------------------------
An imprecise null invites the reader to think the study was inconclusive. A
minimum detectable effect turns that into a specific, falsifiable claim: with
65 pairs across 39 families, persistence of size X would be found 80% of the
time, and anything smaller would usually be missed. If X sits above what the
literature reports for post-2000 funds, the honest summary is not "we found
nothing" but "this design could not have found what anyone claims is there",
which is a statement about the data rather than about the world.

Method
------
Power is computed on the *actual* estimation sample, not an idealised one. The
design matrix -- the real y_lag values, the real vintage dummies, the real
family sizes -- is held fixed. For a candidate beta the outcome is rebuilt as

    y* = beta * y_lag + (fitted vintage component) + w_g * residual_i

with w_g a Rademacher draw per cluster. Resampling the real residuals with
cluster-level signs preserves whatever within-family dependence is actually
present instead of assuming a variance-components form for it. Each replication
is then tested exactly as the headline is tested: wild cluster bootstrap, 5%,
two-sided. Power is the rejection rate.

Using the bootstrap rather than the analytic p-value matters. The analytic test
over-rejects at this cluster count, which would flatter power and understate
the detectable effect.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.base import load_firm_overrides  # noqa: E402
from pefund.persistence import _design, _prepare, wild_cluster_bootstrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_real_analysis import build_regime, raw_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

BETA_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
N_SIMS = 300
N_BOOT = 499


def power_at(
    panel: pd.DataFrame, beta: float, cluster_col: str,
    n_sims: int = N_SIMS, n_boot: int = N_BOOT, seed: int = 20240813,
) -> float:
    """Rejection rate at the 5% level when the true coefficient is `beta`."""
    df = _prepare(panel, (), True, (cluster_col,), 1, False, "power")
    y, X, codes, lag_idx = _design(df, (), True, cluster_col)

    # Restricted fit: everything except y_lag. Its residuals carry the real
    # within-family dependence.
    X_r = np.delete(X, lag_idx, axis=1)
    gamma = np.linalg.pinv(X_r.T @ X_r) @ X_r.T @ y
    fitted = X_r @ gamma
    resid = y - fitted
    lag = X[:, lag_idx]

    n_clusters = int(codes.max()) + 1
    rng = np.random.default_rng(seed)
    rejections = 0
    for _ in range(n_sims):
        weights = rng.choice((-1.0, 1.0), size=n_clusters)
        simulated = df.copy()
        simulated["y"] = beta * lag + fitted + weights[codes] * resid
        result = wild_cluster_bootstrap(
            simulated, "power", vintage_fe=True, cluster_col=cluster_col,
            max_gap=1, n_boot=n_boot, seed=int(rng.integers(1, 10**8)),
        )
        rejections += int(result.p_bootstrap < 0.05)
    return rejections / n_sims


def interpolate_mde(betas, powers, target=0.80):
    """Smallest beta reaching `target` power, linearly interpolated."""
    for i in range(1, len(betas)):
        if powers[i] >= target > powers[i - 1]:
            span = powers[i] - powers[i - 1]
            if span <= 0:
                return betas[i]
            return betas[i - 1] + (target - powers[i - 1]) / span * (
                betas[i] - betas[i - 1]
            )
    return np.nan


def main() -> None:
    panel, _ = build_regime(raw_table(), load_firm_overrides())
    mature = panel[~panel["not_meaningful"].fillna(False).astype(bool)]
    sample = mature[
        (mature["fund_number_gap"] == 1)
        & mature["y"].notna()
        & mature["y_lag"].notna()
    ]
    print(f"Design: {len(sample)} pairs, {sample['firm_id'].nunique()} families, "
          f"{sample['sponsor_id'].nunique()} sponsors")
    print(f"{N_SIMS} replications per point, wild cluster bootstrap "
          f"({N_BOOT} draws), 5% two-sided\n")

    rows = []
    for cluster_col, label in (("firm_id", "family"), ("sponsor_id", "sponsor")):
        powers = []
        print(f"  clustered on {label}")
        for beta in BETA_GRID:
            power = power_at(mature, beta, cluster_col)
            powers.append(power)
            marker = "  <- size" if beta == 0 else ""
            print(f"    beta = {beta:.1f}   power = {power:.3f}{marker}")
            rows.append({"clustered_on": cluster_col, "beta": beta, "power": power})
        mde = interpolate_mde(BETA_GRID, powers)
        print(f"    MDE at 80% power: beta = {mde:.3f}\n")
        rows.append({"clustered_on": cluster_col, "beta": np.nan, "power": np.nan,
                     "mde_80": mde})

    pd.DataFrame(rows).to_csv(DATA / "minimum_detectable_effect.csv", index=False)
    print(f"Wrote {DATA / 'minimum_detectable_effect.csv'}")


if __name__ == "__main__":
    main()
