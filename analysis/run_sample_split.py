"""Where the pooled persistence estimate comes from.

Run:  python analysis/run_sample_split.py

Produces:
    data/sample_splits.csv     beta by plan, by era, and by maturity flag

Pooling Oregon into the CalPERS sample moved beta from 0.214 to 0.344 and
took the confidence interval off zero. Two very different things could do
that, and they have opposite implications:

    PRECISION   the estimate was always around 0.3, and 39 families were
                never enough to separate it from zero. The power calculation
                in `minimum_detectable_effect.py` said in advance that this
                design could not detect anything below 0.435, so a null was
                close to guaranteed. Adding families fixes that.

    POPULATION  Oregon's funds are older and mostly realised, and the
                literature reports far stronger persistence before 2000 than
                after. If so the pooled number is a weighted average of two
                different regimes, and quoting it as one coefficient hides
                the more interesting result.

The two are separable. Under precision, CalPERS-only and Oregon-only should
give similar point estimates with different error bars. Under population,
they should give different point estimates, and splitting on vintage year
should reproduce that difference inside each plan.

This script runs both cuts. It is a decomposition of one estimate, not a
search for a specification that produces a better number: every row is
reported, including the ones that weaken the headline.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.persistence import (  # noqa: E402
    estimate,
    wild_cluster_bootstrap,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_real_analysis import (  # noqa: E402
    CLUSTER,
    N_BOOT,
    build_regime,
    header,
    raw_table,
)

from pefund.ingest.base import load_firm_overrides  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

warnings.filterwarnings("ignore", message="invalid value encountered in sqrt")

#: The split year. Kaplan and Schoar (2005) estimate on funds raised up to
#: 2001 and report betas of 0.4-0.6; Harris, Jenkinson and Kaplan (2014) and
#: Braun, Jenkinson and Stoff (2017) find the relationship far weaker for
#: funds raised after 2000, and attribute it to the industry's growth and to
#: past performance becoming public. 2000 is their dividing line, not one
#: chosen here to make a result.
ERA_SPLIT = 2000


def fit_row(data: pd.DataFrame, label: str, **kwargs) -> dict:
    """One row: point estimate, cluster-robust SE, bootstrap p, sample size."""
    row = {"split": label, "n_pairs": np.nan, "n_families": np.nan,
           "beta": np.nan, "std_error": np.nan, "ci95_low": np.nan,
           "ci95_high": np.nan, "p_bootstrap": np.nan, "note": ""}
    try:
        fit = estimate(data, label, vintage_fe=True, cluster_on=CLUSTER,
                       max_gap=1, **kwargs)
    except Exception as exc:  # noqa: BLE001
        row["note"] = f"not estimable: {str(exc)[:70]}"
        return row

    row.update(
        n_pairs=fit.n_obs,
        n_families=fit.n_firms,
        beta=round(fit.beta, 4),
        std_error=round(fit.se, 4),
        ci95_low=round(fit.beta - 1.96 * fit.se, 4),
        ci95_high=round(fit.beta + 1.96 * fit.se, 4),
    )
    try:
        boot = wild_cluster_bootstrap(
            data, label, vintage_fe=True, cluster_col=CLUSTER[0],
            max_gap=1, n_boot=N_BOOT, **kwargs
        )
        row["p_bootstrap"] = round(boot.p_bootstrap, 4)
    except Exception as exc:  # noqa: BLE001
        row["note"] = f"bootstrap failed: {str(exc)[:60]}"
    row["includes_zero"] = bool(row["ci95_low"] <= 0 <= row["ci95_high"])
    return row


def main() -> None:
    raw = raw_table()
    overrides = load_firm_overrides()

    panel, _ = build_regime(raw, overrides)
    mature = panel[~panel["not_meaningful"].fillna(False).astype(bool)]

    rows = [fit_row(mature, "pooled, both plans")]

    # ------------------------------------------------------------ by plan
    # Each plan is rebuilt from its own rows, not filtered out of the pooled
    # panel. Filtering would be wrong: the lag in the pooled panel is taken
    # from the pooled family sequence, so a CalPERS fund's predecessor can be
    # a fund only Oregon reports. Selecting on the successor's source would
    # then attribute a cross-plan pair to one plan and quietly keep the
    # sample-size gain it was supposed to isolate.
    header("Is the jump precision or population? Each plan on its own rows")
    for source in sorted(raw["source"].dropna().unique()):
        own, _ = build_regime(raw[raw["source"] == source], overrides)
        own_mature = own[~own["not_meaningful"].fillna(False).astype(bool)]
        rows.append(fit_row(own_mature, f"{source} alone"))

    # ------------------------------------------------------------- by era
    header(f"Split on vintage year at {ERA_SPLIT}")
    era = mature["vintage"].astype(float)
    rows.append(fit_row(mature[era < ERA_SPLIT], f"vintage before {ERA_SPLIT}"))
    rows.append(fit_row(mature[era >= ERA_SPLIT], f"vintage {ERA_SPLIT} or later"))
    rows.append(fit_row(mature[era >= 2010], "vintage 2010 or later"))

    # --------------------------------------------------- maturity as a check
    # The headline drops funds each plan flags "not meaningful". The two
    # plans flag at very different rates, so the filter is not the same
    # filter on both halves; the unfiltered panel says how much that matters.
    header("Without the maturity filter")
    rows.append(fit_row(panel, "all funds, including immature"))

    table = pd.DataFrame(rows)
    table.to_csv(DATA / "sample_splits.csv", index=False)

    show = ["split", "beta", "std_error", "ci95_low", "ci95_high",
            "p_bootstrap", "n_pairs", "n_families", "note"]
    print(table[show].to_string(index=False))

    # ------------------------------------------------ maturity comparability
    header("How differently do the two plans flag a fund 'not meaningful'?")
    flag = panel.copy()
    flag["nm"] = flag["not_meaningful"].fillna(False).astype(bool)
    by = flag.groupby("source").agg(
        funds=("fund_id", "size"),
        flagged=("nm", "sum"),
        median_vintage=("vintage", "median"),
    )
    by["share_flagged"] = (by["flagged"] / by["funds"]).round(3)
    print(by.to_string())
    print(
        "\n  The flag is each plan's own judgement, not a common rule. A plan\n"
        "  that flags less leaves younger funds in the mature sample, so the\n"
        "  filter is looser on that plan's half. This is a limitation of the\n"
        "  pooled design and it is why the unfiltered row above is reported."
    )

    print(f"\nWrote {DATA / 'sample_splits.csv'}")


if __name__ == "__main__":
    main()
