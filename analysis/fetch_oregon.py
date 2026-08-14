"""Download and parse the Oregon PERS quarterly PDF archive.

Run:  python analysis/fetch_oregon.py

Produces:
    data/snapshots/raw/oregon_operf_pe_<YYYY>Q<N>.pdf   the source PDFs
    data/snapshots/oregon_<YYYY-MM-DD>.csv              parsed, canonical schema

Reports are discovered by reading the Treasury holdings page rather than by
guessing URLs from a template. Oregon has used at least five naming
conventions for the same quarterly report and files at least one report under
a folder for the wrong year, so a template finds a fraction of what exists:
probing the current pattern across 2014-2026 turned up 8 reports, discovery
turns up 18.

Snapshots are never overwritten. The archive is the asset: two or more dated
snapshots of the same funds are what make `reconstruct_flows_from_snapshots`
work, and cumulative-total disclosures give no cash flows any other way.

Older reports may use a layout the parser does not handle. Those are reported
by year and quarter and skipped, never partially imported.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.manifest import write_manifest  # noqa: E402
from pefund.ingest.oregon import (  # noqa: E402
    OREGON_HOLDINGS_PAGE,
    discover_reports,
    download_url,
    parse_pdf,
)

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "snapshots"
RAW = SNAPSHOTS / "raw"


def main() -> None:
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    try:
        reports = discover_reports()
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"could not read {OREGON_HOLDINGS_PAGE}: {exc.reason}\n"
            "Without the listing page the archive cannot be enumerated; the "
            "already-downloaded PDFs in data/snapshots/raw/ still parse."
        ) from exc

    print(f"{len(reports)} private equity reports linked from the holdings page")

    parsed, failed = [], []
    for report in reports:
        year, quarter = report["year"], report["quarter"]
        pdf_path = RAW / f"oregon_operf_pe_{year}Q{quarter}.pdf"
        try:
            download_url(report["url"], pdf_path)
        except urllib.error.HTTPError as exc:
            failed.append((year, quarter, f"HTTP {exc.code}"))
            continue
        except urllib.error.URLError as exc:
            failed.append((year, quarter, f"network: {exc.reason}"))
            continue

        try:
            df = parse_pdf(pdf_path)
        except Exception as exc:  # noqa: BLE001 - layout changes are expected
            failed.append((year, quarter, f"{type(exc).__name__}: {exc}"))
            continue

        as_of = pd.Timestamp(df["as_of"].iloc[0]).date()
        out = SNAPSHOTS / f"oregon_{as_of}.csv"
        if not out.exists():
            df.to_csv(out, index=False)
        parsed.append((year, quarter, as_of, len(df), out))
        print(f"  Q{quarter} {year}: {len(df):4d} funds, as of {as_of}")

    if failed:
        print(f"\n{len(failed)} reports could not be imported:")
        for year, quarter, why in sorted(failed):
            print(f"  Q{quarter} {year}: {why}")

    print(f"\n{len(parsed)} quarters parsed")
    if not parsed:
        raise SystemExit("no quarters imported; check the holdings page layout")

    panel = pd.concat([pd.read_csv(p) for *_, p in parsed], ignore_index=True)
    dates = sorted(panel["as_of"].unique())
    print(f"{len(dates)} distinct reporting dates, {dates[0]} to {dates[-1]}")
    print(f"{panel['fund_id'].nunique()} distinct funds")

    repeated = (panel.groupby("fund_id")["as_of"].nunique() >= 2).sum()
    print(f"{repeated} funds observed at 2+ dates -> cash flows reconstructable")

    manifest = write_manifest(SNAPSHOTS)
    print(f"manifest: {len(manifest)} archived files -> {SNAPSHOTS / 'MANIFEST.csv'}")


if __name__ == "__main__":
    main()
