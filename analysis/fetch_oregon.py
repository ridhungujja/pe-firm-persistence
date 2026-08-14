"""Download and parse the Oregon PERS quarterly PDF archive.

Run:  python analysis/fetch_oregon.py

Produces:
    data/snapshots/raw/oregon_operf_pe_<YYYY>Q<N>.pdf   the source PDFs
    data/snapshots/oregon_<YYYY-MM-DD>.csv              parsed, canonical schema

Snapshots are never overwritten. The archive is the asset: two or more dated
snapshots of the same funds are what make `reconstruct_flows_from_snapshots`
work, and cumulative-total disclosures give no cash flows any other way.

The URL pattern has changed in the past. If a quarter 404s that is not
necessarily an error -- Oregon publishes with a lag and reorganises its site --
so missing quarters are reported and skipped rather than raising.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.oregon import download, parse_pdf, quarter_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "snapshots"
RAW = SNAPSHOTS / "raw"

#: Quarters to probe. Oregon keeps roughly two years online at any time.
YEARS = range(2019, 2027)
QUARTERS = (1, 2, 3, 4)


def main() -> None:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    found, missing = [], []
    for year in YEARS:
        for quarter in QUARTERS:
            pdf_path = RAW / f"oregon_operf_pe_{year}Q{quarter}.pdf"
            try:
                download(year, quarter, pdf_path)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    missing.append((year, quarter))
                    continue
                raise
            except urllib.error.URLError as exc:
                print(f"  network error on Q{quarter} {year}: {exc.reason}")
                missing.append((year, quarter))
                continue

            df = parse_pdf(pdf_path)
            as_of = pd.Timestamp(df["as_of"].iloc[0]).date()
            out = SNAPSHOTS / f"oregon_{as_of}.csv"
            if not out.exists():
                df.to_csv(out, index=False)
            found.append((year, quarter, as_of, len(df), out))
            print(f"  Q{quarter} {year}: {len(df):4d} funds, as of {as_of} -> {out.name}")

    print(f"\n{len(found)} quarters parsed, {len(missing)} not published at the "
          f"expected URL")
    if not found:
        raise SystemExit(
            "No quarters downloaded. Confirm the current naming from the Oregon "
            f"Treasury holdings page; the pattern tried was:\n  {quarter_url(2025, 3)}"
        )

    panel = pd.concat(
        [pd.read_csv(path) for *_, path in found], ignore_index=True
    )
    n_dates = panel["as_of"].nunique()
    repeated = (
        panel.groupby("fund_id")["as_of"].nunique().pipe(lambda s: (s >= 2).sum())
    )
    print(f"{n_dates} distinct reporting dates, {panel['fund_id'].nunique()} funds")
    print(f"{repeated} funds observed at 2+ dates -> cash flows reconstructable")


if __name__ == "__main__":
    main()
