"""Adapter for the CalPERS Private Equity Program fund performance table.

The table is plain HTML, so pandas reads it directly from the URL; no
spreadsheet round-trip and nothing to copy by hand. Published quarterly with
a roughly two-quarter reporting lag, because GPs have 120 days to deliver
financials to their LPs.

What the columns mean, in CalPERS' own terms:

    Capital Committed            what CalPERS committed to the fund
    Cash In                      contributions, including management fees
    Cash Out                     distributions received
    Cash Out & Remaining Value   distributions plus reported residual value
    Net IRR                      CalPERS' own IRR on its actual cash flows

So residual NAV is the difference between the last two, and TVPI is the last
divided by Cash In.

Two features of this table shape the whole analysis:

1.  It covers only ACTIVE partnerships. Funds that fully exited are removed.
    That is selection on realisation status, and it is not ignorable: the
    surviving old vintages are disproportionately the ones still dragging
    along unsold assets. Any persistence estimate on pre-2010 vintages here
    is conditioned on a fund still being open twenty years in.

2.  There are no dated cash flows, only cumulative totals. PME and Direct
    Alpha need dates, so they are unavailable from a single snapshot. Save
    snapshots each quarter, or pull archived copies, and difference them
    with `reconstruct_flows_from_snapshots`.

Funds marked "N/M" are too young for meaningful performance figures --
CalPERS applies this to recent vintages. The parser keeps those rows with a
`not_meaningful` flag rather than dropping them, so the decision about
whether to include them stays visible in the analysis code.
"""

from __future__ import annotations

import pandas as pd

CALPERS_URL = (
    "https://www.calpers.ca.gov/investments/about-investment-office/"
    "investment-organization/pep-fund-performance-print"
)

RENAMES = {
    "Fund": "fund_name",
    "Vintage Year": "vintage",
    "Capital Committed": "commitment",
    "Cash In": "contributions",
    "Cash Out": "distributions",
    "Cash Out & Remaining Value": "total_value",
    "Net IRR": "net_irr",
    "Investment Multiple": "reported_multiple",
}


def fetch_raw(url: str = CALPERS_URL) -> pd.DataFrame:
    """Read the performance table straight off the page.

    Requires `lxml`. If the page structure changes and several tables come
    back, the widest one is the performance table.
    """
    tables = pd.read_html(url)
    if not tables:
        raise ValueError(f"no tables found at {url}")
    return max(tables, key=lambda t: t.shape[1])


def _money(series: pd.Series) -> pd.Series:
    """'$1,234,567' -> 1234567.0 ; blanks and dashes -> NaN."""
    cleaned = (
        series.astype(str)
        .str.replace(r"[\$,\s]", "", regex=True)
        .str.replace(r"^[-–—]$", "", regex=True)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _percent(series: pd.Series) -> pd.Series:
    """'5.7%' -> 0.057 ; '14.1%  1' -> 0.141 ; 'N/M 1' -> NaN.

    The trailing digit is a footnote marker, not part of the number, so the
    percentage is extracted by pattern rather than by stripping characters.
    """
    extracted = series.astype(str).str.extract(r"(-?\d+\.?\d*)\s*%", expand=False)
    return pd.to_numeric(extracted, errors="coerce") / 100.0


def parse(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn the scraped table into the canonical snapshot schema."""
    df = raw.rename(columns=RENAMES).copy()

    missing = set(RENAMES.values()) - set(df.columns) - {"reported_multiple"}
    if missing:
        raise ValueError(
            f"unexpected table layout, missing {sorted(missing)}; "
            f"got columns {list(raw.columns)}"
        )

    # The printer-friendly page repeats the header as the first body row.
    df = df[df["fund_name"].astype(str).str.strip() != "Fund"]

    df["fund_name"] = df["fund_name"].astype(str).str.strip()
    df["vintage"] = pd.to_numeric(df["vintage"], errors="coerce").astype("Int64")

    for col in ("commitment", "contributions", "distributions", "total_value"):
        df[col] = _money(df[col])

    df["not_meaningful"] = (
        df["net_irr"].astype(str).str.contains("N/M", case=False, na=False)
    )
    df["net_irr"] = _percent(df["net_irr"])

    # Residual value is what has not yet been distributed.
    df["nav"] = df["total_value"] - df["distributions"]
    df["tvpi_reported"] = df["total_value"] / df["contributions"]

    df["fund_id"] = "CALPERS::" + df["fund_name"]
    df["source"] = "CalPERS PEP"
    df = df.dropna(subset=["vintage", "contributions"])
    df = df[df["contributions"] > 0]

    keep = [
        "fund_id",
        "fund_name",
        "vintage",
        "commitment",
        "contributions",
        "distributions",
        "total_value",
        "nav",
        "tvpi_reported",
        "net_irr",
        "not_meaningful",
        "source",
    ]
    return df[keep].reset_index(drop=True)


def load(url: str = CALPERS_URL, as_of: str | None = None) -> pd.DataFrame:
    """Fetch, parse, and stamp a reporting date."""
    out = parse(fetch_raw(url))
    out["as_of"] = pd.Timestamp(as_of) if as_of else pd.Timestamp.today().normalize()
    return out
