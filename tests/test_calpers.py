"""Parser tests built from real rows of the CalPERS table.

The fixture below is copied verbatim from the published page, including the
repeated header row, the footnote markers on Net IRR, and a fund whose name
ends in a footnote digit. Those are the three things that break naive
parsing, so they are the three things the fixture contains.
"""

import numpy as np
import pandas as pd
import pytest

from pefund.ingest.calpers import parse

RAW = pd.DataFrame(
    [
        ["Fund", "Vintage Year", "Capital Committed", "Cash In", "Cash Out",
         "Cash Out & Remaining Value", "Net IRR", "Investment Multiple"],
        ["2024 Golden Bay, L.P.", "2025", "$100,000,000", "$24,096,354", "$0",
         "$25,746,982", "N/M  1", "N/M 1"],
        ["Advent International GPE VI-A, L.P.", "2008", "$500,000,000",
         "$502,306,204", "$1,006,375,016", "$1,045,055,779", "16.3%", "2.1x"],
        ["Advent Global Technology II Limited Partnership", "2022",
         "$150,000,000", "$102,024,862", "$0", "$138,732,537", "14.1%  1", "1.4x 1"],
        ["CalPERS Clean Energy & Technology Fund, LLC", "2007", "$465,000,000",
         "$468,423,814", "$132,249,749", "$137,914,911", "-18.5%", "0.3x"],
        ["Permira IV L.P.2", "2006", "$281,580,283", "$354,598,629",
         "$512,823,310", "$562,868,424", "8.2%", "1.6x"],
    ],
    columns=["Fund", "Vintage Year", "Capital Committed", "Cash In", "Cash Out",
             "Cash Out & Remaining Value", "Net IRR", "Investment Multiple"],
)


@pytest.fixture
def parsed():
    return parse(RAW)


def test_repeated_header_row_is_dropped(parsed):
    assert len(parsed) == 5
    assert "Fund" not in set(parsed["fund_name"])


def test_currency_strings_become_numbers(parsed):
    advent = parsed[parsed["fund_name"].str.startswith("Advent International")].iloc[0]
    assert advent["contributions"] == pytest.approx(502_306_204)
    assert advent["distributions"] == pytest.approx(1_006_375_016)
    assert advent["commitment"] == pytest.approx(500_000_000)


def test_nav_is_total_value_less_distributions(parsed):
    advent = parsed[parsed["fund_name"].str.startswith("Advent International")].iloc[0]
    assert advent["nav"] == pytest.approx(1_045_055_779 - 1_006_375_016)


def test_tvpi_matches_reported_multiple(parsed):
    advent = parsed[parsed["fund_name"].str.startswith("Advent International")].iloc[0]
    # CalPERS reports 2.1x; we recompute from the raw columns.
    assert advent["tvpi_reported"] == pytest.approx(2.1, abs=0.05)


def test_footnote_marker_does_not_corrupt_irr(parsed):
    tech = parsed[parsed["fund_name"].str.startswith("Advent Global")].iloc[0]
    assert tech["net_irr"] == pytest.approx(0.141)
    assert not tech["not_meaningful"]


def test_negative_irr_parsed(parsed):
    clean = parsed[parsed["fund_name"].str.startswith("CalPERS Clean")].iloc[0]
    assert clean["net_irr"] == pytest.approx(-0.185)
    assert clean["tvpi_reported"] < 0.4


def test_not_meaningful_flagged_not_dropped(parsed):
    bay = parsed[parsed["fund_name"].str.startswith("2024 Golden Bay")].iloc[0]
    assert bay["not_meaningful"]
    assert np.isnan(bay["net_irr"])
    assert bay["tvpi_reported"] > 0  # still has a computable multiple


def test_unexpected_layout_raises():
    with pytest.raises(ValueError, match="unexpected table layout"):
        parse(pd.DataFrame({"Something": ["else"]}))
