"""Tests for the metric layer.

Each case is one where the correct answer is known analytically, so a
regression in the code shows up as a failed assertion rather than a
plausible-looking number.
"""

import numpy as np
import pandas as pd
import pytest

from pefund.metrics import (
    FundCashFlows,
    direct_alpha,
    dpi,
    fund_irr,
    ks_pme,
    ln_pme,
    rvpi,
    tvpi,
    xirr,
)

DATES = pd.DatetimeIndex(["2010-01-01", "2012-01-01"])


def make_fund(amounts, nav=0.0, dates=DATES, fund_id="TEST"):
    return FundCashFlows(
        fund_id=fund_id,
        dates=dates,
        amounts=np.array(amounts, dtype=float),
        nav=nav,
        nav_date=dates[-1],
    )


def flat_index(level_start=100.0, level_end=100.0, dates=DATES):
    return pd.Series([level_start, level_end], index=dates)


class TestIRR:
    def test_two_year_doubling_is_about_41_percent(self):
        # 100 -> 200 over the exact act/365.25 year fraction between the dates.
        years = (DATES[-1] - DATES[0]).days / 365.25
        r = xirr(DATES, np.array([-100.0, 200.0]))
        assert r == pytest.approx(2 ** (1 / years) - 1, rel=1e-6)

    def test_known_ten_percent(self):
        r = xirr(DATES, np.array([-100.0, 121.0]))
        assert r == pytest.approx(0.10, abs=2e-4)

    def test_no_sign_change_returns_nan(self):
        assert np.isnan(xirr(DATES, np.array([-100.0, -50.0])))

    def test_nav_counts_as_terminal_distribution(self):
        fund = make_fund([-100.0, 0.0], nav=121.0)
        assert fund_irr(fund) == pytest.approx(0.10, abs=2e-4)


class TestMultiples:
    def test_dpi_rvpi_tvpi_decomposition(self):
        fund = make_fund([-100.0, 60.0], nav=90.0)
        assert dpi(fund) == pytest.approx(0.60)
        assert rvpi(fund) == pytest.approx(0.90)
        assert tvpi(fund) == pytest.approx(1.50)

    def test_paid_in_ignores_distributions(self):
        dates = pd.DatetimeIndex(["2010-01-01", "2011-01-01", "2012-01-01"])
        fund = make_fund([-60.0, 30.0, -40.0], nav=0.0, dates=dates)
        assert fund.contributions == pytest.approx(100.0)
        assert fund.distributions == pytest.approx(30.0)


class TestPME:
    def test_pme_is_one_when_fund_tracks_index(self):
        # Index doubles; fund's single investment also doubles.
        index = flat_index(100.0, 200.0)
        fund = make_fund([-100.0, 0.0], nav=200.0)
        assert ks_pme(fund, index) == pytest.approx(1.0, rel=1e-9)

    def test_pme_above_one_when_fund_beats_index(self):
        index = flat_index(100.0, 150.0)
        fund = make_fund([-100.0, 0.0], nav=200.0)
        assert ks_pme(fund, index) == pytest.approx(200 / 150, rel=1e-9)

    def test_pme_below_one_when_fund_lags(self):
        index = flat_index(100.0, 200.0)
        fund = make_fund([-100.0, 0.0], nav=150.0)
        assert ks_pme(fund, index) < 1.0

    def test_direct_alpha_zero_when_tracking_index(self):
        index = flat_index(100.0, 200.0)
        fund = make_fund([-100.0, 0.0], nav=200.0)
        assert direct_alpha(fund, index) == pytest.approx(0.0, abs=1e-6)

    def test_direct_alpha_positive_when_outperforming(self):
        index = flat_index(100.0, 150.0)
        fund = make_fund([-100.0, 0.0], nav=200.0)
        assert direct_alpha(fund, index) > 0

    def test_price_index_carried_forward_between_flow_dates(self):
        # Benchmark observed monthly, cash flows land mid-month.
        idx = pd.Series(
            [100.0, 110.0, 121.0],
            index=pd.DatetimeIndex(["2010-01-01", "2011-01-01", "2012-01-01"]),
        )
        dates = pd.DatetimeIndex(["2010-06-15", "2012-01-01"])
        fund = make_fund([-100.0, 0.0], nav=121.0, dates=dates)
        # Flow discounted at the January level of 100, terminal at 121.
        assert ks_pme(fund, idx) == pytest.approx(1.0, rel=1e-9)

    def test_benchmark_starting_after_first_flow_raises(self):
        idx = pd.Series([100.0], index=pd.DatetimeIndex(["2011-01-01"]))
        fund = make_fund([-100.0, 0.0], nav=121.0)
        with pytest.raises(ValueError, match="no value on or before"):
            ks_pme(fund, idx)


class TestLongNickels:
    def test_matches_index_return_when_fund_tracks_index(self):
        index = flat_index(100.0, 200.0)
        fund = make_fund([-100.0, 0.0], nav=200.0)
        years = (DATES[-1] - DATES[0]).days / 365.25
        assert ln_pme(fund, index) == pytest.approx(2 ** (1 / years) - 1, rel=1e-6)


class TestValidation:
    def test_unsorted_dates_rejected(self):
        dates = pd.DatetimeIndex(["2012-01-01", "2010-01-01"])
        with pytest.raises(ValueError, match="sorted"):
            make_fund([-100.0, 200.0], dates=dates)

    def test_length_mismatch_rejected(self):
        with pytest.raises(ValueError, match="length mismatch"):
            FundCashFlows("X", DATES, np.array([-100.0]), 0.0, DATES[-1])
