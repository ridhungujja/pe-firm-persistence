"""Fund-level performance metrics for private equity cash flow streams.

Conventions
-----------
Cash flows are stated from the *limited partner's* perspective:
    contributions (capital calls) are NEGATIVE
    distributions                 are POSITIVE
Residual NAV is held separately and treated as a terminal distribution
when computing since-inception metrics.

References
----------
Kaplan & Schoar (2005), "Private Equity Performance: Returns, Persistence,
    and Capital Flows", Journal of Finance 60(4).
Gredil, Griffiths & Stucke (2014), "Benchmarking Private Equity: The Direct
    Alpha Method".
Long & Nickels (1996), "A Private Investment Benchmark".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq

DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class FundCashFlows:
    """A single fund's cash flow history plus its residual value.

    Parameters
    ----------
    dates : DatetimeIndex of cash flow dates, sorted ascending.
    amounts : signed cash flows to the LP (negative = call, positive = dist).
    nav : residual net asset value as of `nav_date`.
    nav_date : valuation date of `nav`.
    """

    fund_id: str
    dates: pd.DatetimeIndex
    amounts: np.ndarray
    nav: float
    nav_date: pd.Timestamp

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.amounts):
            raise ValueError(f"{self.fund_id}: dates and amounts length mismatch")
        if not self.dates.is_monotonic_increasing:
            raise ValueError(f"{self.fund_id}: dates must be sorted ascending")
        if self.nav_date < self.dates[-1]:
            raise ValueError(f"{self.fund_id}: nav_date precedes last cash flow")

    @property
    def contributions(self) -> float:
        """Total paid-in capital (positive number)."""
        return float(-self.amounts[self.amounts < 0].sum())

    @property
    def distributions(self) -> float:
        return float(self.amounts[self.amounts > 0].sum())

    def terminal_flows(self) -> tuple[pd.DatetimeIndex, np.ndarray]:
        """Cash flows with residual NAV appended as a terminal distribution."""
        if self.nav_date == self.dates[-1]:
            dates = self.dates
            amounts = self.amounts.copy()
            amounts[-1] += self.nav
        else:
            dates = self.dates.append(pd.DatetimeIndex([self.nav_date]))
            amounts = np.append(self.amounts, self.nav)
        return dates, amounts


# ---------------------------------------------------------------- multiples


def dpi(cf: FundCashFlows) -> float:
    """Distributions to paid-in."""
    return cf.distributions / cf.contributions if cf.contributions else np.nan


def rvpi(cf: FundCashFlows) -> float:
    """Residual value to paid-in."""
    return cf.nav / cf.contributions if cf.contributions else np.nan


def tvpi(cf: FundCashFlows) -> float:
    """Total value to paid-in. Note this is *not* time-weighted."""
    return dpi(cf) + rvpi(cf)


# --------------------------------------------------------------------- IRR


def xnpv(rate: float, dates: pd.DatetimeIndex, amounts: np.ndarray) -> float:
    """Net present value of irregularly spaced cash flows."""
    if rate <= -1.0:
        return np.inf
    years = (dates - dates[0]).days.to_numpy() / DAYS_PER_YEAR
    return float(np.sum(amounts / (1.0 + rate) ** years))


def xirr(
    dates: pd.DatetimeIndex,
    amounts: np.ndarray,
    lo: float = -0.9999,
    hi: float = 100.0,
) -> float:
    """Annualised money-weighted return on irregularly spaced cash flows.

    Returns NaN when no sign change exists on [lo, hi], which happens for
    funds that have returned less than they called with no residual value,
    and for degenerate all-positive streams. NaN is the honest answer here:
    a bracketing failure is not a zero return.
    """
    amounts = np.asarray(amounts, dtype=float)
    if len(amounts) < 2 or not (amounts.min() < 0 < amounts.max()):
        return np.nan
    f_lo, f_hi = xnpv(lo, dates, amounts), xnpv(hi, dates, amounts)
    if np.isnan(f_lo) or np.isnan(f_hi) or f_lo * f_hi > 0:
        return np.nan
    return float(brentq(xnpv, lo, hi, args=(dates, amounts), xtol=1e-10))


def fund_irr(cf: FundCashFlows) -> float:
    """Since-inception IRR treating residual NAV as a terminal distribution.

    Caveat for the write-up: IRR assumes interim distributions are reinvested
    at the IRR itself, and IRRs are not additive across funds. Aggregating
    fund IRRs by averaging is wrong; pool the cash flows instead.
    """
    dates, amounts = cf.terminal_flows()
    return xirr(dates, amounts)


# ---------------------------------------------------- public-market metrics


def _index_at(index: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """Index level on each date, carrying the last observation forward.

    `index` must be a total-return level series (dividends reinvested),
    not a price series. Using a price index understates the benchmark and
    mechanically inflates every PME in the panel.
    """
    if not index.index.is_monotonic_increasing:
        index = index.sort_index()
    aligned = index.reindex(index.index.union(dates)).ffill().reindex(dates)
    if aligned.isna().any():
        missing = dates[aligned.isna()]
        raise ValueError(f"benchmark has no value on or before {missing[0].date()}")
    return aligned.to_numpy(dtype=float)


def ks_pme(cf: FundCashFlows, index: pd.Series) -> float:
    """Kaplan-Schoar PME: index-discounted distributions over contributions.

    PME = [ sum(D_t / I_t) + NAV_T / I_T ] / sum(C_t / I_t)

    A value of 1.0 means the fund exactly matched the benchmark on a
    dollar-weighted basis. Interpretation is a *wealth ratio*, not a return:
    PME of 1.2 does not mean 20% annualised outperformance.
    """
    dates, amounts = cf.terminal_flows()
    levels = _index_at(index, dates)
    discounted = amounts / levels
    inflows = discounted[discounted > 0].sum()
    outflows = -discounted[discounted < 0].sum()
    return float(inflows / outflows) if outflows else np.nan


def direct_alpha(cf: FundCashFlows, index: pd.Series) -> float:
    """Direct Alpha: annualised excess return over the benchmark.

    Each cash flow is compounded forward to the horizon at the realised
    benchmark return, then the IRR of that adjusted stream is taken. Unlike
    KS-PME this is expressed as a rate and is comparable across horizons.
    Returned as a simple annual rate; take log1p for the continuously
    compounded version used in Gredil et al.
    """
    dates, amounts = cf.terminal_flows()
    levels = _index_at(index, dates)
    adjusted = amounts * (levels[-1] / levels)
    return xirr(dates, adjusted)


def ln_pme(cf: FundCashFlows, index: pd.Series) -> float:
    """Long-Nickels PME: IRR of the fund's flows against a replicating
    benchmark portfolio's terminal value.

    Known failure mode: when the fund strongly outperforms, the short
    benchmark position can drive the replicating NAV negative and the IRR
    becomes meaningless. NaN is returned in that case rather than a number
    that looks usable.
    """
    dates, amounts = cf.terminal_flows()
    levels = _index_at(index, dates)
    # Value of the benchmark portfolio built from the fund's own flows.
    replicating_nav = -float(np.sum(amounts[:-1] * (levels[-1] / levels[:-1])))
    if replicating_nav <= 0:
        return np.nan
    ln_amounts = amounts.copy()
    ln_amounts[-1] = replicating_nav
    return xirr(dates, ln_amounts)


# ------------------------------------------------------------------ summary


def summarise(cf: FundCashFlows, index: pd.Series | None = None) -> dict:
    """All metrics for one fund as a flat record."""
    out = {
        "fund_id": cf.fund_id,
        "paid_in": cf.contributions,
        "distributed": cf.distributions,
        "nav": cf.nav,
        "dpi": dpi(cf),
        "rvpi": rvpi(cf),
        "tvpi": tvpi(cf),
        "irr": fund_irr(cf),
    }
    if index is not None:
        out["ks_pme"] = ks_pme(cf, index)
        out["direct_alpha"] = direct_alpha(cf, index)
        out["ln_pme"] = ln_pme(cf, index)
    return out


def summarise_panel(
    flows: list[FundCashFlows], index: pd.Series | None = None
) -> pd.DataFrame:
    return pd.DataFrame([summarise(cf, index) for cf in flows])
