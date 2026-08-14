"""Cross-plan measurement error from the CalPERS/Oregon overlap.

Run:  python analysis/run_overlap.py

Produces data/overlap_pairs.csv and data/attenuation.csv.

The idea
--------
A fund held by two plans is one underlying partnership reported twice. The
spread between the two reports is a direct observation of reporting noise,
which is otherwise invisible: with one source you cannot separate a fund that
truly returned 1.5x from a fund that returned 1.4x and was reported as 1.5x.

Under classical measurement error in the regressor, OLS is attenuated by

    lambda = var(true) / (var(true) + var(error))

and beta_corrected = beta_raw / lambda. With two independent reports of the
same quantity, var(error) = var(difference) / 2, which makes lambda estimable
rather than assumed.

Alignment
---------
Only reports with the SAME as-of quarter are compared. CalPERS publishes with
a reporting lag and its page carries its own as-of date, which the adapter now
parses rather than stamping the download date. Comparing a CalPERS Q3 figure
against an Oregon Q1 figure would measure two quarters of NAV growth and call
it reporting error, and that number would then be divided into beta.

What this is NOT
----------------
Both plans are limited partners in the same partnership and receive the same
GP-reported valuation. They are not independent appraisals. Differences arise
from fee terms negotiated at different closes, from entering at different
times, from each plan's own share of the fund, and from rounding -- CalPERS
reports whole dollars, Oregon reports millions to one decimal.

So this estimates a FLOOR on reporting noise, not the whole of it. The part
that matters most for persistence -- that a GP's carrying values are stale and
smoothed relative to what the assets would fetch -- is common to both reports
and therefore invisible here. The corrected beta below is a lower bound on the
correction, not the corrected truth.
"""

from __future__ import annotations

import sys
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
from pefund.persistence import build_panel, estimate  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_real_analysis import raw_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SNAPSHOTS = DATA / "snapshots"


def header(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def keyed(df: pd.DataFrame) -> pd.DataFrame:
    """Add the (family stem, fund number) matching key.

    The raw regex stem is used rather than the override-corrected family id.
    The overrides were hand-checked against CalPERS spellings; applying them
    to Oregon's slightly different names would map one plan and not the other
    and destroy matches rather than create them.
    """
    out = df.copy()
    out["stem"] = normalise_firm_ids(out)
    out["fund_number"] = parse_fund_number(out["fund_name"])
    return out


def attenuation(
    log_a: np.ndarray, log_b: np.ndarray
) -> dict:
    """Reliability ratio from two reports of the same quantity."""
    difference = log_a - log_b
    var_error = float(np.var(difference, ddof=1) / 2.0)

    # The best available estimate of the fund's true log TVPI is the average
    # of the two reports; its variance overstates var(true) by var(error)/2.
    average = (log_a + log_b) / 2.0
    var_average = float(np.var(average, ddof=1))
    var_true = max(var_average - var_error / 2.0, 0.0)

    lam = var_true / (var_true + var_error) if (var_true + var_error) > 0 else np.nan
    return {
        "n_pairs": len(difference),
        "var_error": var_error,
        "var_true": var_true,
        "lambda": lam,
        "sd_error_log": float(np.sqrt(var_error)),
        "mean_abs_log_diff": float(np.mean(np.abs(difference))),
        "median_abs_pct_diff": float(np.median(np.abs(np.expm1(difference)))),
    }


def bootstrap_lambda(log_a, log_b, n_boot=9999, seed=20240813):
    """Percentile interval for lambda. 43 pairs is a thin variance estimate."""
    rng = np.random.default_rng(seed)
    n = len(log_a)
    draws = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        result = attenuation(log_a[idx], log_b[idx])
        if np.isfinite(result["lambda"]):
            draws.append(result["lambda"])
    draws = np.array(draws)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def calpers_panel() -> pd.DataFrame:
    raw = raw_table()
    overrides = load_firm_overrides()
    df = raw.copy()
    df["firm_id_raw"] = normalise_firm_ids(df)
    df["firm_id"] = apply_firm_overrides(df["firm_id_raw"], overrides)
    df["fund_number"] = parse_fund_number(df["fund_name"])
    df, _ = deduplicate_share_classes(df)
    df = add_sequence_numbers(df)
    df, _ = flag_vintage_anomalies(df)
    df["tvpi"] = df["total_value"] / df["contributions"]
    df = df[df["tvpi"].notna() & (df["contributions"] > 0)]
    return build_panel(df.drop(columns=["tvpi"]), df[["fund_id", "tvpi"]], "tvpi")


def main() -> None:
    calpers = pd.read_csv(DATA / "calpers_snapshot.csv")
    calpers_date = pd.Timestamp(calpers["as_of"].iloc[0]).date()

    oregon_path = SNAPSHOTS / f"oregon_{calpers_date}.csv"
    header("Alignment")
    print(f"  CalPERS reporting date   {calpers_date}")
    if not oregon_path.exists():
        available = sorted(p.stem.replace("oregon_", "") for p in
                           SNAPSHOTS.glob("oregon_*.csv"))
        print(f"  Oregon snapshot for {calpers_date}: NOT AVAILABLE")
        print(f"  Oregon has: {', '.join(available)}")
        raise SystemExit(
            "\nNo Oregon report shares the CalPERS reporting quarter, so no "
            "aligned\npair exists. Comparing across quarters would measure NAV "
            "drift rather\nthan reporting error, so the attenuation factor is "
            "left uncomputed."
        )

    oregon = pd.read_csv(oregon_path)
    print(f"  Oregon reporting date    {pd.Timestamp(oregon['as_of'].iloc[0]).date()}")
    print(f"  aligned: yes, both describe the quarter ending {calpers_date}")
    print(f"\n  CalPERS funds {len(calpers)},  Oregon funds {len(oregon)}")

    cal, ore = keyed(calpers), keyed(oregon)
    merged = cal.merge(
        ore, on=["stem", "fund_number"], suffixes=("_cal", "_ore"), how="inner"
    )
    merged = merged[merged["fund_number"].notna()]

    # Both plans must report a usable multiple for the pair to say anything.
    merged = merged[
        (merged["tvpi_reported_cal"] > 0) & (merged["tvpi_reported_ore"] > 0)
    ].drop_duplicates(subset=["stem", "fund_number"])

    header("Matched pairs")
    print(f"  matched on (family stem, fund number): {len(merged)}")
    print(f"  as a share of the smaller plan:        "
          f"{len(merged) / min(len(cal), len(ore)):.1%}")

    if len(merged) < 10:
        raise SystemExit(
            f"only {len(merged)} aligned pairs; too few to estimate a variance. "
            "Reported rather than computed."
        )

    log_cal = np.log(merged["tvpi_reported_cal"].to_numpy())
    log_ore = np.log(merged["tvpi_reported_ore"].to_numpy())

    merged["log_tvpi_cal"] = log_cal
    merged["log_tvpi_ore"] = log_ore
    merged["log_diff"] = log_cal - log_ore
    merged[[
        "fund_name_cal", "fund_name_ore", "stem", "fund_number",
        "vintage_cal", "vintage_ore",
        "tvpi_reported_cal", "tvpi_reported_ore", "log_diff",
        "nav_cal", "nav_ore",
    ]].to_csv(DATA / "overlap_pairs.csv", index=False)

    header("How far apart are the two reports?")
    pct = np.abs(np.expm1(merged["log_diff"]))
    print(f"  correlation of log TVPI across plans   {np.corrcoef(log_cal, log_ore)[0, 1]:.4f}")
    print(f"  median absolute difference             {pct.median():.2%}")
    print(f"  90th percentile absolute difference    {pct.quantile(0.9):.2%}")
    print(f"  largest disagreement                   {pct.max():.2%}")
    worst = merged.loc[pct.idxmax()]
    print(f"    {worst['fund_name_cal']}: "
          f"CalPERS {worst['tvpi_reported_cal']:.3f} vs "
          f"Oregon {worst['tvpi_reported_ore']:.3f}")

    disagree = (merged["vintage_cal"] != merged["vintage_ore"]).sum()
    print(f"\n  pairs where the two plans disagree on the vintage year: "
          f"{disagree} of {len(merged)}")

    header("Attenuation")
    result = attenuation(log_cal, log_ore)
    lo, hi = bootstrap_lambda(log_cal, log_ore)
    result["lambda_ci_low"], result["lambda_ci_high"] = lo, hi

    print(f"  var(reporting error)   {result['var_error']:.5f}   "
          f"(sd {result['sd_error_log']:.4f} in logs)")
    print(f"  var(true log TVPI)     {result['var_true']:.5f}")
    print(f"  reliability lambda     {result['lambda']:.4f}  "
          f"95% CI [{lo:.4f}, {hi:.4f}]")

    # One pair in 43 can dominate a variance, so report the estimate without
    # the single largest disagreement as well. Shown, not substituted: the
    # outlier is a real pair of reports and dropping it silently would be
    # choosing the answer.
    order = np.argsort(np.abs(log_cal - log_ore))[:-1]
    trimmed = attenuation(log_cal[order], log_ore[order])
    print(f"  lambda excluding the single largest gap   {trimmed['lambda']:.4f} "
          f"(n = {trimmed['n_pairs']})")
    result["lambda_ex_max"] = trimmed["lambda"]

    vintage_agree = (merged["vintage_cal"] == merged["vintage_ore"]).to_numpy()
    if vintage_agree.sum() >= 10:
        same_vintage = attenuation(log_cal[vintage_agree], log_ore[vintage_agree])
        print(f"  lambda on vintage-agreeing pairs only     "
              f"{same_vintage['lambda']:.4f} (n = {same_vintage['n_pairs']})")
        result["lambda_vintage_agree"] = same_vintage["lambda"]

    panel = calpers_panel()
    mature = panel[~panel["not_meaningful"].fillna(False).astype(bool)]
    fit = estimate(
        mature, "headline", vintage_fe=True, cluster_on=("firm_id",), max_gap=1
    )
    corrected = fit.beta / result["lambda"]
    result["beta_raw"] = fit.beta
    result["beta_corrected"] = corrected
    result["beta_corrected_low"] = fit.beta / hi
    result["beta_corrected_high"] = fit.beta / lo

    print(f"\n  beta raw (headline)    {fit.beta:.4f}  (SE {fit.se:.4f})")
    print(f"  beta corrected         {corrected:.4f}  "
          f"[{fit.beta / hi:.4f}, {fit.beta / lo:.4f}] from the lambda interval")
    print(f"  correction factor      {1 / result['lambda']:.3f}x")

    pd.DataFrame([result]).to_csv(DATA / "attenuation.csv", index=False)

    print(
        "\n  This is a FLOOR on the correction, not the correction. Both plans\n"
        "  hold the same partnership and receive the same GP valuation, so the\n"
        "  differences measured here are fee terms, close dates, each plan's\n"
        "  share, and rounding. The larger error -- that GP carrying values are\n"
        "  stale and smoothed relative to what the assets would fetch -- is\n"
        "  common to both reports and cancels in the difference. A correction\n"
        "  built on it would be larger, and cannot be estimated from overlap."
    )

    print(f"\nWrote {DATA / 'overlap_pairs.csv'}, {DATA / 'attenuation.csv'}")


if __name__ == "__main__":
    main()
