"""Kenneth French Data Library: the PME benchmark.

PME discounts a fund's cash flows by a public-market index, so the choice of
index is not a formatting decision -- it is the counterfactual the whole
statistic is built on. Three properties matter and the French market factor
has all of them:

*   It is a TOTAL return. A price index such as the headline S&P 500 level
    excludes dividends, roughly two points a year. Over a ten-year fund life
    that compounds to about 22% of the benchmark's terminal wealth, and every
    PME computed against it is inflated by that margin. This is the single
    easiest way to accidentally manufacture outperformance.
*   It is value-weighted over the whole US market, not large caps only.
*   It is the standard benchmark in the academic PME literature, so estimates
    here are comparable to published ones.

Source:
    https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
    F-F_Research_Data_Factors_CSV.zip

The monthly file gives `Mkt-RF` and `RF` in percent. The market's total
return is their sum, and compounding that gives the level series that
`ks_pme` and `direct_alpha` expect.

Missing observations are coded -99 or -99.99. They must become NaN before
compounding: read literally, a single -99 month multiplies the running level
by -0.98 and destroys every value after it.

A note on risk. Buyout portfolios are levered and tilted toward smaller,
cheaper companies, so the market factor is not their correct risk benchmark
and Korteweg-Nagel argue this materially changes conclusions. `load_factors`
therefore returns the size and value factors too, so a second benchmark can be
built cheaply and the choice can be shown to matter rather than assumed away.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

FRENCH_FACTORS_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_Factors_CSV.zip"
)

#: French codes missing data with these sentinels rather than leaving blanks.
MISSING_CODES = (-99.0, -99.99, -999.0)


def download_factors(dest: str | Path) -> Path:
    """Save the raw zip so the benchmark is reproducible offline."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    request = urllib.request.Request(
        FRENCH_FACTORS_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        dest.write_bytes(response.read())
    return dest


def parse_factors(raw: bytes) -> pd.DataFrame:
    """Parse the monthly factor block out of the French CSV.

    The file starts with a prose header, then the monthly table keyed by
    YYYYMM, then an annual table keyed by YYYY. Only the monthly block is
    wanted, and it is identified by the key's width rather than by counting
    header lines, which change between releases.
    """
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
            text = archive.read(name).decode("latin-1")
    else:
        text = raw.decode("latin-1")

    rows = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        # Monthly rows are keyed YYYYMM; the annual block that follows is YYYY.
        if len(parts[0]) != 6:
            continue
        try:
            values = [float(p) for p in parts[1:5]]
        except ValueError:
            continue
        rows.append([parts[0], *values])

    if not rows:
        raise ValueError(
            "no monthly rows found in the French factor file; the layout may "
            "have changed"
        )

    df = pd.DataFrame(rows, columns=["yyyymm", "mkt_rf", "smb", "hml", "rf"])
    df["date"] = pd.to_datetime(df["yyyymm"], format="%Y%m") + pd.offsets.MonthEnd(0)

    for col in ("mkt_rf", "smb", "hml", "rf"):
        df[col] = df[col].replace(list(MISSING_CODES), np.nan) / 100.0

    return df.set_index("date")[["mkt_rf", "smb", "hml", "rf"]].sort_index()


def market_total_return(factors: pd.DataFrame) -> pd.Series:
    """Monthly total return on the US market: excess return plus the risk-free."""
    total = factors["mkt_rf"] + factors["rf"]
    if total.isna().any():
        # Compounding through a NaN silently truncates the level series, so
        # refuse rather than produce a benchmark with a hole in it.
        first_bad = total[total.isna()].index[0]
        raise ValueError(f"missing factor data at {first_bad.date()}; cannot compound")
    return total


def build_index(factors: pd.DataFrame, base: float = 100.0) -> pd.Series:
    """Compound monthly total returns into an index level series."""
    returns = market_total_return(factors)
    level = base * (1.0 + returns).cumprod()
    level.name = "level"
    return level


def load_index(
    cache: str | Path = "data/benchmarks/F-F_Research_Data_Factors_CSV.zip",
    start: str | None = None,
) -> pd.Series:
    """Download (once) and return the market total-return level series."""
    path = download_factors(cache)
    factors = parse_factors(path.read_bytes())
    if start:
        factors = factors.loc[start:]
    return build_index(factors)
