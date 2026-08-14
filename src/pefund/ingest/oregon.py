"""Adapter for the Oregon PERS (OPERF) private equity portfolio report.

Oregon publishes its private equity book quarterly as a PDF, and past
quarters stay online at predictable URLs. That archive is the reason this
adapter is worth the extra work over an HTML table: differencing consecutive
snapshots recovers approximate quarterly cash flows, which is what makes PME
and Direct Alpha computable on real data at all. CalPERS publishes cumulative
totals only, so a single plan gives no flows no matter how carefully it is
parsed.

Layout, one fund per line:

    [*] <vintage> <partnership name> $<commit> $<contrib> $<distrib> \
        $<fair value> [<multiple>x] [<IRR>% | n.m.]

All amounts are in millions of dollars and are converted to dollars here so
the frame is unit-compatible with the CalPERS adapter.

Three features of the source that the parser has to encode rather than
smooth over:

1.  A leading asterisk means the fund was SOLD IN THE SECONDARY MARKET.
    Oregon's own note says performance for such a fund "is not representative
    of the performance of that fund if it were held until its natural
    liquidation". A secondary sale truncates the fund's life at a negotiated
    price, so its TVPI is a transaction outcome, not a realisation. These
    rows are kept and flagged as `sold_secondary`, never silently pooled with
    funds that ran to term.

2.  Fair market value is occasionally negative and written in accounting
    parentheses, "($3.0)". That is a real reported value, usually a fund with
    accrued liabilities and no remaining assets, and it must not be read as
    positive.

3.  The multiple and the IRR are independently omitted. Young funds show
    "n.m." for both; a few rows carry a multiple with no IRR. The parser
    treats the two fields separately instead of assuming they travel together.

Oregon's own disclaimer, which belongs in the write-up: because the industry
lacks valuation standards, investment pace differs across partnerships, and
returns are understated early in a fund's life, the report states that its
IRRs DO NOT reflect current or expected returns, SHOULD NOT be used to assess
a partnership's success or to compare returns across partnerships, and HAVE
NOT been approved by the general partners. See `DISCLAIMER` below.
"""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

#: Observed URL pattern. Oregon has changed this before, so a failure to
#: fetch should send you to the Treasury holdings page rather than to a
#: retry loop.
OREGON_URL_TEMPLATE = (
    "https://www.oregon.gov/treasury/invested-for-oregon/Documents/"
    "Invested-for-OR-Performance-and-Holdings/{year}/"
    "OPERF_Private_Equity_Portfolio_-_Quarter_{quarter}_{year}.pdf"
)

SOURCE_NAME = "Oregon PERS OPERF"

#: Quoted so the limitations section can cite the plan rather than assert the
#: same point in the author's own voice.
DISCLAIMER = (
    "Due to a number of factors, including most importantly a lack of "
    "valuation standards in the private equity industry, differences in the "
    "pace of investments across partnerships and the understatement of "
    "returns in the early years of a partnership's life, the IRR information "
    "in this report DOES NOT accurately reflect the current or expected "
    "future returns of the partnership. The IRRs SHOULD NOT be used to assess "
    "the investment success of a partnership or to compare returns across "
    "partnerships. The IRRs in this report HAVE NOT been approved by the "
    "individual general partners of the partnerships."
)

MILLIONS = 1_000_000.0

#: One fund row. The money fields allow a leading "(" so that a negative fair
#: value written "($3.0)" is captured rather than skipped.
_MONEY = r"\(?-?\$-?[\d,]+\.?\d*\)?"
_ROW = re.compile(
    r"^(?P<secondary>\*\s+)?"
    r"(?P<vintage>(?:19|20)\d{2})\s+"
    r"(?P<name>.+?)\s+"
    rf"(?P<commitment>{_MONEY})\s+"
    rf"(?P<contributions>{_MONEY})\s+"
    rf"(?P<distributions>{_MONEY})\s+"
    rf"(?P<nav>{_MONEY})"
    r"(?P<tail>.*)$"
)

_MULTIPLE = re.compile(r"(-?[\d,]+\.?\d*)\s*x", re.I)
_PERCENT = re.compile(r"(-?[\d,]+\.?\d*)\s*%")
_NOT_MEANINGFUL = re.compile(r"n\.?\s*m\.?", re.I)
_AS_OF = re.compile(r"As of\s+(.+?)\s*$", re.I | re.M)


def _money_to_float(token: str) -> float:
    """'$1,234.5' -> 1234.5 ; '($3.0)' -> -3.0.

    Accounting parentheses mean negative. Reading them as positive would turn
    a fund with a residual liability into one with a residual asset.
    """
    negative = token.strip().startswith("(") or token.strip().startswith("-$")
    cleaned = re.sub(r"[^\d.]", "", token)
    if not cleaned:
        return np.nan
    value = float(cleaned)
    return -value if negative else value


def quarter_url(year: int, quarter: int) -> str:
    return OREGON_URL_TEMPLATE.format(year=year, quarter=quarter)


def download(year: int, quarter: int, dest: str | Path) -> Path:
    """Save one quarterly PDF. Never overwrites: the archive is the asset."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    request = urllib.request.Request(
        quarter_url(year, quarter), headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        dest.write_bytes(response.read())
    return dest


def extract_lines(pdf_path: str | Path) -> list[str]:
    """Every text line in the PDF, in reading order."""
    import pdfplumber  # imported lazily so the rest of the package needs no PDF stack

    lines: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").split("\n"))
    return lines


def parse_as_of(lines: list[str]) -> pd.Timestamp | None:
    """Reporting date from the 'As of September 30, 2025' banner."""
    for line in lines:
        match = _AS_OF.search(line.strip())
        if match:
            try:
                return pd.Timestamp(match.group(1))
            except ValueError:
                continue
    return None


def parse_lines(lines: list[str], as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Turn extracted PDF lines into the canonical snapshot schema."""
    if as_of is None:
        as_of = parse_as_of(lines)

    records = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.lower().startswith("total"):
            continue
        match = _ROW.match(line)
        if not match:
            continue

        name = match.group("name").strip()
        if not name or name.lower() == "partnership":
            continue

        tail = match.group("tail")
        multiple_match = _MULTIPLE.search(tail)
        percent_match = _PERCENT.search(tail)

        commitment = _money_to_float(match.group("commitment")) * MILLIONS
        contributions = _money_to_float(match.group("contributions")) * MILLIONS
        distributions = _money_to_float(match.group("distributions")) * MILLIONS
        nav = _money_to_float(match.group("nav")) * MILLIONS

        records.append(
            {
                "fund_id": f"OPERF::{name}",
                "fund_name": name,
                "vintage": int(match.group("vintage")),
                "commitment": commitment,
                "contributions": contributions,
                "distributions": distributions,
                "nav": nav,
                # Oregon reports distributed and fair value separately, so
                # total value is their sum rather than a published column.
                "total_value": distributions + nav,
                "reported_multiple": (
                    float(multiple_match.group(1).replace(",", ""))
                    if multiple_match
                    else np.nan
                ),
                "net_irr": (
                    float(percent_match.group(1).replace(",", "")) / 100.0
                    if percent_match
                    else np.nan
                ),
                "not_meaningful": bool(_NOT_MEANINGFUL.search(tail)),
                "sold_secondary": bool(match.group("secondary")),
                "source": SOURCE_NAME,
            }
        )

    df = pd.DataFrame.from_records(records)
    if df.empty:
        raise ValueError(
            "no fund rows parsed; the report layout has probably changed. "
            "Check the Oregon Treasury holdings page for the current format."
        )

    df["tvpi_reported"] = df["total_value"] / df["contributions"].replace(0, np.nan)
    df["as_of"] = as_of

    # Funds with no capital called yet are KEPT, with a NaN multiple. They
    # carry a real commitment, and dropping them here would be silent data
    # loss with a specific cost: a fund first seen at zero paid-in and drawn
    # down later is the only kind whose entire cash flow history is visible in
    # a snapshot archive, which is precisely what PME needs. Filter them out
    # in the analysis where a multiple is required, not in the parser.
    df["fully_uncalled"] = df["contributions"] <= 0

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
        "reported_multiple",
        "net_irr",
        "not_meaningful",
        "sold_secondary",
        "fully_uncalled",
        "source",
        "as_of",
    ]
    return df[keep].reset_index(drop=True)


def parse_pdf(pdf_path: str | Path) -> pd.DataFrame:
    """Parse a saved quarterly PDF into the canonical snapshot schema."""
    return parse_lines(extract_lines(pdf_path))


def load(year: int, quarter: int, cache_dir: str | Path = "data/snapshots/raw"):
    """Download (if needed) and parse one quarter."""
    path = download(
        year, quarter, Path(cache_dir) / f"oregon_operf_pe_{year}Q{quarter}.pdf"
    )
    return parse_pdf(path)
