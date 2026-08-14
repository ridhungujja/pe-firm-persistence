"""Loading real disclosure data into the canonical schema.

Public pension plans publish fund-level private equity performance under
state sunshine laws. That is the free substitute for Preqin or Burgiss, and
its limitations are the most interesting part of the project: you observe
only funds these particular LPs chose to commit to, which is selection on
the fund's ex-ante attractiveness to a large institutional investor.

Two shapes of data exist and they support different work:

    "snapshot"  fund, vintage, commitment, contributions, distributions,
                NAV, net IRR, as of one reporting date. Most plans publish
                this. Enough for TVPI/DPI/IRR and persistence regressions.
                NOT enough for PME, which needs dated cash flows.

    "cash flow" dated contributions and distributions per fund. Rarer;
                some plans publish it, and it can be reconstructed
                approximately by differencing consecutive snapshots.

`ks_pme` and `direct_alpha` require the second shape. If you only have
snapshots, either restrict the analysis to multiples and IRR, or reconstruct
quarterly flows by differencing and say plainly in the write-up that the
reconstruction is an approximation.

Network note: fetching these files needs outbound access to state pension
domains, so run the download step on your own machine rather than in a
sandbox with a domain allowlist.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..metrics import FundCashFlows

#: Columns every ingested snapshot must provide before analysis.
SNAPSHOT_SCHEMA: dict[str, str] = {
    "fund_id": "unique key, usually source + fund name",
    "fund_name": "as reported",
    "firm_id": "GP identifier; needs manual normalisation, see note below",
    "vintage": "int year",
    "commitment": "capital committed by the reporting LP",
    "contributions": "cumulative paid-in",
    "distributions": "cumulative distributed",
    "nav": "reported residual value",
    "as_of": "reporting date of nav",
    "source": "which plan published the row",
}

CASHFLOW_SCHEMA: dict[str, str] = {
    "fund_id": "matches the snapshot key",
    "date": "cash flow date",
    "amount": "signed, negative = call, positive = distribution",
}


@dataclass(frozen=True)
class Source:
    name: str
    plan: str
    shape: str  # "snapshot" or "cash flow"
    notes: str


#: Where to get the data. URLs move; search the plan's investment
#: transparency or "AIM program" page rather than hard-coding a link.
SOURCES: tuple[Source, ...] = (
    Source(
        "CalPERS PE Program Fund Performance",
        "California Public Employees' Retirement System",
        "snapshot",
        "Longest history and the widest manager coverage. Published as a "
        "quarterly table with cash-in, cash-out, NAV and net IRR.",
    ),
    Source(
        "CalSTRS Private Equity Portfolio Performance",
        "California State Teachers' Retirement System",
        "snapshot",
        "Overlaps heavily with CalPERS. Overlap is useful: the same fund "
        "reported by two LPs is a check on NAV reporting consistency.",
    ),
    Source(
        "Oregon PERS Private Equity Returns",
        "Oregon Public Employees Retirement Fund",
        "snapshot",
        "Early and consistent discloser; good vintage depth back to the 1980s.",
    ),
    Source(
        "Washington State Investment Board PE Returns",
        "Washington State Investment Board",
        "snapshot",
        "Heavy buyout concentration, useful for a single-strategy sample.",
    ),
    Source(
        "TRS Texas Private Markets Report",
        "Teacher Retirement System of Texas",
        "snapshot",
        "More recent vintages; helps balance a sample skewed to the 1990s.",
    ),
)


def normalise_firm_ids(funds: pd.DataFrame, name_col: str = "fund_name") -> pd.Series:
    """First-pass GP identifier from fund names.

    Strips the fund number so that "Blackstone Capital Partners VII" and
    "Blackstone Capital Partners VI" map to one firm. This is a starting
    point, not a solution: name changes, spin-outs, and joint ventures all
    break it, and the persistence regression is only as good as this mapping.
    Hand-check the largest firms and keep the corrections in a CSV that is
    version controlled alongside the code.
    """
    roman = r"\s+(?:[IVXLC]+|\d+)\s*$"
    cleaned = (
        funds[name_col]
        .str.replace(r"[,\.]", "", regex=True)
        .str.replace(
            r"\s+(?:L\.?P\.?|LLC|Ltd|Fund|Partners)?\s*$", "", regex=True
        )
        .str.replace(roman, "", regex=True)
        .str.strip()
        .str.upper()
    )
    return cleaned


#: Hand-checked corrections to `normalise_firm_ids`, version controlled next
#: to the code as the README roadmap requires.
DEFAULT_OVERRIDES_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "firm_overrides.csv"
)


def load_firm_overrides(path: str | Path | None = None) -> pd.DataFrame:
    """Read the hand-checked firm mapping.

    Returns an empty frame if the file is absent, so the pipeline runs before
    anyone has reviewed a single name. Lines starting with `#` are comments.
    """
    path = Path(path) if path is not None else DEFAULT_OVERRIDES_PATH
    cols = ["firm_id_raw", "firm_id_canonical", "decision", "confidence", "reason"]
    if not Path(path).exists():
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, comment="#", dtype=str).fillna("")
    missing = set(cols) - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")

    bad = set(df["decision"]) - {"merge", "keep_separate"}
    if bad:
        raise ValueError(f"{path} has unknown decision values: {sorted(bad)}")

    dupes = df.loc[df["firm_id_raw"].duplicated(), "firm_id_raw"].tolist()
    if dupes:
        raise ValueError(f"{path} maps the same stem twice: {sorted(set(dupes))}")

    # A merge target that is itself a merge source would make the result
    # depend on row order. Require the mapping to be flat.
    merges = df[df["decision"] == "merge"]
    chained = set(merges["firm_id_canonical"]) & set(merges["firm_id_raw"])
    if chained:
        raise ValueError(f"{path} chains merges through: {sorted(chained)}")
    return df


def apply_firm_overrides(
    firm_ids: pd.Series, overrides: pd.DataFrame | None = None
) -> pd.Series:
    """Remap raw stems onto hand-checked family identifiers.

    Deliberately a lookup rather than a looser regex. The stem rule in
    `normalise_firm_ids` fails in both directions and only one of them is
    safe to fix automatically: share classes and feeder tags block the numeral
    strip and split one series across several stems, while co-investment
    sleeves and annex funds legitimately deserve their own identity. No
    pattern separates those two cases, so the decisions are recorded by hand.
    """
    if overrides is None:
        overrides = load_firm_overrides()
    if overrides.empty:
        return firm_ids

    merges = overrides[overrides["decision"] == "merge"]
    mapping = dict(zip(merges["firm_id_raw"], merges["firm_id_canonical"]))

    # keep_separate rows may name a family that only exists after merging, so
    # they are not evidence of a stale mapping.
    stale = set(overrides["firm_id_raw"]) - set(firm_ids) - set(mapping.values())
    if stale:
        warnings.warn(
            f"{len(stale)} override rows match no fund in this snapshot; "
            f"the source table may have been restated: {sorted(stale)[:5]}",
            stacklevel=2,
        )
    return firm_ids.map(lambda x: mapping.get(x, x))


#: Entity, domicile and feeder wording that carries no fund number. Removed
#: before parsing so that the "L" of "L.P." is not read as roman 50.
_ENTITY_WORDS = re.compile(
    r"\b(?:L\s*\.?\s*P\s*\.?\s*\d*|LLC|LTD|LIMITED\s+PARTNERSHIP|PARTNERSHIP"
    r"|S\s*\.?\s*C\s*\.?\s*SP|SCSP|S\s*\.?\s*L\s*\.?\s*P|SLP|ILP|INC|PLC"
    r"|COOPERATIEF\s+U\s*\.?\s*A|COOPERATIEF|A\s+DELAWARE|DELAWARE"
    r"|GMBH|SARL|BV|NV|SA|AB|KG|USD|EUR|GBP)\b",
    flags=re.I,
)

#: Well-formed roman numeral up to C. The lookahead stops the empty match.
_ROMAN_RE = re.compile(r"^(?=[IVXLC])C{0,3}(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$")
_ROMAN_DIGITS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

#: No GP in a public-plan sample is on fund 60. Anything larger parsed out of
#: a name is a year ("KKR 2006 Fund") or an acronym that happens to be
#: spellable in roman letters, not a series designator.
MAX_FUND_NUMBER = 60


def _roman_to_int(token: str) -> int:
    total = 0
    for i, ch in enumerate(token):
        value = _ROMAN_DIGITS[ch]
        nxt = _ROMAN_DIGITS.get(token[i + 1]) if i + 1 < len(token) else None
        total += -value if nxt is not None and nxt > value else value
    return total


def parse_fund_number(names: pd.Series) -> pd.Series:
    """Extract the series designator from a fund name as an integer.

    Handles roman ("Blackstone Capital Partners V") and arabic ("Triton Fund
    6") numbering, and looks through the share-class and feeder tags that sit
    after the number ("Advent International GPE VII-C", "CVC Capital Partners
    IX (A)").

    Returns NaN where the name carries no number. That is not a failure: a
    first fund is usually unnumbered ("KKR Asian Fund", "The Rise Fund"), and
    the caller must decide whether to treat it as fund 1 or leave it out. It
    is left as NaN here so the decision is explicit at the call site rather
    than assumed once, invisibly, in the parser.

    The first number wins, not the last. Overage vehicles name the generation
    before their own sequence ("Genstar XI Opportunities Fund I"), and the
    generation is what distinguishes them from their siblings.
    """

    def one(name: object) -> float:
        if not isinstance(name, str):
            return np.nan
        cleaned = _ENTITY_WORDS.sub(" ", name.upper())
        cleaned = re.sub(r"[^\w\s-]", " ", cleaned)
        tokens = cleaned.split()
        # Skip the first token: a leading number belongs to the firm's name
        # ("57 Stars Global Opportunities Fund 2", "2024 Golden Bay").
        for token in tokens[1:]:
            head = token.split("-")[0]
            if not head:
                continue
            if head.isdigit():
                value = int(head)
            elif _ROMAN_RE.match(head):
                value = _roman_to_int(head)
            else:
                continue
            if 0 < value <= MAX_FUND_NUMBER:
                return float(value)
        return np.nan

    return names.map(one)


#: Columns that are additive across share classes of one fund.
_SHARE_CLASS_SUM_COLS = ("commitment", "contributions", "distributions", "nav")


def deduplicate_share_classes(
    funds: pd.DataFrame,
    family_col: str = "firm_id",
    number_col: str = "fund_number",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collapse share classes of one fund into a single row.

    Public plans commit to several feeders of the same partnership and report
    each separately: "Bridgepoint Europe III 'C'" and "Bridgepoint Europe III
    'D'" are one fund. Left alone they invent a sequence step, double-count
    committed capital, and hand the AR(1) regression a pair of observations
    whose "persistence" is an accounting identity rather than skill.

    Rows sharing a (family, fund number) key are aggregated. Cash columns are
    summed; the vintage is the earliest reported, which also repairs the case
    where one class is stamped with the LP's commitment date instead of the
    fund's vintage.

    `net_irr` is set to NaN on every collapsed row and never averaged. An IRR
    is the root of a polynomial in dated cash flows, so a commitment-weighted
    mean of two class IRRs is not the IRR of the combined position and can sit
    outside the range of its inputs. The recomputed multiple is the usable
    figure for aggregated rows; a true combined IRR needs the dated flows,
    which a single snapshot does not carry.

    Returns (deduplicated funds, report of collapsed groups).
    """
    for col in (family_col, number_col):
        if col not in funds.columns:
            raise ValueError(f"deduplicate_share_classes needs a {col!r} column")

    df = funds.copy()
    # A missing fund number cannot be matched to anything, so those rows are
    # never collapsed. Grouping them would pool every unnumbered vehicle in a
    # family into one row.
    keyed = df[number_col].notna()
    counts = df[keyed].groupby([family_col, number_col])["fund_id"].transform("size")
    collapsing = pd.Series(False, index=df.index)
    collapsing.loc[keyed] = counts > 1

    df["n_share_classes"] = 1
    if not collapsing.any():
        return df, pd.DataFrame(
            columns=[family_col, number_col, "n_share_classes", "fund_names", "vintages"]
        )

    report_rows = []
    aggregated = []
    for (family, number), group in df[collapsing].groupby([family_col, number_col]):
        # The representative row is the largest commitment: its fund_id and
        # name are the ones a reader is most likely to recognise.
        rep = group.sort_values("commitment", ascending=False).iloc[0].copy()
        for col in _SHARE_CLASS_SUM_COLS:
            if col in group.columns:
                rep[col] = group[col].sum()
        if "distributions" in group.columns and "nav" in group.columns:
            rep["total_value"] = group["distributions"].sum() + group["nav"].sum()
        elif "total_value" in group.columns:
            rep["total_value"] = group["total_value"].sum()
        if "tvpi_reported" in group.columns:
            paid_in = rep.get("contributions", np.nan)
            rep["tvpi_reported"] = (
                rep["total_value"] / paid_in if paid_in and paid_in > 0 else np.nan
            )
        if "vintage" in group.columns:
            rep["vintage"] = group["vintage"].min()
        if "as_of" in group.columns:
            rep["as_of"] = group["as_of"].max()
        if "not_meaningful" in group.columns:
            rep["not_meaningful"] = bool(group["not_meaningful"].any())
        if "net_irr" in group.columns:
            rep["net_irr"] = np.nan
        rep["n_share_classes"] = len(group)
        aggregated.append(rep)

        report_rows.append(
            {
                family_col: family,
                number_col: number,
                "n_share_classes": len(group),
                "fund_names": " | ".join(group["fund_name"].astype(str)),
                "vintages": ";".join(str(int(v)) for v in sorted(group["vintage"])),
                "vintage_kept": int(group["vintage"].min()),
                "commitment_total": float(group["commitment"].sum()),
                "net_irr_dropped": ";".join(
                    "" if pd.isna(v) else f"{v:.3f}" for v in group.get("net_irr", [])
                ),
            }
        )

    out = pd.concat(
        [df[~collapsing], pd.DataFrame(aggregated)], ignore_index=True
    )
    return out, pd.DataFrame(report_rows)


def add_sequence_numbers(funds: pd.DataFrame) -> pd.DataFrame:
    """Rank each firm's funds by vintage to get the sequence number.

    Ties within a vintage are broken by commitment size, arbitrarily but
    reproducibly. A firm that raised two funds in one year is usually running
    parallel vehicles, which the AR(1) framing does not handle cleanly; flag
    those rather than pretending the ordering is meaningful.
    """
    out = funds.sort_values(["firm_id", "vintage", "commitment"]).copy()
    out["sequence"] = out.groupby("firm_id").cumcount() + 1
    dupes = out.duplicated(subset=["firm_id", "vintage"], keep=False)
    out["parallel_vintage"] = dupes
    return out


#: How far a fund's vintage may sit from its family's implied trend before it
#: is called suspect. Successive funds in a series are typically three to four
#: years apart, so a residual beyond this is a reporting artefact rather than
#: an unusually long or short fundraising cycle.
VINTAGE_TREND_TOLERANCE = 3.0


def flag_vintage_anomalies(
    funds: pd.DataFrame,
    family_col: str = "firm_id",
    number_col: str = "fund_number",
    tolerance: float = VINTAGE_TREND_TOLERANCE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Flag funds whose reported vintage contradicts their place in the series.

    Public plans sometimes stamp a row with the date the LP committed rather
    than the fund's vintage year, which puts a 2005 fund in 2015. That is not
    a harmless label: vintage fixed effects absorb the market environment a
    fund invested into, so a mis-stamped row is assigned the wrong control and
    contaminates the effect for every fund genuinely in that year.

    Two independent checks, because they catch different errors:

    order  within a family, fund numbers and vintages must both increase. A
           pair that disagrees means one of the two rows is wrong, and the
           check cannot say which.

    trend  regress vintage on fund number within the family and flag residuals
           beyond `tolerance` years. This catches a row that preserves the
           ordering but is still years adrift, which the order check misses.
           Needs three or more numbered funds to have a residual worth reading.

    Nothing is corrected. A vintage is either right or unknown, and guessing a
    replacement would put a fabricated year into the fixed effects with no way
    for a reader to tell it from a reported one. The caller decides whether to
    drop these rows, and both estimates should be shown.

    Returns (funds with a `vintage_anomaly` bool column, report of flagged rows).
    """
    df = funds.copy()
    df["vintage_anomaly"] = False
    df["vintage_anomaly_reason"] = ""

    if number_col not in df.columns:
        raise ValueError(f"flag_vintage_anomalies needs a {number_col!r} column")

    for family, group in df.groupby(family_col):
        numbered = group.dropna(subset=[number_col, "vintage"])
        if len(numbered) < 2:
            continue
        numbered = numbered.sort_values(number_col)
        numbers = numbered[number_col].to_numpy(dtype=float)
        vintages = numbered["vintage"].to_numpy(dtype=float)

        # order: a later fund number must not carry an earlier vintage.
        for pos in range(1, len(numbered)):
            if vintages[pos] < vintages[pos - 1]:
                for idx in (numbered.index[pos], numbered.index[pos - 1]):
                    df.loc[idx, "vintage_anomaly"] = True
                    df.loc[idx, "vintage_anomaly_reason"] = (
                        f"fund number order contradicts vintage order "
                        f"(#{int(numbers[pos - 1])}={int(vintages[pos - 1])} vs "
                        f"#{int(numbers[pos])}={int(vintages[pos])})"
                    )

        # trend: residual from the family's own fundraising cadence.
        if len(numbered) >= 3 and len(set(numbers)) >= 2:
            slope, intercept = np.polyfit(numbers, vintages, 1)
            residuals = vintages - (slope * numbers + intercept)
            for idx, resid in zip(numbered.index, residuals):
                if abs(resid) > tolerance:
                    df.loc[idx, "vintage_anomaly"] = True
                    existing = df.loc[idx, "vintage_anomaly_reason"]
                    note = f"{resid:+.1f}y from the family's fund-number trend"
                    df.loc[idx, "vintage_anomaly_reason"] = (
                        f"{existing}; {note}" if existing else note
                    )

    cols = [
        c
        for c in [
            "fund_id",
            "fund_name",
            family_col,
            number_col,
            "vintage",
            "vintage_anomaly_reason",
        ]
        if c in df.columns
    ]
    report = df.loc[df["vintage_anomaly"], cols].sort_values([family_col, number_col])
    return df, report.reset_index(drop=True)


def validate_snapshot(funds: pd.DataFrame) -> pd.DataFrame:
    """Check schema and flag rows that will poison the estimates."""
    missing = set(SNAPSHOT_SCHEMA) - set(funds.columns)
    if missing:
        raise ValueError(f"snapshot is missing columns: {sorted(missing)}")

    out = funds.copy()
    out["flag_zero_paid_in"] = out["contributions"] <= 0
    out["flag_negative_nav"] = out["nav"] < 0
    out["flag_unfunded"] = out["contributions"] < 0.1 * out["commitment"]
    out["flag_young"] = out["vintage"] > pd.Timestamp(out["as_of"].max()).year - 5

    # A fund three years old is mostly unrealised NAV, and its TVPI is the
    # GP's own mark rather than a realisation. Keep the rows, flag them, and
    # show the regression with and without.
    return out


def cash_flows_from_long(
    flows: pd.DataFrame, snapshots: pd.DataFrame
) -> list[FundCashFlows]:
    """Assemble FundCashFlows objects from a long cash flow table."""
    missing = set(CASHFLOW_SCHEMA) - set(flows.columns)
    if missing:
        raise ValueError(f"cash flow table is missing columns: {sorted(missing)}")

    navs = snapshots.set_index("fund_id")[["nav", "as_of"]]
    out: list[FundCashFlows] = []
    for fund_id, group in flows.sort_values("date").groupby("fund_id"):
        if fund_id not in navs.index:
            continue
        nav, as_of = navs.loc[fund_id, "nav"], pd.Timestamp(navs.loc[fund_id, "as_of"])
        dates = pd.DatetimeIndex(group["date"])
        if as_of < dates[-1]:
            as_of = dates[-1]
        out.append(
            FundCashFlows(
                fund_id=str(fund_id),
                dates=dates,
                amounts=group["amount"].to_numpy(dtype=float),
                nav=float(nav),
                nav_date=as_of,
            )
        )
    return out


def resolve_snapshot(data_dir: str | Path, prefix: str) -> Path:
    """Find a snapshot: the working copy, else the newest dated archive copy.

    The working copies in data/ are rebuilt by the fetch scripts and are
    gitignored, so a fresh clone has only the dated archive. Offline
    reproduction has to work from that, which means every consumer needs the
    fallback rather than just the two that happened to be tested.
    """
    data_dir = Path(data_dir)
    working = data_dir / f"{prefix}_snapshot.csv"
    if working.exists():
        return working
    archived = sorted((data_dir / "snapshots").glob(f"{prefix}_[0-9]*.csv"))
    if archived:
        return archived[-1]
    raise SystemExit(
        f"no {prefix} snapshot found in {data_dir} or its snapshots/ archive; "
        f"run: python analysis/fetch_{prefix}.py"
    )


def funds_observed_from_inception(panel: pd.DataFrame) -> pd.Index:
    """Funds whose entire cash flow history falls inside a snapshot archive.

    Differencing consecutive snapshots recovers flows that happen *between*
    snapshots. Flows before the archive starts are unrecoverable, and
    `reconstruct_flows_from_snapshots` dates the whole opening cumulative
    balance at the first snapshot instead.

    For a multiple that is harmless -- TVPI does not care when money moved.
    For PME it is fatal, because PME discounts each flow by the market return
    since that flow's date. Dating twenty years of capital calls at a single
    day prices them all at one index level and yields a number with no
    interpretation. Worse, it fails silently: the result looks plausible.

    A fund is safe only if its first appearance shows zero paid-in capital, so
    that the first real call is observed. Callers should compute PME on this
    subset and leave the rest NaN rather than approximating.
    """
    required = {"fund_id", "as_of", "contributions"}
    if not required <= set(panel.columns):
        raise ValueError(f"need columns {sorted(required)}")

    ordered = panel.sort_values(["fund_id", "as_of"])
    first = ordered.groupby("fund_id").first()
    n_dates = ordered.groupby("fund_id")["as_of"].nunique()
    return first.index[(first["contributions"] <= 0) & (n_dates >= 2)]


def load_benchmark(path: str, date_col: str = "date", level_col: str = "level") -> pd.Series:
    """Load a total-return index level series.

    Use a total-return series, not a price series. The S&P 500 price index
    excludes roughly two points a year of dividends, which flatters every
    PME in the panel by a compounding margin over a ten-year fund life.
    """
    df = pd.read_csv(path, parse_dates=[date_col])
    series = df.set_index(date_col)[level_col].sort_index().astype(float)
    if (series <= 0).any():
        raise ValueError("benchmark levels must be strictly positive")
    if series.pct_change().abs().max() > 0.5:
        raise ValueError("benchmark has a >50% single-period move; check for splits")
    return series


def reconstruct_flows_from_snapshots(panel: pd.DataFrame) -> pd.DataFrame:
    """Difference consecutive snapshots into approximate quarterly flows.

    Requires a panel of the *same* funds observed at several `as_of` dates.
    Contributions and distributions are cumulative in these disclosures, so
    the period flow is the first difference. Two caveats to state in the
    write-up: within-quarter timing is lost (flows are dated at quarter end,
    which biases IRRs slightly), and any restatement shows up as a negative
    flow that has to be zeroed rather than passed through.
    """
    required = {"fund_id", "as_of", "contributions", "distributions"}
    if not required <= set(panel.columns):
        raise ValueError(f"need columns {sorted(required)}")

    df = panel.sort_values(["fund_id", "as_of"]).copy()
    g = df.groupby("fund_id")
    df["call"] = g["contributions"].diff().fillna(df["contributions"]).clip(lower=0)
    df["dist"] = g["distributions"].diff().fillna(df["distributions"]).clip(lower=0)
    df["amount"] = df["dist"] - df["call"]
    df["date"] = pd.to_datetime(df["as_of"])
    return df.loc[df["amount"] != 0, ["fund_id", "date", "amount"]].reset_index(drop=True)
