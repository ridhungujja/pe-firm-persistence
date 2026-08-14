"""Simulated fund universe with a *known* data-generating process.

The point of this module is not to fake data for a demo. It is to give the
estimators in `pefund.persistence` a world where the true persistence
coefficient is known, so we can check whether the regression recovers it and
measure how far off it goes once realistic sample problems are introduced:

    - endogenous fundraising (a GP only raises fund k+1 after a decent fund k)
    - look-ahead bias (predecessor performance measured at final value rather
      than at the successor's fundraise date)
    - stale interim NAVs

Cash flow timing follows the Takahashi-Alexander (2002) commitment model:
capital is called at a decaying rate against uncalled commitment, and value
is distributed at a rate that rises with fund age.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..metrics import FundCashFlows

QUARTERS_PER_YEAR = 4


@dataclass
class SimulationConfig:
    n_firms: int = 220
    first_vintage: int = 1995
    last_vintage: int = 2016
    years_between_funds: int = 4
    fund_life_years: int = 12

    # Performance process: log(TVPI) = mu + theta_firm + vintage_effect + eps
    mu_log_tvpi: float = 0.55
    sd_skill: float = 0.18  # sd of theta across firms
    sd_idiosyncratic: float = 0.34  # sd of eps within firm
    sd_vintage_effect: float = 0.20

    # Fundraising rule. A GP raises a successor only if interim TVPI at the
    # fundraise date clears this bar. Set to 0.0 to switch selection off.
    successor_tvpi_threshold: float = 1.05
    max_funds_per_firm: int = 6

    # Takahashi-Alexander parameters
    call_rate: float = 0.28  # quarterly rate against uncalled commitment
    distribution_exponent: float = 2.4  # "bow" of the distribution curve
    yield_rate: float = 0.02

    # Benchmark index (quarterly geometric Brownian motion, total return)
    index_drift: float = 0.085
    index_vol: float = 0.16
    market_beta: float = 1.1  # loading of fund log-TVPI on realised market

    seed: int = 20260813


@dataclass
class SimulatedUniverse:
    funds: pd.DataFrame
    cash_flows: list[FundCashFlows]
    index: pd.Series
    true_skill: pd.Series = field(repr=False)
    config: SimulationConfig = field(repr=False)


def _quarter_ends(start: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="QE")


def simulate_index(cfg: SimulationConfig, rng: np.random.Generator) -> pd.Series:
    """Quarterly total-return index level, normalised to 100 at inception."""
    n = (cfg.last_vintage + cfg.fund_life_years - cfg.first_vintage + 2) * 4
    dates = _quarter_ends(pd.Timestamp(f"{cfg.first_vintage}-01-01"), n)
    dt = 1 / QUARTERS_PER_YEAR
    shocks = rng.normal(
        (cfg.index_drift - 0.5 * cfg.index_vol**2) * dt,
        cfg.index_vol * np.sqrt(dt),
        size=n,
    )
    return pd.Series(100 * np.exp(np.cumsum(shocks)), index=dates, name="index")


def _ta_cash_flows(
    commitment: float,
    target_tvpi: float,
    start: pd.Timestamp,
    cfg: SimulationConfig,
    rng: np.random.Generator,
) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    """Generate one fund's quarterly flows and its NAV path.

    Returns (dates, signed cash flows, nav path). Distributions and terminal
    NAV are scaled so that realised TVPI equals `target_tvpi` exactly; the
    timing shape is left untouched.
    """
    n = cfg.fund_life_years * QUARTERS_PER_YEAR
    dates = _quarter_ends(start, n)
    uncalled = commitment
    nav = 0.0
    calls = np.zeros(n)
    dists = np.zeros(n)
    navs = np.zeros(n)
    growth = (target_tvpi ** (1 / cfg.fund_life_years)) - 1

    for t in range(n):
        rate = cfg.call_rate * (1.0 if t < 4 else 0.75)
        call = uncalled * rate if t < n - 4 else 0.0
        uncalled -= call
        nav = nav * (1 + growth / QUARTERS_PER_YEAR) + call
        age = (t + 1) / QUARTERS_PER_YEAR
        d_rate = max(
            cfg.yield_rate,
            (age / cfg.fund_life_years) ** cfg.distribution_exponent,
        )
        dist = nav * d_rate / QUARTERS_PER_YEAR * 4 if t >= 6 else 0.0
        dist = min(dist, nav)
        nav -= dist
        calls[t], dists[t], navs[t] = call, dist, nav

    paid_in = calls.sum()
    realised = (dists.sum() + navs[-1]) / paid_in
    scale = target_tvpi / realised
    dists *= scale
    navs *= scale
    # Small reporting noise on interim NAVs: GPs mark to model, quarterly.
    navs *= np.exp(rng.normal(0, 0.03, size=n))
    return dates, dists - calls, navs


def simulate(cfg: SimulationConfig | None = None) -> SimulatedUniverse:
    cfg = cfg or SimulationConfig()
    rng = np.random.default_rng(cfg.seed)
    index = simulate_index(cfg, rng)

    vintages = np.arange(cfg.first_vintage, cfg.last_vintage + 1)
    vintage_effect = pd.Series(
        rng.normal(0, cfg.sd_vintage_effect, size=len(vintages)), index=vintages
    )
    skill = pd.Series(
        rng.normal(0, cfg.sd_skill, size=cfg.n_firms),
        index=[f"GP{i:03d}" for i in range(cfg.n_firms)],
        name="true_skill",
    )

    records: list[dict] = []
    flows: list[FundCashFlows] = []

    for firm_id, theta in skill.items():
        vintage = int(rng.choice(vintages[: max(1, len(vintages) - 8)]))
        commitment = float(np.exp(rng.normal(np.log(300), 0.7)))  # $mm

        for seq in range(1, cfg.max_funds_per_firm + 1):
            if vintage > cfg.last_vintage:
                break
            # Realised market return over the fund's life, in logs.
            start = pd.Timestamp(f"{vintage}-01-01")
            end = start + pd.DateOffset(years=cfg.fund_life_years)
            window = index.loc[start:end]
            mkt = np.log(window.iloc[-1] / window.iloc[0]) if len(window) > 1 else 0.0

            log_tvpi = (
                cfg.mu_log_tvpi
                + theta
                + vintage_effect[vintage]
                + cfg.market_beta * (mkt / cfg.fund_life_years - cfg.index_drift)
                + rng.normal(0, cfg.sd_idiosyncratic)
            )
            target = float(np.clip(np.exp(log_tvpi), 0.05, 12.0))

            dates, amounts, navs = _ta_cash_flows(commitment, target, start, cfg, rng)
            fund_id = f"{firm_id}-F{seq}"
            flows.append(
                FundCashFlows(
                    fund_id=fund_id,
                    dates=dates,
                    amounts=amounts,
                    nav=float(navs[-1]),
                    nav_date=dates[-1],
                )
            )

            # Interim TVPI at the moment the successor fund is being raised.
            k = cfg.years_between_funds * QUARTERS_PER_YEAR
            paid = -amounts[:k][amounts[:k] < 0].sum()
            interim = (amounts[:k][amounts[:k] > 0].sum() + navs[k - 1]) / paid

            records.append(
                {
                    "fund_id": fund_id,
                    "firm_id": firm_id,
                    "sequence": seq,
                    "vintage": vintage,
                    "commitment": commitment,
                    "true_skill": theta,
                    "interim_tvpi_at_next_raise": float(interim),
                }
            )

            if interim < cfg.successor_tvpi_threshold:
                break  # failed to raise a successor: firm exits the sample
            commitment *= float(np.exp(rng.normal(0.25, 0.3)))
            vintage += cfg.years_between_funds

    return SimulatedUniverse(
        funds=pd.DataFrame(records),
        cash_flows=flows,
        index=index,
        true_skill=skill,
        config=cfg,
    )
