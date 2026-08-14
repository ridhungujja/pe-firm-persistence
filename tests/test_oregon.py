"""Tests for the Oregon PERS PDF adapter.

Everything here runs against saved fixture pages, never the network, so the
suite still passes when Oregon reorganises its site. The fixtures are a real
two-page slice of the Q3 2025 report plus the extracted text of the whole
report, which is what lets the row-level edge cases be tested cheaply.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pefund.ingest.oregon import (
    DISCLAIMER,
    _money_to_float,
    parse_as_of,
    parse_lines,
    parse_pdf,
    quarter_url,
)

FIXTURES = Path(__file__).parent / "fixtures"
LINES_FIXTURE = FIXTURES / "oregon_operf_pe_2025Q3_lines.txt"
PDF_FIXTURE = FIXTURES / "oregon_operf_pe_2025Q3_pages_1_and_last.pdf"


@pytest.fixture(scope="module")
def lines():
    return LINES_FIXTURE.read_text().split("\n")


@pytest.fixture(scope="module")
def parsed(lines):
    return parse_lines(lines)


class TestMoneyParsing:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("$50.0", 50.0),
            ("$1,234.5", 1234.5),
            ("$0.0", 0.0),
            ("($3.0)", -3.0),      # accounting parentheses mean negative
            ("($0.3)", -0.3),
        ],
    )
    def test_money_tokens(self, token, expected):
        assert _money_to_float(token) == pytest.approx(expected)

    def test_parenthesised_value_is_not_read_as_positive(self):
        # The whole point: a fund with a residual liability must not become a
        # fund with a residual asset.
        assert _money_to_float("($2.6)") < 0


class TestRowParsing:
    def test_parses_the_expected_number_of_funds(self, parsed):
        assert len(parsed) == 447

    def test_as_of_date_is_read_from_the_banner(self, lines):
        assert parse_as_of(lines) == pd.Timestamp("2025-09-30")

    def test_amounts_are_converted_from_millions_to_dollars(self, parsed):
        row = parsed.set_index("fund_name").loc["A&M Capital Partners"]
        assert row["commitment"] == pytest.approx(100_000_000.0)
        assert row["contributions"] == pytest.approx(75_400_000.0)
        assert row["distributions"] == pytest.approx(135_300_000.0)
        assert row["nav"] == pytest.approx(28_100_000.0)

    def test_total_value_is_distributions_plus_nav(self, parsed):
        assert parsed["total_value"].equals(parsed["distributions"] + parsed["nav"])

    def test_fund_name_keeps_a_leading_year_that_belongs_to_it(self, parsed):
        # "2000 2000 Riverside Capital Appreciation Fund": the first number is
        # the vintage, the second is part of the partnership's name.
        row = parsed[parsed["fund_name"] == "2000 Riverside Capital Appreciation Fund"]
        assert len(row) == 1
        assert row["vintage"].iloc[0] == 2000

    def test_negative_fair_value_survives_parsing(self, parsed):
        assert (parsed["nav"] < 0).any(), "at least one fund reports a negative NAV"

    def test_secondary_sales_are_flagged(self, parsed):
        assert parsed["sold_secondary"].sum() == 94
        assert parsed.loc[
            parsed["fund_name"] == "Affinity Asia Pacific Fund III", "sold_secondary"
        ].all()

    def test_secondary_flag_does_not_leak_into_the_name(self, parsed):
        assert not parsed["fund_name"].str.startswith("*").any()

    def test_not_meaningful_rows_have_no_irr(self, parsed):
        nm = parsed[parsed["not_meaningful"]]
        assert len(nm) == 41
        assert nm["net_irr"].isna().all()

    def test_multiple_and_irr_are_read_independently(self, parsed):
        # A few rows carry a multiple but no IRR; the parser must not assume
        # the two fields always travel together.
        has_multiple_no_irr = parsed[
            parsed["reported_multiple"].notna() & parsed["net_irr"].isna()
        ]
        assert len(has_multiple_no_irr) > 0

    def test_negative_irrs_are_signed(self, parsed):
        assert (parsed["net_irr"] < 0).any()
        assert parsed["net_irr"].min() < -0.05

    def test_total_row_is_excluded(self, parsed):
        assert not parsed["fund_name"].str.lower().str.startswith("total").any()
        # The published total is $64.5bn of commitments; no single fund is.
        assert parsed["commitment"].max() < 5_000_000_000

    def test_header_rows_are_excluded(self, parsed):
        # Note the assertion is on an exact match, not a substring: real funds
        # are named "Vitruvian Investment Partnership IV".
        assert not (parsed["fund_name"].str.strip() == "Partnership").any()
        assert not parsed["fund_name"].str.contains("Vintage Year").any()
        assert not parsed["fund_name"].str.contains("Fair Market").any()

    def test_uncalled_funds_are_kept_and_flagged_not_dropped(self, parsed):
        # A fund that has not drawn capital yet is the only kind whose whole
        # cash flow history can be recovered from a snapshot archive, which is
        # what PME needs. Dropping it in the parser would be silent data loss
        # exactly where it costs the most.
        uncalled = parsed[parsed["fully_uncalled"]]
        assert len(uncalled) == 6
        assert (uncalled["contributions"] == 0).all()
        assert (uncalled["commitment"] > 0).all()
        assert uncalled["tvpi_reported"].isna().all(), (
            "no multiple is computable with zero paid-in"
        )

    def test_called_funds_are_not_flagged_uncalled(self, parsed):
        called = parsed[~parsed["fully_uncalled"]]
        assert (called["contributions"] > 0).all()


class TestAgainstPublishedTotals:
    """The report prints its own totals, which is a free correctness check."""

    def test_commitments_match_the_published_total(self, parsed):
        # Reconciles exactly only because uncalled funds are retained; they
        # carry $1,275m of commitments and no contributions.
        assert parsed["commitment"].sum() / 1e6 == pytest.approx(64_498.3, abs=1.0)

    def test_contributions_match_the_published_total(self, parsed):
        assert parsed["contributions"].sum() / 1e6 == pytest.approx(64_527.3, abs=1.0)

    def test_distributions_match_the_published_total(self, parsed):
        assert parsed["distributions"].sum() / 1e6 == pytest.approx(79_201.4, abs=1.0)

    def test_fair_value_matches_the_published_total(self, parsed):
        assert parsed["nav"].sum() / 1e6 == pytest.approx(26_226.8, abs=4.0)

    def test_computed_tvpi_matches_oregons_printed_multiple(self, parsed):
        both = parsed.dropna(subset=["reported_multiple"])
        difference = (both["tvpi_reported"] - both["reported_multiple"]).abs()
        # Oregon prints dollars to one decimal in millions, so small funds
        # carry visible rounding; anything beyond this is a parsing error.
        assert difference.mean() < 0.01
        assert difference.max() < 0.05


class TestPdfPath:
    def test_parses_a_real_pdf_end_to_end(self):
        df = parse_pdf(PDF_FIXTURE)
        assert len(df) > 50
        assert df["as_of"].iloc[0] == pd.Timestamp("2025-09-30")
        assert {"fund_id", "fund_name", "vintage", "commitment"} <= set(df.columns)

    def test_fund_ids_are_namespaced_by_plan(self):
        df = parse_pdf(PDF_FIXTURE)
        assert df["fund_id"].str.startswith("OPERF::").all()
        assert (df["source"] == "Oregon PERS OPERF").all()

    def test_layout_change_raises_rather_than_returning_nothing(self):
        with pytest.raises(ValueError, match="layout has probably changed"):
            parse_lines(["Oregon Public Employees Retirement Fund", "no rows here"])


class TestMetadata:
    def test_url_pattern(self):
        assert quarter_url(2025, 3).endswith(
            "2025/OPERF_Private_Equity_Portfolio_-_Quarter_3_2025.pdf"
        )

    def test_disclaimer_is_carried_with_the_adapter(self):
        # The plan's own statement of the measurement problem is a primary
        # source for the limitations section, so it ships with the code.
        assert "SHOULD NOT be used to assess" in DISCLAIMER
        assert "HAVE NOT been approved" in DISCLAIMER


class TestReportDiscovery:
    """Oregon has used at least five naming conventions for one report.

    A URL template finds only the quarters matching the current convention.
    These tests pin the filename parsing against every observed form, using an
    inline HTML sample so nothing here touches the network.
    """

    SAMPLE_HTML = """
    <a href="/treasury/.../2021/OPERF-Private-Equity-Portfolio-Quarter-1-2021.pdf">Q1</a>
    <a href="/treasury/.../2022/OPERF-Private-Equity-Q2-2022.pdf">Q2</a>
    <a href="/treasury/.../2023/PrivateEquity-Q3-2023.pdf">Q3</a>
    <a href="/treasury/.../2023/OPERF_Private_Equity_Portfolio_-_Quarter_4_2023.pdf">Q4</a>
    <a href="/treasury/.../2026/OPERF-Private-Equity-Portfolio-Quarter-4-2025.pdf">Q4</a>
    <a href="/treasury/.../2025/OPERF-Fixed-Income-Quarter-1-2025.pdf">not PE</a>
    <a href="/treasury/.../notes.pdf">no quarter</a>
    """

    @staticmethod
    def _discover(html):
        import pefund.ingest.oregon as oregon

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return html.encode()

        original = oregon.urllib.request.urlopen
        oregon.urllib.request.urlopen = lambda *a, **k: _Response()
        try:
            return oregon.discover_reports()
        finally:
            oregon.urllib.request.urlopen = original

    def test_all_naming_conventions_are_recognised(self):
        found = self._discover(self.SAMPLE_HTML)
        assert {(r["year"], r["quarter"]) for r in found} == {
            (2021, 1), (2022, 2), (2023, 3), (2023, 4), (2025, 4),
        }

    def test_year_comes_from_the_filename_not_the_folder(self):
        # Oregon files the Q4 2025 report under a /2026/ folder. Trusting the
        # folder would date the snapshot a year late and corrupt the ordering
        # that cash-flow differencing depends on.
        found = self._discover(self.SAMPLE_HTML)
        q4_2025 = [r for r in found if r["filename"].endswith("Quarter-4-2025.pdf")]
        assert len(q4_2025) == 1
        assert q4_2025[0]["year"] == 2025
        assert "/2026/" in q4_2025[0]["url"]

    def test_non_private_equity_reports_are_skipped(self):
        found = self._discover(self.SAMPLE_HTML)
        assert not any("Fixed-Income" in r["filename"] for r in found)

    def test_links_without_a_quarter_are_skipped(self):
        found = self._discover(self.SAMPLE_HTML)
        assert not any(r["filename"] == "notes.pdf" for r in found)

    def test_relative_links_are_absolutised(self):
        found = self._discover(self.SAMPLE_HTML)
        assert all(r["url"].startswith("https://www.oregon.gov/") for r in found)

    def test_results_are_newest_first(self):
        found = self._discover(self.SAMPLE_HTML)
        keys = [(r["year"], r["quarter"]) for r in found]
        assert keys == sorted(keys, reverse=True)

    def test_reorganised_page_yields_nothing_rather_than_bad_urls(self):
        assert self._discover("<html><body>no reports here</body></html>") == []
