"""Pull the live CalPERS table and save it as a clean CSV.

Run:  python analysis/fetch_calpers.py

Writes data/calpers_snapshot.csv and prints a data-quality summary. Re-run it
each quarter; keeping dated copies is what eventually makes PME possible,
since differencing consecutive snapshots recovers approximate cash flows.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.base import (  # noqa: E402
    add_sequence_numbers,
    apply_firm_overrides,
    deduplicate_share_classes,
    flag_vintage_anomalies,
    normalise_firm_ids,
    parse_fund_number,
)
from pefund.ingest.calpers import CALPERS_URL, load  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data"
pd.set_option("display.width", 130)


def main() -> None:
    print(f"Fetching {CALPERS_URL}")
    try:
        df = load()
    except Exception as exc:  # noqa: BLE001
        print(f"\nFetch failed: {exc}")
        print("If this is an ImportError, run: pip install lxml")
        print("If the page moved, search CalPERS for 'PEP Fund Performance'.")
        raise SystemExit(1) from exc

    n_raw_rows = len(df)
    df["firm_id_raw"] = normalise_firm_ids(df)
    df["firm_id"] = apply_firm_overrides(df["firm_id_raw"])
    df["fund_number"] = parse_fund_number(df["fund_name"])

    # Share classes must collapse before sequence numbering, or each class
    # becomes its own step in the series.
    df, dedup_report = deduplicate_share_classes(df)
    if not dedup_report.empty:
        dedup_report.to_csv(OUT / "share_class_dedup.csv", index=False)

    df = add_sequence_numbers(df)
    df, anomalies = flag_vintage_anomalies(df)
    if not anomalies.empty:
        anomalies.to_csv(OUT / "vintage_anomalies.csv", index=False)

    path = OUT / "calpers_snapshot.csv"
    df.to_csv(path, index=False)

    # Dated copy, never overwritten. A single snapshot gives cumulative totals
    # only; two or more give cash flows by differencing, which is the whole
    # reason PME becomes possible later. The archive is the asset.
    snapshots = OUT / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    as_of = pd.Timestamp(df["as_of"].max()).date()
    archived = snapshots / f"calpers_{as_of}.csv"
    if not archived.exists():
        df.to_csv(archived, index=False)
        print(f"archived snapshot -> {archived}")
    else:
        print(f"snapshot for {as_of} already archived, not overwritten")

    print(f"\n{n_raw_rows} rows published, {len(df)} funds after share-class dedup")
    print(f"vintages {df['vintage'].min()}-{df['vintage'].max()}")
    print(f"{df['firm_id_raw'].nunique()} firms after name normalisation")
    print(f"{df['firm_id'].nunique()} firms after hand-checked overrides")
    print(
        f"{len(dedup_report)} funds collapsed from "
        f"{int(dedup_report['n_share_classes'].sum()) if not dedup_report.empty else 0}"
        f" share-class rows -> {OUT / 'share_class_dedup.csv'}"
    )
    print(f"{df['fund_number'].notna().sum()} funds have a parsed fund number")
    print(
        f"{int(df['vintage_anomaly'].sum())} funds flagged with a suspect vintage "
        f"-> {OUT / 'vintage_anomalies.csv'}"
    )
    print(f"{df['not_meaningful'].sum()} funds flagged not-meaningful by CalPERS")
    print(f"{df['parallel_vintage'].sum()} funds share a vintage with a sibling fund")

    multi = df.groupby("firm_id").size()
    usable = int((multi >= 2).sum())
    print(f"\n{usable} firms have 2+ funds -> {int((multi[multi >= 2] - 1).sum())} "
          f"usable observations for the persistence regression")

    print("\nCommitment-weighted TVPI by vintage decade:")
    decade = (df["vintage"] // 10 * 10).astype(int)
    summary = df.groupby(decade).apply(
        lambda g: pd.Series(
            {
                "funds": len(g),
                "tvpi": (g["total_value"].sum() / g["contributions"].sum()),
                "median_irr": g["net_irr"].median(),
            }
        ),
        include_groups=False,
    )
    print(summary.round(3).to_string())

    print("\nTop 10 firms by fund count (check these names by hand first):")
    print(multi.sort_values(ascending=False).head(10).to_string())

    print(f"\nWrote {path}")
    print("\nReminder: this table holds ACTIVE partnerships only. Fully exited")
    print("funds are absent, so old vintages here are survivors in a specific")
    print("and non-random sense. Say so in the write-up.")


if __name__ == "__main__":
    main()
