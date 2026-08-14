"""End-to-end run: simulate a fund universe, measure it, estimate persistence.

Because the simulated world has a known skill process, every number printed
here can be checked against the truth. The interesting output is not the
level of beta but the gap between specifications: how much of the apparent
persistence in a naive regression is selection, look-ahead, or vintage
effects wearing a GP's clothes.

Run with:  python analysis/run_analysis.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.synthetic import SimulationConfig, simulate  # noqa: E402
from pefund.metrics import summarise_panel  # noqa: E402
from pefund.persistence import (  # noqa: E402
    build_panel,
    estimate,
    quartile_transitions,
    results_table,
)

OUT = Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(exist_ok=True)
# statsmodels computes standard errors for every coefficient including the
# vintage dummies; with two-way clustering a few of those variances come back
# negative and numpy warns on the sqrt. The coefficient we actually report is
# guarded inside `estimate`, so this warning is noise here.
warnings.filterwarnings("ignore", message="invalid value encountered in sqrt")

pd.set_option("display.width", 130)
pd.set_option("display.max_columns", 30)


def header(text: str) -> None:
    print(f"\n{text}\n{'-' * len(text)}")


def measure(universe) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (fund attributes, performance metrics) as separate frames.

    They are kept apart on purpose: `build_panel` does the join, and passing
    an already-merged frame in as both arguments silently produces _x/_y
    suffixed columns instead of failing.
    """
    metrics = summarise_panel(universe.cash_flows, universe.index)
    return universe.funds, metrics


def main() -> None:
    # ------------------------------------------------------------ simulate
    selected = simulate(SimulationConfig())
    open_cfg = SimulationConfig(successor_tvpi_threshold=0.0)
    unselected = simulate(open_cfg)

    cfg = selected.config
    implied_beta = cfg.sd_skill**2 / (cfg.sd_skill**2 + cfg.sd_idiosyncratic**2)

    header("Data-generating process")
    print(f"  sd(GP skill)          {cfg.sd_skill:.3f}")
    print(f"  sd(idiosyncratic)     {cfg.sd_idiosyncratic:.3f}")
    print(f"  implied AR(1) beta    {implied_beta:.3f}   <- the target")
    print(f"  funds (selected)      {len(selected.funds)}")
    print(f"  funds (no selection)  {len(unselected.funds)}")

    # ------------------------------------------------------------- measure
    funds_sel, metrics_sel = measure(selected)
    funds_open, metrics_open = measure(unselected)
    panel_sel = funds_sel.merge(metrics_sel, on="fund_id", validate="one_to_one")
    panel_sel.to_csv(OUT / "fund_metrics.csv", index=False)

    header("Fund performance distribution (selected sample)")
    cols = ["tvpi", "dpi", "irr", "ks_pme", "direct_alpha"]
    print(panel_sel[cols].describe(percentiles=[0.25, 0.5, 0.75]).round(3))

    pooled_pme = (
        panel_sel["ks_pme"] * panel_sel["paid_in"]
    ).sum() / panel_sel["paid_in"].sum()
    header("Aggregation matters")
    print(f"  equal-weighted mean PME      {panel_sel['ks_pme'].mean():.3f}")
    print(f"  capital-weighted mean PME    {pooled_pme:.3f}")
    print(f"  median PME                   {panel_sel['ks_pme'].median():.3f}")
    print("  Equal-weighting each fund answers a different question than")
    print("  weighting by capital deployed; report which one and why.")

    # --------------------------------------------------------- persistence
    specs = []

    p_open = build_panel(funds_open, metrics_open, "tvpi")
    specs.append(
        estimate(p_open, "1. No selection, final lag, vintage FE", cluster_on=("firm_id", "vintage"))
    )

    p_sel = build_panel(funds_sel, metrics_sel, "tvpi")
    specs.append(estimate(p_sel, "2. Selected sample, no vintage FE", vintage_fe=False))
    specs.append(estimate(p_sel, "3. Selected sample, vintage FE"))
    specs.append(
        estimate(p_sel, "4. + fund size control", controls=("log_commitment",))
    )

    p_interim = build_panel(
        funds_sel,
        metrics_sel,
        "tvpi",
        predecessor_col="interim_tvpi_at_next_raise",
    )
    specs.append(
        estimate(p_interim, "5. Lag known at fundraise (no look-ahead)")
    )

    p_pme = build_panel(funds_sel, metrics_sel, "ks_pme")
    specs.append(estimate(p_pme, "6. Dependent variable = log PME"))

    # Selection on the *outcome*: imagine LPs only disclose funds that did not
    # embarrass them, so the bottom of the current-performance distribution is
    # missing. Unlike selection on the regressor, this one bites.
    cut = p_sel.groupby("vintage")["y"].transform(lambda s: s.quantile(0.25))
    p_censored = p_sel[p_sel["y"] > cut]
    specs.append(estimate(p_censored, "7. Bottom quartile of y undisclosed"))

    header(f"Persistence estimates (target beta = {implied_beta:.3f})")
    table = results_table(specs)
    print(table.to_string(index=False))
    table.to_csv(OUT / "persistence_results.csv", index=False)

    header("What the specifications say")
    b = {s.spec[0]: s.beta for s in specs}
    truth = implied_beta
    print(f"  Omitting vintage FE (2 vs 3):        {b['2'] - b['3']:+.3f}")
    print(f"  Selection on the lag (3 vs 1):       {b['3'] - b['1']:+.3f}")
    print(f"  Measuring the lag at fundraise (5-3):{b['5'] - b['3']:+.3f}")
    print(f"  Censoring the outcome (7 vs 3):      {b['7'] - b['3']:+.3f}")
    print()
    print("  Read the signs, do not assume them. In this DGP:")
    print("   - Dropping vintage FE ATTENUATES beta rather than inflating it.")
    print("     Successor and predecessor sit in different vintages, so the")
    print("     vintage shock enters the regressor as classical measurement")
    print("     error. Whether omitting it flatters skill depends on how")
    print("     vintage effects are correlated across a GP's funds.")
    print("   - Selection on the LAG barely moves beta, and that is a result,")
    print("     not a null. Truncating on a regressor restricts its range but")
    print("     leaves the conditional mean E[y|y_lag] intact, so OLS stays")
    print("     consistent. Survivorship is only fatal when it operates on the")
    print("     outcome or on something correlated with the error, which is")
    print("     what spec 7 does deliberately.")
    print(f"   - Every estimate should be read against the truth, {truth:.3f}.")

    header("Quartile transitions, selected sample (rows: predecessor)")
    print(quartile_transitions(p_sel).round(3).to_string())

    header("Do the estimates track true skill?")
    firm_avg = (
        p_sel.dropna(subset=["y"])
        .groupby("firm_id")
        .agg(mean_log_tvpi=("y", "mean"), n_funds=("y", "size"), skill=("true_skill", "first"))
    )
    for k in (1, 2, 3, 4):
        sub = firm_avg[firm_avg["n_funds"] >= k]
        if len(sub) > 20:
            r = np.corrcoef(sub["mean_log_tvpi"], sub["skill"])[0, 1]
            print(f"  corr(mean performance, true skill) | >= {k} funds: {r:.3f}  (n={len(sub)})")
    print("  Rising with fund count is the signal-to-noise story: a GP's track")
    print("  record only becomes informative after several funds.")

    print(f"\nWrote {OUT / 'fund_metrics.csv'} and {OUT / 'persistence_results.csv'}")


if __name__ == "__main__":
    main()
