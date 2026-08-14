"""Persistence estimates on the real CalPERS sample. The headline output.

Run:  python analysis/fetch_calpers.py     # writes data/calpers_raw.csv
      python analysis/run_real_analysis.py

Produces:
    data/real_specifications.csv    the seven-row specification table
    data/mapping_robustness.csv     beta under three family-mapping regimes
    data/transition_test.csv        quartile transition permutation test
    data/transition_counts.csv      the cell counts behind it

What is estimated
-----------------
    y_{i,k} = alpha + beta * y_{i,k-1} + gamma' X + delta_v + u

y is log TVPI, i a fund family, k the fund's place in that family, delta_v a
vintage fixed effect. Standard errors cluster on family. Every row carries a
wild cluster bootstrap p-value alongside the analytic one; with roughly 75
families the cluster-robust asymptotic over-rejects, so where the two
disagree the bootstrap is the one to believe.

The headline row is row 3: mature funds only, adjacent funds only.
Adjacency is what makes beta the LP's actual decision problem -- fund k has
just been raised and fund k+1 is being marketed. Without it the regression
happily treats a 2007 fund as the immediate predecessor of a 2021 one,
because a single plan holds an arbitrary subset of any family's series, and
that estimates a different and much weaker claim.

Mapping regimes
---------------
The 70 merge decisions in firm_overrides.csv are researcher degrees of
freedom, so the whole table is re-run three ways: on the raw regex stems, on
high-confidence merges only, and on all merges. Each regime is rebuilt from
data/calpers_raw.csv rather than from the processed snapshot, because
share-class dedup keys on firm_id and so differs by regime.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.base import (  # noqa: E402
    add_sequence_numbers,
    apply_firm_overrides,
    deduplicate_share_classes,
    flag_vintage_anomalies,
    load_firm_overrides,
    normalise_firm_ids,
    parse_fund_number,
)
from pefund.persistence import (  # noqa: E402
    build_panel,
    estimate,
    quartile_transitions,
    results_table,
    transition_permutation_test,
    wild_cluster_bootstrap,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "calpers_raw.csv"

CLUSTER = ("firm_id",)
N_BOOT = 9999

pd.set_option("display.width", 150)
pd.set_option("display.max_columns", 40)
warnings.filterwarnings("ignore", message="invalid value encountered in sqrt")


def header(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def build_regime(raw: pd.DataFrame, overrides: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Run the full ingestion path under one family-mapping regime."""
    df = raw.copy()
    df["firm_id_raw"] = normalise_firm_ids(df)
    df["firm_id"] = apply_firm_overrides(df["firm_id_raw"], overrides)
    df["fund_number"] = parse_fund_number(df["fund_name"])

    n_rows = len(df)
    df, dedup = deduplicate_share_classes(df)
    df = add_sequence_numbers(df)
    df, _ = flag_vintage_anomalies(df)

    df["tvpi"] = df["total_value"] / df["contributions"]
    df = df[df["tvpi"].notna() & (df["contributions"] > 0)]

    metrics = df[["fund_id", "tvpi", "net_irr"]].copy()
    funds = df.drop(columns=["tvpi", "net_irr"])
    panel = build_panel(funds, metrics, "tvpi")

    funnel = {
        "published_rows": n_rows,
        "after_share_class_dedup": len(df) + len(dedup),
        "funds_with_tvpi": len(df),
        "families": df["firm_id"].nunique(),
        "families_2plus": int((df.groupby("firm_id").size() >= 2).sum()),
        "lagged_pairs": int(panel["y_lag"].notna().sum()),
    }
    return panel, funnel


def irr_panel(raw: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    """Same sample, but net IRR in levels as the dependent variable."""
    df = raw.copy()
    df["firm_id_raw"] = normalise_firm_ids(df)
    df["firm_id"] = apply_firm_overrides(df["firm_id_raw"], overrides)
    df["fund_number"] = parse_fund_number(df["fund_name"])
    df, _ = deduplicate_share_classes(df)
    df = add_sequence_numbers(df)
    df, _ = flag_vintage_anomalies(df)
    df = df[df["net_irr"].notna()]
    metrics = df[["fund_id", "net_irr"]].copy()
    funds = df.drop(columns=["net_irr"])
    return build_panel(funds, metrics, "net_irr", log=False)


def specification_rows(panel: pd.DataFrame, irr: pd.DataFrame) -> list[dict]:
    """The seven specifications, each with analytic and bootstrap inference."""
    mature = panel[~panel["not_meaningful"].fillna(False).astype(bool)]

    specs = [
        ("1. All funds, vintage FE", panel, dict()),
        ("2. Mature only, vintage FE", mature, dict()),
        ("3. Mature, adjacent funds only  [HEADLINE]", mature, dict(max_gap=1)),
        ("4. Row 3 + log commitment", mature,
         dict(max_gap=1, controls=("log_commitment",))),
        ("5. Row 3 + fund number", mature, dict(max_gap=1, controls=("fund_number",))),
        ("6. Row 3, excluding vintage anomalies", mature,
         dict(max_gap=1, drop_vintage_anomalies=True)),
        ("7. Row 3, dependent = net IRR",
         irr[~irr["not_meaningful"].fillna(False).astype(bool)], dict(max_gap=1)),
    ]

    rows = []
    for name, data, kwargs in specs:
        try:
            fit = estimate(data, name, vintage_fe=True, cluster_on=CLUSTER, **kwargs)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: NOT ESTIMABLE -- {exc}")
            rows.append({"specification": name, "beta": np.nan, "note": str(exc)[:80]})
            continue

        row = fit.as_row()
        try:
            boot = wild_cluster_bootstrap(
                data, name, vintage_fe=True, cluster_col=CLUSTER[0],
                n_boot=N_BOOT, **kwargs
            )
            row["p_bootstrap"] = round(boot.p_bootstrap, 4)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: bootstrap failed -- {exc}")
            row["p_bootstrap"] = np.nan

        ci_low = fit.beta - 1.96 * fit.se
        ci_high = fit.beta + 1.96 * fit.se
        row["ci95_low"] = round(ci_low, 4)
        row["ci95_high"] = round(ci_high, 4)
        row["includes_zero"] = bool(ci_low <= 0 <= ci_high)
        rows.append(row)
    return rows


def main() -> None:
    if not RAW.exists():
        raise SystemExit(f"{RAW} not found; run: python analysis/fetch_calpers.py")

    raw = pd.read_csv(RAW)
    all_overrides = load_firm_overrides()
    high_conf = all_overrides[
        (all_overrides["decision"] == "keep_separate")
        | (all_overrides["confidence"] == "high")
    ]
    empty = all_overrides.iloc[0:0]

    regimes = {
        "regex only (no overrides)": empty,
        "high-confidence merges": high_conf,
        "all merges": all_overrides,
    }

    # ------------------------------------------------------------- funnel
    panel, funnel = build_regime(raw, all_overrides)
    irr = irr_panel(raw, all_overrides)

    header("Sample funnel (all merges)")
    labels = {
        "published_rows": "rows published by CalPERS",
        "after_share_class_dedup": "after share-class dedup",
        "funds_with_tvpi": "funds with a computable TVPI",
        "families": "distinct fund families",
        "families_2plus": "families with 2+ funds",
        "lagged_pairs": "lagged pairs (the estimation sample)",
    }
    for key, label in labels.items():
        print(f"  {label:38} {funnel[key]:5d}")
    adjacent = int(
        (panel["fund_number_gap"] == 1).sum()
    )
    print(f"  {'of which adjacent (gap = 1)':38} {adjacent:5d}")
    mature_adjacent = int(
        ((panel["fund_number_gap"] == 1)
         & ~panel["not_meaningful"].fillna(False).astype(bool)).sum()
    )
    print(f"  {'mature AND adjacent (headline row)':38} {mature_adjacent:5d}")

    # ------------------------------------------------- specification table
    header("Specification table  (y = log TVPI, SEs clustered on family)")
    rows = specification_rows(panel, irr)
    table = pd.DataFrame(rows)
    table.to_csv(DATA / "real_specifications.csv", index=False)
    show = [c for c in ["specification", "beta", "std_error", "ci95_low", "ci95_high",
                        "p", "p_bootstrap", "n_funds", "n_firms"] if c in table.columns]
    print(table[show].to_string(index=False))

    # ------------------------------------------------- mapping robustness
    header("Mapping robustness: headline specification under three regimes")
    robust = []
    for label, overrides in regimes.items():
        regime_panel, regime_funnel = build_regime(raw, overrides)
        regime_mature = regime_panel[
            ~regime_panel["not_meaningful"].fillna(False).astype(bool)
        ]
        try:
            fit = estimate(
                regime_mature, label, vintage_fe=True, cluster_on=CLUSTER, max_gap=1
            )
            boot = wild_cluster_bootstrap(
                regime_mature, label, vintage_fe=True, cluster_col=CLUSTER[0],
                max_gap=1, n_boot=N_BOOT
            )
            robust.append({
                "regime": label,
                "merges_applied": int((overrides["decision"] == "merge").sum()),
                "families": regime_funnel["families"],
                "lagged_pairs": regime_funnel["lagged_pairs"],
                "beta": round(fit.beta, 4),
                "std_error": round(fit.se, 4),
                "p_analytic": round(fit.pvalue, 4),
                "p_bootstrap": round(boot.p_bootstrap, 4),
                "n_obs": fit.n_obs,
                "n_families": fit.n_firms,
            })
        except Exception as exc:  # noqa: BLE001
            print(f"  {label}: NOT ESTIMABLE -- {exc}")
            robust.append({"regime": label, "beta": np.nan, "note": str(exc)[:80]})

    robust_table = pd.DataFrame(robust)
    robust_table.to_csv(DATA / "mapping_robustness.csv", index=False)
    print(robust_table.to_string(index=False))

    betas = robust_table["beta"].dropna()
    if len(betas) > 1:
        print(f"\n  spread across regimes: {betas.max() - betas.min():+.4f}")

    # ------------------------------------------------ transition matrices
    header("Quartile transitions, mature adjacent pairs (rows: predecessor)")
    mature = panel[~panel["not_meaningful"].fillna(False).astype(bool)]
    adjacent_pairs = mature[mature["fund_number_gap"] == 1]
    matrix = quartile_transitions(adjacent_pairs)
    if matrix.empty:
        print("  not estimable: too few funds per vintage to cut into quartiles")
    else:
        print(matrix.round(3).to_string())

    test = transition_permutation_test(adjacent_pairs)
    if np.isnan(test.p_value):
        print(f"\n  permutation test not run: only {test.n_pairs} pairs survive "
              "within-vintage quartile assignment")
    else:
        print("\n  cell counts")
        print(test.counts.to_string())
        print(f"\n  observed diagonal share {test.observed_diagonal:.3f}")
        print(f"  null mean               {test.null_mean:.3f} "
              f"(sd {test.null_sd:.3f})")
        print(f"  permutation p           {test.p_value:.4f}  "
              f"({test.n_pairs} pairs, {test.n_permutations} shuffles)")
        pd.DataFrame([test.as_row()]).to_csv(DATA / "transition_test.csv", index=False)
        test.counts.to_csv(DATA / "transition_counts.csv")

    # Widen to all pairs if adjacency leaves too little to say anything.
    if np.isnan(test.p_value) or test.n_pairs < 20:
        header("Transition test on ALL mature pairs (adjacency not imposed)")
        wider = transition_permutation_test(mature)
        if np.isnan(wider.p_value):
            print(f"  still not estimable: {wider.n_pairs} pairs")
        else:
            print(wider.counts.to_string())
            print(f"\n  observed diagonal {wider.observed_diagonal:.3f}, "
                  f"null {wider.null_mean:.3f}, p = {wider.p_value:.4f}, "
                  f"n = {wider.n_pairs}")

    print(f"\nWrote {DATA / 'real_specifications.csv'}, "
          f"{DATA / 'mapping_robustness.csv'}")


if __name__ == "__main__":
    main()
