"""Reconstruct cash flows from the Oregon snapshot archive and compute PME.

Run:  python analysis/fetch_oregon.py    # builds the archive
      python analysis/run_pme.py

Produces data/oregon_pme.csv and prints the sample funnel.

Why most funds get NaN
----------------------
Differencing consecutive snapshots recovers the flows that happened BETWEEN
snapshots. It cannot recover flows that happened before the archive begins.
For a fund that had already called 80% of its capital by the first snapshot,
the reconstruction sees only the tail, and `reconstruct_flows_from_snapshots`
dates the entire opening cumulative balance at the first snapshot date.

For a multiple that is harmless: TVPI does not care when the money moved. For
PME it is fatal. PME discounts every flow by the market's return from that
flow's date, so dating twenty years of capital calls at a single day in 2023
prices them all at the 2023 index level and produces a number with no
interpretation at all -- and it does not fail loudly, it just returns a
plausible-looking ratio.

So PME is computed only for funds whose FIRST appearance in the archive shows
zero paid-in capital. For those the whole call and distribution history falls
inside the observation window and the flow series is complete. Every other
fund gets NaN. It is not approximated from a single observation, and the
excluded count is reported rather than buried.

The honest cost: that leaves a small sample of young funds, whose value is
mostly unrealised GP marks rather than cash returned. Their PME is a statement
about carrying values, not about realisations, and the printed summary says so.
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.base import (  # noqa: E402
    funds_observed_from_inception,
    reconstruct_flows_from_snapshots,
)
from pefund.ingest.french import load_index  # noqa: E402
from pefund.metrics import FundCashFlows, direct_alpha, ks_pme, tvpi  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "snapshots"
OUT = ROOT / "data" / "oregon_pme.csv"


def load_archive() -> pd.DataFrame:
    paths = sorted(glob.glob(str(SNAPSHOTS / "oregon_*.csv")))
    if len(paths) < 2:
        raise SystemExit(
            f"found {len(paths)} Oregon snapshot(s) in {SNAPSHOTS}; PME needs at "
            "least two. Run: python analysis/fetch_oregon.py"
        )
    panel = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    panel["as_of"] = pd.to_datetime(panel["as_of"])
    return panel.sort_values(["fund_id", "as_of"])


def main() -> None:
    panel = load_archive()
    index = load_index()

    dates = sorted(panel["as_of"].unique())
    print(f"Archive: {len(dates)} quarters, {pd.Timestamp(dates[0]).date()} "
          f"to {pd.Timestamp(dates[-1]).date()}, {panel['fund_id'].nunique()} funds")

    usable = funds_observed_from_inception(panel)
    print(f"\nSample funnel")
    print(f"  funds in archive                       {panel['fund_id'].nunique():4d}")
    print(f"  observed at 2+ dates                   "
          f"{int((panel.groupby('fund_id')['as_of'].nunique() >= 2).sum()):4d}")
    print(f"  zero paid-in at first appearance       {len(usable):4d}   <- PME sample")
    print(f"  already called capital before archive  "
          f"{panel['fund_id'].nunique() - len(usable):4d}   <- PME left NaN")

    flows = reconstruct_flows_from_snapshots(panel)
    last = panel.groupby("fund_id").last()

    rows = []
    for fund_id in panel["fund_id"].unique():
        info = last.loc[fund_id]
        record = {
            "fund_id": fund_id,
            "fund_name": info["fund_name"],
            "vintage": info["vintage"],
            "commitment": info["commitment"],
            "contributions": info["contributions"],
            "distributions": info["distributions"],
            "nav": info["nav"],
            "tvpi_reported": info["tvpi_reported"],
            "sold_secondary": info["sold_secondary"],
            "inception_observed": fund_id in usable,
            "ks_pme": np.nan,
            "direct_alpha": np.nan,
            "tvpi_from_flows": np.nan,
        }
        if fund_id in usable:
            group = flows[flows["fund_id"] == fund_id]
            if not group.empty:
                nav_date = pd.Timestamp(info["as_of"])
                cf = FundCashFlows(
                    fund_id=str(fund_id),
                    dates=pd.DatetimeIndex(group["date"]),
                    amounts=group["amount"].to_numpy(dtype=float),
                    nav=float(info["nav"]),
                    nav_date=max(nav_date, pd.DatetimeIndex(group["date"])[-1]),
                )
                record["ks_pme"] = ks_pme(cf, index)
                record["direct_alpha"] = direct_alpha(cf, index)
                record["tvpi_from_flows"] = tvpi(cf)
        rows.append(record)

    result = pd.DataFrame(rows)
    result.to_csv(OUT, index=False)

    sample = result[result["inception_observed"] & result["ks_pme"].notna()]
    print(f"\nPME computed for {len(sample)} funds, benchmark = French market "
          f"total return")
    if not sample.empty:
        weights = sample["contributions"]
        print(f"  equal-weighted mean KS PME   {sample['ks_pme'].mean():.3f}")
        print(f"  capital-weighted KS PME      "
              f"{np.average(sample['ks_pme'], weights=weights):.3f}")
        print(f"  median KS PME                {sample['ks_pme'].median():.3f}")
        print(f"  median direct alpha          {sample['direct_alpha'].median():+.2%}")
        print(f"  median TVPI                  {sample['tvpi_from_flows'].median():.3f}")
        unrealised = sample["nav"] / sample["nav"].add(sample["distributions"])
        print(f"  median share of value unrealised  {unrealised.median():.1%}")
        print(f"  vintages {int(sample['vintage'].min())}-{int(sample['vintage'].max())}")

    print(
        "\nRead this sample for what it is. Every fund in it is young enough "
        "that\nits value is overwhelmingly the GP's own carrying mark rather "
        "than cash\nreturned, which is the case Oregon itself labels 'not "
        "meaningful'. The\nnumber measures marks against the market, not "
        "realisations against it."
    )
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
