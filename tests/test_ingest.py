"""Tests for the ingestion layer's schema guarantees."""

import numpy as np
import pandas as pd
import pytest

from pefund.ingest.base import (
    add_sequence_numbers,
    apply_firm_overrides,
    assign_sponsor_ids,
    cash_flows_from_long,
    derive_sponsor_ids,
    deduplicate_share_classes,
    flag_vintage_anomalies,
    load_firm_overrides,
    load_sponsor_overrides,
    normalise_firm_ids,
    parse_fund_number,
    reconstruct_flows_from_snapshots,
    validate_snapshot,
)


def test_firm_ids_collapse_fund_numbers():
    funds = pd.DataFrame(
        {"fund_name": ["Acme Capital Partners VII, L.P.", "Acme Capital Partners VI"]}
    )
    ids = normalise_firm_ids(funds)
    assert ids.nunique() == 1


def _overrides(rows):
    cols = ["firm_id_raw", "firm_id_canonical", "decision", "confidence", "reason"]
    return pd.DataFrame(rows, columns=cols)


def test_overrides_merge_a_series_split_by_a_share_class():
    # "(A)" after the fund number blocks the numeral strip, so every vintage
    # lands on its own stem and the firm looks like three first-time funds.
    funds = pd.DataFrame(
        {
            "fund_name": [
                "Acme Capital Partners VII (A) L.P.",
                "Acme Capital Partners VIII (A) L.P.",
                "Acme Capital Partners IX, L.P.",
            ]
        }
    )
    raw = normalise_firm_ids(funds)
    assert raw.nunique() == 3

    overrides = _overrides(
        [
            ("ACME CAPITAL PARTNERS VII (A)", "ACME CAPITAL PARTNERS", "merge", "high", ""),
            ("ACME CAPITAL PARTNERS VIII (A)", "ACME CAPITAL PARTNERS", "merge", "high", ""),
        ]
    )
    assert apply_firm_overrides(raw, overrides).nunique() == 1


def test_keep_separate_rows_do_not_merge():
    raw = pd.Series(["ACME PARTNERS", "ACME PARTNERS GROWTH"])
    overrides = _overrides(
        [("ACME PARTNERS GROWTH", "ACME PARTNERS GROWTH", "keep_separate", "high", "")]
    )
    assert list(apply_firm_overrides(raw, overrides)) == list(raw)


def test_no_overrides_leaves_ids_untouched():
    raw = pd.Series(["ACME PARTNERS", "BETA FUND"])
    assert list(apply_firm_overrides(raw, _overrides([]))) == list(raw)


def test_chained_merges_are_rejected(tmp_path):
    # A -> B and B -> C would make the result depend on row order.
    path = tmp_path / "o.csv"
    path.write_text(
        "firm_id_raw,firm_id_canonical,decision,confidence,reason\n"
        "A,B,merge,high,\n"
        "B,C,merge,high,\n"
    )
    with pytest.raises(ValueError, match="chains merges"):
        load_firm_overrides(path)


def test_duplicate_stem_is_rejected(tmp_path):
    path = tmp_path / "o.csv"
    path.write_text(
        "firm_id_raw,firm_id_canonical,decision,confidence,reason\n"
        "A,B,merge,high,\n"
        "A,C,merge,high,\n"
    )
    with pytest.raises(ValueError, match="maps the same stem twice"):
        load_firm_overrides(path)


def test_shipped_overrides_are_well_formed_and_merge_only_real_stems():
    overrides = load_firm_overrides()
    assert not overrides.empty, "data/firm_overrides.csv should ship with the repo"

    # Every merge target must be a family the mapping actually produces, and no
    # target may also be a source (already checked in the loader).
    merges = overrides[overrides["decision"] == "merge"]
    assert not merges.empty
    assert (merges["firm_id_raw"] != merges["firm_id_canonical"]).all()

    keeps = overrides[overrides["decision"] == "keep_separate"]
    assert (keeps["firm_id_raw"] == keeps["firm_id_canonical"]).all(), (
        "keep_separate rows must be no-ops"
    )


def test_sequence_numbers_run_within_firm():
    funds = pd.DataFrame(
        {
            "firm_id": ["A", "A", "B"],
            "vintage": [2004, 2000, 2001],
            "commitment": [100.0, 50.0, 75.0],
        }
    )
    out = add_sequence_numbers(funds)
    a = out[out["firm_id"] == "A"].sort_values("vintage")
    assert list(a["sequence"]) == [1, 2]
    assert out[out["firm_id"] == "B"]["sequence"].iloc[0] == 1


def test_parallel_vintages_are_flagged():
    funds = pd.DataFrame(
        {"firm_id": ["A", "A"], "vintage": [2005, 2005], "commitment": [10.0, 20.0]}
    )
    assert add_sequence_numbers(funds)["parallel_vintage"].all()


def test_validate_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing columns"):
        validate_snapshot(pd.DataFrame({"fund_id": ["A"]}))


def test_reconstruction_differences_cumulative_totals():
    panel = pd.DataFrame(
        {
            "fund_id": ["A", "A", "A"],
            "as_of": pd.to_datetime(["2020-03-31", "2020-06-30", "2020-09-30"]),
            "contributions": [50.0, 80.0, 80.0],
            "distributions": [0.0, 10.0, 45.0],
        }
    )
    flows = reconstruct_flows_from_snapshots(panel)
    assert flows["amount"].iloc[0] == pytest.approx(-50.0)
    assert flows["amount"].iloc[1] == pytest.approx(-20.0)  # -30 call + 10 dist
    assert flows["amount"].iloc[2] == pytest.approx(35.0)


def test_cash_flow_assembly_attaches_nav():
    flows = pd.DataFrame(
        {
            "fund_id": ["A", "A"],
            "date": pd.to_datetime(["2015-01-01", "2018-01-01"]),
            "amount": [-100.0, 60.0],
        }
    )
    snaps = pd.DataFrame(
        {"fund_id": ["A"], "nav": [80.0], "as_of": [pd.Timestamp("2020-12-31")]}
    )
    built = cash_flows_from_long(flows, snaps)
    assert len(built) == 1
    assert built[0].nav == 80.0
    assert built[0].contributions == 100.0


# --------------------------------------------------------------- fund numbers


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Blackstone Capital Partners V L.P.", 5),
        ("Apollo Investment Fund VIII, L.P.", 8),
        ("Triton Fund 6 SCSp", 6),                      # arabic
        ("Hg Genesis 10 A L.P.", 10),                   # arabic + share class
        ("Advent International GPE VII-C, L.P.", 7),    # hyphenated class
        ("CVC Capital Partners IX (A) L.P.", 9),        # parenthetical class
        ("TA XIV-A, L.P.", 14),
        ("Welsh, Carson, Anderson & Stowe XI, L.P.", 11),
        ("Mayfield XVII, a Delaware Limited Partnership", 17),
        ("Permira VI L.P. 1", 6),                       # feeder tag after LP
        ("Genstar XI Opportunities Fund I, L.P.", 11),  # generation, not sleeve
        ("57 Stars Global Opportunities Fund 2 (CalPERS), LLC", 2),
    ],
)
def test_fund_numbers_parse(name, expected):
    assert parse_fund_number(pd.Series([name]))[0] == expected


@pytest.mark.parametrize(
    "name",
    [
        "KKR Asian Fund L.P.",          # unnumbered first fund
        "The Rise Fund (A), L.P.",
        "KKR 2006 Fund L.P.",           # year, not a fund number
        "Bain Capital Venture Fund 2022, L.P.",
        "2024 Golden Bay, L.P.",        # leading number is the firm's name
    ],
)
def test_unnumbered_or_year_named_funds_are_nan(name):
    assert np.isnan(parse_fund_number(pd.Series([name]))[0])


def test_lp_suffix_is_not_read_as_roman_fifty():
    # "L.P." tokenises to L + P and L is roman 50; the entity stripper must
    # remove it before the numeral scan or every fund becomes number 50.
    assert np.isnan(parse_fund_number(pd.Series(["Acme Fund L.P."]))[0])


# ------------------------------------------------------- share-class dedup


def _classes(**over):
    base = {
        "fund_id": ["a", "b", "c"],
        "fund_name": ["Euro III 'C'", "Euro III 'D'", "Euro IV"],
        "firm_id": ["EURO", "EURO", "EURO"],
        "fund_number": [3.0, 3.0, 4.0],
        "vintage": [2015, 2005, 2008],
        "commitment": [100.0, 50.0, 70.0],
        "contributions": [80.0, 40.0, 60.0],
        "distributions": [90.0, 30.0, 20.0],
        "nav": [10.0, 20.0, 50.0],
        "total_value": [100.0, 50.0, 70.0],
        "net_irr": [0.042, 0.024, 0.11],
    }
    base.update(over)
    return pd.DataFrame(base)


def test_share_classes_collapse_with_summed_cash_and_earliest_vintage():
    out, report = deduplicate_share_classes(_classes())

    assert len(out) == 2, "two classes of fund III must become one row"
    fund3 = out[out["fund_number"] == 3.0].iloc[0]
    assert fund3["commitment"] == 150.0
    assert fund3["contributions"] == 120.0
    assert fund3["distributions"] == 120.0
    assert fund3["nav"] == 30.0
    assert fund3["total_value"] == 150.0          # distributions + nav
    assert fund3["vintage"] == 2005, "earliest vintage wins over the 2015 stamp"
    assert fund3["n_share_classes"] == 2
    assert len(report) == 1


def test_single_class_fund_passes_through_untouched():
    out, _ = deduplicate_share_classes(_classes())
    fund4 = out[out["fund_number"] == 4.0].iloc[0]
    assert fund4["commitment"] == 70.0
    assert fund4["vintage"] == 2008
    assert fund4["n_share_classes"] == 1
    assert fund4["net_irr"] == 0.11, "an uncollapsed row keeps its reported IRR"


def test_net_irr_is_nan_on_collapsed_rows_only():
    out, _ = deduplicate_share_classes(_classes())
    assert np.isnan(out.set_index("fund_number").loc[3.0, "net_irr"])
    assert not np.isnan(out.set_index("fund_number").loc[4.0, "net_irr"])


def test_unnumbered_rows_are_never_collapsed_together():
    # Two different unnumbered vehicles in one family must stay separate;
    # NaN is "unknown", not a key they have in common.
    funds = _classes(
        fund_id=["a", "b", "c"],
        fund_name=["Euro CF", "Euro Growth", "Euro IV"],
        fund_number=[np.nan, np.nan, 4.0],
    )
    out, report = deduplicate_share_classes(funds)
    assert len(out) == 3
    assert report.empty


# ------------------------------------------------------- vintage anomalies


def test_vintage_order_contradiction_is_flagged():
    funds = pd.DataFrame(
        {
            "fund_id": ["a", "b"],
            "fund_name": ["Acme III", "Acme IV"],
            "firm_id": ["ACME", "ACME"],
            "fund_number": [3.0, 4.0],
            "vintage": [2015, 2008],   # fund IV predates fund III
        }
    )
    out, report = flag_vintage_anomalies(funds)
    assert out["vintage_anomaly"].all()
    assert len(report) == 2
    assert "contradicts" in report["vintage_anomaly_reason"].iloc[0]


def test_vintage_off_family_trend_is_flagged():
    # Ordering is preserved, so only the trend check can catch this one.
    funds = pd.DataFrame(
        {
            "fund_id": list("abcd"),
            "fund_name": ["Acme I", "Acme II", "Acme III", "Acme IV"],
            "firm_id": ["ACME"] * 4,
            "fund_number": [1.0, 2.0, 3.0, 4.0],
            "vintage": [2000, 2003, 2006, 2020],
        }
    )
    out, report = flag_vintage_anomalies(funds)
    assert out["vintage_anomaly"].any()
    assert not report.empty


def test_clean_family_is_not_flagged():
    funds = pd.DataFrame(
        {
            "fund_id": list("abcd"),
            "fund_name": ["Acme I", "Acme II", "Acme III", "Acme IV"],
            "firm_id": ["ACME"] * 4,
            "fund_number": [1.0, 2.0, 3.0, 4.0],
            "vintage": [2000, 2003, 2006, 2009],
        }
    )
    out, report = flag_vintage_anomalies(funds)
    assert not out["vintage_anomaly"].any()
    assert report.empty


def test_anomalous_vintages_are_flagged_not_corrected():
    funds = pd.DataFrame(
        {
            "fund_id": ["a", "b"],
            "fund_name": ["Acme III", "Acme IV"],
            "firm_id": ["ACME", "ACME"],
            "fund_number": [3.0, 4.0],
            "vintage": [2015, 2008],
        }
    )
    out, _ = flag_vintage_anomalies(funds)
    assert list(out["vintage"]) == [2015, 2008], "vintages must not be rewritten"


# --------------------------------------------------------------- sponsors


class TestSponsorMapping:
    """Sponsor sits above family. Two families under one firm share an
    investment committee, so their residuals are correlated and they must not
    be counted as independent clusters."""

    def test_leading_token_is_the_sponsor(self):
        families = pd.Series([
            "SILVER LAKE PARTNERS", "SILVER LAKE TECHNOLOGY INVESTORS",
            "CARLYLE EUROPE PARTNERS", "CARLYLE PARTNERS",
        ])
        assert list(derive_sponsor_ids(families)) == [
            "SILVER", "SILVER", "CARLYLE", "CARLYLE"
        ]

    def test_leading_article_is_stripped(self):
        # "The Rise Fund" and "The Veritas Capital Fund" would otherwise both
        # become sponsor "THE".
        out = derive_sponsor_ids(pd.Series(["THE RISE FUND", "THE VERITAS CAPITAL FUND"]))
        assert list(out) == ["RISE", "VERITAS"]

    def test_single_token_family_is_its_own_sponsor(self):
        assert derive_sponsor_ids(pd.Series(["PERMIRA"]))[0] == "PERMIRA"

    def test_overrides_separate_two_firms_sharing_a_first_word(self):
        families = pd.Series([
            "GENERAL ATLANTIC MANAGED ACCOUNT", "GENERAL CATALYST HEALTH ASSURANCE"
        ])
        assert derive_sponsor_ids(families).nunique() == 1, "the rule pools them"
        overrides = pd.DataFrame(
            [("GENERAL ATLANTIC MANAGED ACCOUNT", "GENERAL ATLANTIC", "high", ""),
             ("GENERAL CATALYST HEALTH ASSURANCE", "GENERAL CATALYST", "high", "")],
            columns=["firm_id", "sponsor_id", "confidence", "reason"],
        )
        assert assign_sponsor_ids(families, overrides).nunique() == 2

    def test_families_without_an_override_keep_the_derived_sponsor(self):
        families = pd.Series(["PERMIRA", "PERMIRA GROWTH OPPORTUNITIES"])
        overrides = pd.DataFrame(
            [("SOMETHING ELSE", "OTHER", "high", "")],
            columns=["firm_id", "sponsor_id", "confidence", "reason"],
        )
        assert list(assign_sponsor_ids(families, overrides)) == ["PERMIRA", "PERMIRA"]

    def test_duplicate_family_row_is_rejected(self, tmp_path):
        path = tmp_path / "s.csv"
        path.write_text(
            "firm_id,sponsor_id,confidence,reason\nA,X,high,\nA,Y,high,\n"
        )
        with pytest.raises(ValueError, match="maps the same family twice"):
            load_sponsor_overrides(path)

    def test_shipped_sponsor_overrides_are_well_formed(self):
        overrides = load_sponsor_overrides()
        assert not overrides.empty
        assert (overrides["sponsor_id"] != "").all()
        assert (overrides["reason"] != "").all(), "every hand mapping states why"
        assert set(overrides["confidence"]) <= {"high", "medium", "low"}

    def test_sponsor_count_never_exceeds_family_count(self):
        families = pd.Series([
            "SILVER LAKE PARTNERS", "SILVER LAKE TECHNOLOGY INVESTORS", "PERMIRA"
        ])
        sponsors = assign_sponsor_ids(families, pd.DataFrame(
            columns=["firm_id", "sponsor_id", "confidence", "reason"]))
        assert sponsors.nunique() <= families.nunique()
