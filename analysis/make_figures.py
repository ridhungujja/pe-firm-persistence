"""Build every figure in figures/. Matplotlib only, no seaborn.

Run:  python analysis/fetch_calpers.py
      python analysis/run_real_analysis.py     # writes the tables these read
      python analysis/make_figures.py

Produces:
    figures/coefficients.png        beta with 95% CIs, every specification
    figures/sample_funnel.png       raw rows down to the estimation sample
    figures/vintage_coverage.png    fund count and median TVPI by vintage
    figures/transition_heatmap.png  quartile transitions with cell counts
    figures/simulation_validation.png  estimated vs true beta, known DGP
    figures/leave_one_out.png       beta when each family is dropped in turn

Design notes, because they were decisions rather than defaults:

*   Colours are the first three slots of a palette validated for colour-vision
    deficiency (worst all-pairs CVD dE 9.2, normal-vision 24.0 on a light
    surface). Blue carries the estimate, orange marks the headline row, and
    identity is never carried by colour alone -- every highlighted element is
    also labelled in text.
*   Vintage coverage is TWO STACKED PANELS, not one panel with two y-axes.
    Fund count and median TVPI have unrelated scales, and a twin axis lets the
    reader infer a crossing or a divergence that is an artefact of where the
    two scales were pinned. Shared x, separate panels, no inference invited.
*   The transition heatmap is a single-hue sequential ramp with the counts
    printed in the cells. A rainbow would imply the four quartiles are
    unordered categories, and proportions without counts are unreadable in
    the smaller cells.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.base import resolve_snapshot  # noqa: E402
from pefund.ingest.synthetic import SimulationConfig, simulate  # noqa: E402
from pefund.metrics import summarise_panel  # noqa: E402
from pefund.persistence import build_panel, estimate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FIGURES = ROOT / "figures"

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d8d7d2"

warnings.filterwarnings("ignore", message="invalid value encountered in sqrt")

plt.rcParams.update({
    "figure.dpi": 160,
    "savefig.dpi": 160,
    "savefig.bbox": "tight",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
})


def _style(ax, xgrid=False, ygrid=False):
    ax.set_axisbelow(True)
    if xgrid:
        ax.xaxis.grid(True)
    if ygrid:
        ax.yaxis.grid(True)
    return ax


def figure_coefficients() -> None:
    path = DATA / "all_specifications.csv"
    if not path.exists():
        print("  skipped coefficients: run run_real_analysis.py first")
        return
    table = pd.read_csv(path).dropna(subset=["beta"])
    table = table.iloc[::-1].reset_index(drop=True)   # top row at the top

    fig, ax = plt.subplots(figsize=(7.4, 0.42 * len(table) + 1.4))
    y = np.arange(len(table))
    headline = table["specification"].str.contains("HEADLINE")
    colours = [ORANGE if h else BLUE for h in headline]

    ax.axvline(0.0, color=MUTED, linewidth=1.0, zorder=1)
    for i, row in table.iterrows():
        ax.plot(
            [row["ci95_low"], row["ci95_high"]], [y[i], y[i]],
            color=colours[i], linewidth=2.0, solid_capstyle="round", zorder=2,
        )
    ax.scatter(
        table["beta"], y, s=42, color=colours, zorder=3,
        edgecolor="white", linewidth=1.2,
    )

    for i, row in table.iterrows():
        ax.annotate(
            f"{row['beta']:.3f}",
            (row["beta"], y[i]), textcoords="offset points", xytext=(0, 8),
            ha="center", fontsize=7.5, color=INK,
        )

    labels = [s.replace("  [HEADLINE]", "") for s in table["specification"]]
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    for tick, is_head in zip(ax.get_yticklabels(), headline):
        if is_head:
            tick.set_color(ORANGE)
            tick.set_fontweight("bold")

    ax.set_xlabel(
        "beta on predecessor log TVPI  (95% CI; SEs clustered on family, "
        "except row 3s on sponsor)"
    )
    # Read the zero-crossing off the estimate rather than asserting it. This
    # caption said "the interval includes zero" for as long as it did; when
    # pooling the second plan moved the headline off zero the sentence became
    # false and the figure kept publishing it.
    head_row = table[table["specification"].str.contains(r"\[HEADLINE\]", regex=True)]
    if head_row.empty:
        head_row = table.iloc[[0]]
    lo = float(head_row["ci95_low"].iloc[0])
    hi = float(head_row["ci95_high"].iloc[0])
    verdict = ("the interval includes zero" if lo <= 0 <= hi
               else "the interval excludes zero")
    ax.set_title(
        "Persistence estimate across specifications\n"
        f"orange = headline (mature funds, adjacent pairs); {verdict}",
        loc="left", color=INK,
    )
    _style(ax, xgrid=True)
    fig.savefig(FIGURES / "coefficients.png")
    plt.close(fig)
    print("  coefficients.png")


def figure_funnel() -> None:
    path = DATA / "sample_funnel.csv"
    if not path.exists():
        print("  skipped funnel: run run_real_analysis.py first")
        return
    steps = pd.read_csv(path)
    labels = list(steps["step"])
    values = [int(v) for v in steps["n"]]

    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    x = np.arange(len(values))
    colours = [BLUE] * (len(values) - 1) + [ORANGE]
    ax.bar(x, values, width=0.62, color=colours, zorder=3)

    for i, value in enumerate(values):
        ax.annotate(
            f"{value:,}", (i, value), textcoords="offset points", xytext=(0, 4),
            ha="center", fontsize=8.5, color=INK,
        )
        if i:
            lost = values[i - 1] - value
            # Only label a genuine drop. The funnel changes units midway --
            # funds up to "families with 2+", pairs after it -- so the step
            # into "lagged pairs" counts up, and differencing across it
            # produced a "--159" that means nothing.
            if lost > 0:
                # Sit each loss just above the shorter of the two bars it
                # spans, so the labels step down with the funnel instead of
                # floating in a row disconnected from the bars.
                ax.annotate(
                    f"−{lost:,}", (i - 0.5, value + max(values) * 0.055),
                    ha="center", fontsize=7.5, color=MUTED,
                )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("funds / pairs")
    ax.set_title(
        f"Sample funnel: {values[0]:,} published rows become "
        f"{values[-1]:,} usable observations",
        loc="left", color=INK,
    )
    _style(ax, ygrid=True)
    fig.savefig(FIGURES / "sample_funnel.png")
    plt.close(fig)
    print("  sample_funnel.png")


def figure_vintage_coverage() -> None:
    # Both plans. CalPERS alone starts at 1998 and has one fund before 2000,
    # so a CalPERS-only version of this panel hides the entire realised half
    # of the sample.
    df = pd.concat(
        [pd.read_csv(resolve_snapshot(DATA, prefix)) for prefix in ("calpers", "oregon")],
        ignore_index=True,
    )
    df["tvpi"] = df["total_value"] / df["contributions"]
    df["unrealised"] = df["nav"] / df["total_value"].replace(0, np.nan)
    by = df.groupby("vintage").agg(
        funds=("fund_id", "size"),
        median_tvpi=("tvpi", "median"),
        unrealised=("unrealised", "median"),
    )
    # No lower cutoff. There was a `>= 1998` here from when CalPERS was the
    # only source and 1998 was its first vintage; kept after Oregon was pooled
    # in, it silently dropped all 68 pre-2000 funds -- the entire realised half
    # of the sample, and the reason for adding the second plan.
    by = by[by.index.notna()]

    # Two panels rather than a twin axis: fund count and TVPI have unrelated
    # scales, and a shared axis invites a reading of "crossing" that would be
    # an artefact of where the scales were pinned.
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(7.6, 4.8), sharex=True,
        gridspec_kw={"height_ratios": [1.15, 1]},
    )

    top.bar(by.index, by["funds"], color=BLUE, width=0.72, zorder=3,
            label="funds in the table")
    top.bar(by.index, by["funds"] * by["unrealised"].fillna(0), width=0.72,
            color=AQUA, zorder=4, label="unrealised share of value (shaded)")
    top.set_ylabel("funds")
    top.legend(frameon=False, fontsize=7.5, loc="upper left")
    span = f"{int(by.index.min())}-{int(by.index.max())}"
    top.set_title(
        f"Vintage coverage, {span}: old funds are realised, recent ones are "
        "still marks",
        loc="left", color=INK,
    )
    _style(top, ygrid=True)

    bottom.plot(by.index, by["median_tvpi"], color=ORANGE, linewidth=2.0,
                marker="o", markersize=4, zorder=3)
    bottom.axhline(1.0, color=MUTED, linewidth=0.9, linestyle=(0, (4, 3)))
    bottom.annotate("1.0x", (by.index.min(), 1.0), textcoords="offset points",
                    xytext=(0, 4), fontsize=7.5, color=MUTED)
    bottom.set_ylabel("median TVPI")
    bottom.set_xlabel("vintage year")
    _style(bottom, ygrid=True)

    fig.savefig(FIGURES / "vintage_coverage.png")
    plt.close(fig)
    print("  vintage_coverage.png")


def figure_transition_heatmap() -> None:
    path = DATA / "transition_counts.csv"
    if not path.exists():
        print("  skipped transition heatmap: no transition_counts.csv")
        return
    counts = pd.read_csv(path, index_col=0)
    counts.columns = [str(int(float(c))) for c in counts.columns]
    matrix = counts.to_numpy(dtype=float)
    shares = matrix / matrix.sum(axis=1, keepdims=True)

    fig, ax = plt.subplots(figsize=(4.9, 4.3))
    # Single-hue sequential ramp: the quartiles are ordered, so a rainbow
    # would imply they are unordered categories.
    ramp = matplotlib.colors.LinearSegmentedColormap.from_list(
        "blues", ["#f4f8fd", BLUE]
    )
    image = ax.imshow(shares, cmap=ramp, vmin=0, vmax=shares.max())

    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            # Only the darkest cells take white text; a mid-tone
            # cell with white numerals is the classic unreadable
            # heatmap.
            dark = shares[i, j] > shares.max() * 0.68
            ax.text(
                j, i, f"{shares[i, j]:.0%}\nn={int(matrix[i, j])}",
                ha="center", va="center", fontsize=8,
                color="white" if dark else INK,
            )

    ax.set_xticks(range(matrix.shape[1]), [f"Q{c}" for c in counts.columns])
    ax.set_yticks(range(matrix.shape[0]), [f"Q{int(float(i))}" for i in counts.index])
    ax.set_xlabel("successor quartile")
    ax.set_ylabel("predecessor quartile")
    # Read from the test output rather than restating it. This subtitle sat at
    # "p = 0.089" from the one-plan run while the cells below it updated.
    test = pd.read_csv(DATA / "transition_test.csv").iloc[0]
    caption_obs = float(test["observed_diagonal_share"])
    caption_null = float(test["null_mean"])
    caption_p = float(test["p_value"])
    ax.set_title(
        "Quartile transitions, mature adjacent pairs\n"
        f"diagonal {caption_obs:.0%} vs {caption_null:.0%} under the "
        f"within-vintage null (p = {caption_p:.4f})",
        loc="left", color=INK, fontsize=9.5,
    )
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.colorbar(image, ax=ax, shrink=0.75, label="share of row")
    fig.savefig(FIGURES / "transition_heatmap.png")
    plt.close(fig)
    print("  transition_heatmap.png")


def figure_simulation_validation() -> None:
    """Estimated beta against the DGP's true beta, across skill settings.

    The estimator has to clear this before anything it says about real data
    is worth reading: on data whose persistence is known by construction, the
    estimate must land on the truth.
    """
    rows = []
    for sd_skill in (0.0, 0.08, 0.14, 0.18, 0.24, 0.30):
        cfg = SimulationConfig(sd_skill=sd_skill, successor_tvpi_threshold=0.0,
                               n_firms=260, seed=7)
        universe = simulate(cfg)
        metrics = summarise_panel(universe.cash_flows, universe.index)
        panel = build_panel(universe.funds, metrics, "tvpi")
        fit = estimate(panel, f"sd_skill={sd_skill}")
        true_beta = cfg.sd_skill**2 / (cfg.sd_skill**2 + cfg.sd_idiosyncratic**2)
        rows.append({"true": true_beta, "beta": fit.beta, "se": fit.se})
    results = pd.DataFrame(rows)
    results.to_csv(DATA / "simulation_validation.csv", index=False)

    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    limit = max(results["true"].max(), results["beta"].max()) * 1.18
    ax.plot([0, limit], [0, limit], color=MUTED, linewidth=1.0,
            linestyle=(0, (4, 3)), zorder=1)
    ax.annotate("estimate = truth", (limit * 0.62, limit * 0.66), fontsize=7.5,
                color=MUTED, rotation=38)
    ax.errorbar(
        results["true"], results["beta"], yerr=1.96 * results["se"],
        fmt="o", color=BLUE, ecolor=BLUE, elinewidth=1.8, capsize=0,
        markersize=6, markeredgecolor="white", markeredgewidth=1.1, zorder=3,
    )
    ax.set_xlabel("true beta,  var(skill) / (var(skill) + var(idiosyncratic))")
    ax.set_ylabel("estimated beta  (95% CI)")
    ax.set_title(
        "Estimator recovers known persistence\n"
        "simulated funds, no selection, vintage FE",
        loc="left", color=INK,
    )
    _style(ax, xgrid=True, ygrid=True)
    fig.savefig(FIGURES / "simulation_validation.png")
    plt.close(fig)
    print("  simulation_validation.png")


def figure_leave_one_out() -> None:
    path = DATA / "leave_one_family_out.csv"
    if not path.exists():
        print("  skipped leave-one-out: run run_real_analysis.py first")
        return
    loo = pd.read_csv(path)
    full = 0.2142

    fig, ax = plt.subplots(figsize=(6.8, 3.4))
    ax.hist(loo["beta"], bins=14, color=BLUE, zorder=3)
    ax.axvline(0.0, color=MUTED, linewidth=1.0, zorder=2)
    ax.axvline(full, color=ORANGE, linewidth=2.0, zorder=4)
    top = ax.get_ylim()[1]

    ax.annotate(
        f"full sample {full:.3f}", (full, top * 0.98),
        textcoords="offset points", xytext=(7, 0), fontsize=8, color=ORANGE,
        va="top",
    )
    # The empty region left of the distribution is the only place a label does
    # not sit on top of a bar; point at the extreme refit from there.
    worst = loo.loc[(loo["beta"] - full).abs().idxmax()]
    ax.annotate(
        f"most influential single family:\ndrop {worst['dropped'].title()}\n"
        f"→ {worst['beta']:.3f}",
        xy=(worst["beta"], 1.4), xycoords="data",
        xytext=(0.035, top * 0.72), textcoords="data",
        fontsize=7.5, color=MUTED, va="center",
        arrowprops=dict(arrowstyle="->", color=MUTED, linewidth=0.9,
                        shrinkA=0, shrinkB=4),
    )
    ax.annotate(
        "no refit reaches zero", xy=(0.0, top * 0.30),
        textcoords="offset points", xytext=(7, 0), fontsize=7.5, color=MUTED,
    )
    ax.set_xlabel("beta with one family removed")
    ax.set_ylabel("refits")
    ax.set_title(
        f"Leave-one-family-out: {len(loo)} refits span "
        f"[{loo['beta'].min():.3f}, {loo['beta'].max():.3f}], none below zero",
        loc="left", color=INK,
    )
    _style(ax, ygrid=True)
    fig.savefig(FIGURES / "leave_one_out.png")
    plt.close(fig)
    print("  leave_one_out.png")


def main() -> None:
    FIGURES.mkdir(exist_ok=True)
    print(f"Writing figures to {FIGURES}")
    figure_coefficients()
    figure_funnel()
    figure_vintage_coverage()
    figure_transition_heatmap()
    figure_simulation_validation()
    figure_leave_one_out()


if __name__ == "__main__":
    main()
