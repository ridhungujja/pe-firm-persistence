"""Tests for the French factor loader and the PME eligibility rule.

Both exist to stop a specific silent failure. The factor parser must not
compound through French's -99.99 missing codes, and the eligibility rule must
refuse to compute PME for funds whose early cash flows predate the archive.
Neither error raises on its own; both produce plausible numbers.
"""

import numpy as np
import pandas as pd
import pytest

from pefund.ingest.base import funds_observed_from_inception
from pefund.ingest.french import (
    build_index,
    market_total_return,
    parse_factors,
)

HEADER = (
    "This file was created by CMPT_ME_BEME_RETS using the 202506 CRSP database.\n"
    "\n"
    ",Mkt-RF,SMB,HML,RF\n"
)


def _csv(rows: str) -> bytes:
    return (HEADER + rows).encode("latin-1")


class TestFactorParsing:
    def test_monthly_rows_are_read_and_scaled_to_decimals(self):
        factors = parse_factors(_csv("192607,2.96,-2.30,-2.87,0.22\n"))
        assert len(factors) == 1
        row = factors.iloc[0]
        assert row["mkt_rf"] == pytest.approx(0.0296)
        assert row["rf"] == pytest.approx(0.0022)

    def test_dates_land_on_month_end(self):
        factors = parse_factors(_csv("202502,1.00,0.10,0.20,0.30\n"))
        assert factors.index[0] == pd.Timestamp("2025-02-28")

    def test_annual_block_is_ignored(self):
        # The annual table follows the monthly one and is keyed YYYY, not
        # YYYYMM. Reading it would append 4-digit "months" to the series.
        raw = _csv("202501,1.0,0.1,0.2,0.3\n202502,1.0,0.1,0.2,0.3\n\n1927,10.0,1.0,2.0,3.0\n")
        factors = parse_factors(raw)
        assert len(factors) == 2
        assert factors.index.max().year == 2025

    @pytest.mark.parametrize("code", ["-99", "-99.99", "-999"])
    def test_missing_codes_become_nan(self, code):
        factors = parse_factors(_csv(f"202501,{code},0.1,0.2,0.3\n"))
        assert np.isnan(factors["mkt_rf"].iloc[0])

    def test_empty_file_raises(self):
        with pytest.raises(ValueError, match="no monthly rows"):
            parse_factors(_csv(""))


class TestIndexConstruction:
    def test_compounding_has_the_analytic_answer(self):
        # Two months of exactly 10% total return: 100 -> 110 -> 121.
        raw = _csv("202501,9.0,0,0,1.0\n202502,9.0,0,0,1.0\n")
        level = build_index(parse_factors(raw), base=100.0)
        assert level.iloc[0] == pytest.approx(110.0)
        assert level.iloc[1] == pytest.approx(121.0)

    def test_market_return_is_excess_plus_riskfree(self):
        factors = parse_factors(_csv("202501,4.0,0,0,1.0\n"))
        assert market_total_return(factors).iloc[0] == pytest.approx(0.05)

    def test_missing_month_refuses_to_compound(self):
        # Compounding through a NaN truncates the level series from that point
        # on and every PME after it is silently wrong, so this must raise.
        raw = _csv("202501,1.0,0,0,0.3\n202502,-99.99,0,0,0.3\n")
        with pytest.raises(ValueError, match="cannot compound"):
            build_index(parse_factors(raw))

    def test_index_is_strictly_positive(self):
        raw = _csv("202501,-20.0,0,0,0.3\n202502,5.0,0,0,0.3\n")
        assert (build_index(parse_factors(raw)) > 0).all()


class TestPmeEligibility:
    @staticmethod
    def _archive():
        return pd.DataFrame(
            {
                "fund_id": ["new", "new", "old", "old", "once"],
                "as_of": pd.to_datetime(
                    ["2024-03-31", "2024-06-30", "2024-03-31", "2024-06-30",
                     "2024-03-31"]
                ),
                # "new" is uncalled at first sight; "old" was already drawn.
                "contributions": [0.0, 40.0, 500.0, 560.0, 0.0],
                "distributions": [0.0, 5.0, 200.0, 240.0, 0.0],
            }
        )

    def test_fund_uncalled_at_first_sight_is_eligible(self):
        assert "new" in funds_observed_from_inception(self._archive())

    def test_fund_already_drawn_before_the_archive_is_excluded(self):
        # Its early calls are unrecoverable, and PME would date them all at the
        # first snapshot without complaining.
        assert "old" not in funds_observed_from_inception(self._archive())

    def test_single_observation_is_excluded(self):
        assert "once" not in funds_observed_from_inception(self._archive())

    def test_missing_columns_raise(self):
        with pytest.raises(ValueError, match="need columns"):
            funds_observed_from_inception(pd.DataFrame({"fund_id": ["a"]}))
