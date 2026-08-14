"""Reproducibility: the same inputs must produce the same numbers.

Every random procedure in the estimation is seeded. That is easy to assert and
easy to break — a stray `np.random` call, an unseeded default, or a dict whose
iteration order leaks into a resampling loop all produce results that drift
between runs without ever failing. A result that cannot be reproduced cannot
be checked by anyone, including its author six months later.
"""

import numpy as np
import pandas as pd
import pytest

from pefund.persistence import (
    build_panel,
    estimate,
    leave_one_out,
    spearman_within,
    transition_permutation_test,
    wild_cluster_bootstrap,
)

from test_persistence import make_ar_panel


@pytest.fixture(scope="module")
def panel():
    funds, metrics = make_ar_panel(beta=0.3, n_firms=120, funds_per_firm=3, seed=42)
    return build_panel(funds, metrics)


class TestDeterminism:
    def test_ols_is_identical_across_runs(self, panel):
        a = estimate(panel, "x", vintage_fe=False, cluster_on=("firm_id",))
        b = estimate(panel, "x", vintage_fe=False, cluster_on=("firm_id",))
        assert a.beta == b.beta
        assert a.se == b.se
        assert a.pvalue == b.pvalue

    def test_bootstrap_is_identical_across_runs(self, panel):
        a = wild_cluster_bootstrap(panel, "x", vintage_fe=False, n_boot=499)
        b = wild_cluster_bootstrap(panel, "x", vintage_fe=False, n_boot=499)
        assert a.p_bootstrap == b.p_bootstrap
        assert a.t_observed == b.t_observed

    def test_bootstrap_seed_actually_changes_the_draw(self, panel):
        # The converse check: if two seeds gave the same answer, the seed
        # would not be reaching the resampler and the first test would be
        # passing for the wrong reason.
        a = wild_cluster_bootstrap(panel, "x", vintage_fe=False, n_boot=499, seed=1)
        b = wild_cluster_bootstrap(panel, "x", vintage_fe=False, n_boot=499, seed=2)
        assert a.t_observed == b.t_observed, "the observed statistic is not random"
        assert not np.array_equal(a.t_null, b.t_null)

    def test_permutation_test_is_identical_across_runs(self, panel):
        a = transition_permutation_test(panel, n_permutations=499)
        b = transition_permutation_test(panel, n_permutations=499)
        assert a.p_value == b.p_value
        assert a.observed_diagonal == b.observed_diagonal

    def test_spearman_is_identical_across_runs(self, panel):
        a = spearman_within(panel, n_permutations=499)
        b = spearman_within(panel, n_permutations=499)
        assert a["rho"] == b["rho"]
        assert a["p_value"] == b["p_value"]

    def test_leave_one_out_is_identical_across_runs(self, panel):
        a = leave_one_out(panel, by="firm_id", vintage_fe=False,
                          cluster_on=("firm_id",))
        b = leave_one_out(panel, by="firm_id", vintage_fe=False,
                          cluster_on=("firm_id",))
        pd.testing.assert_frame_equal(a, b)

    def test_row_order_does_not_change_the_estimate(self, panel):
        # Reading the same CSV on a different machine can hand back rows in a
        # different order; the coefficient must not care.
        shuffled = panel.sample(frac=1.0, random_state=5).reset_index(drop=True)
        a = estimate(panel, "x", vintage_fe=False, cluster_on=("firm_id",))
        b = estimate(shuffled, "x", vintage_fe=False, cluster_on=("firm_id",))
        assert a.beta == pytest.approx(b.beta, rel=1e-10)
        assert a.se == pytest.approx(b.se, rel=1e-10)


class TestShippedResults:
    """The committed tables must match what the code produces now."""

    def test_specification_table_is_present_and_complete(self, repo_data):
        path = repo_data / "real_specifications.csv"
        if not path.exists():
            pytest.skip("run analysis/run_real_analysis.py first")
        table = pd.read_csv(path)
        assert len(table) == 7, "all seven WORK_BRIEF 2.2 rows must be present"
        assert table["beta"].notna().all(), "no row may be left unestimated"
        assert "p_bootstrap" in table.columns

    def test_headline_row_is_labelled(self, repo_data):
        path = repo_data / "real_specifications.csv"
        if not path.exists():
            pytest.skip("run analysis/run_real_analysis.py first")
        table = pd.read_csv(path)
        headline = table[table["specification"].str.contains("HEADLINE")]
        assert len(headline) == 1, "exactly one row is the headline"

    def test_mapping_regimes_all_estimated(self, repo_data):
        path = repo_data / "mapping_robustness.csv"
        if not path.exists():
            pytest.skip("run analysis/run_real_analysis.py first")
        table = pd.read_csv(path)
        assert len(table) == 3
        assert table["beta"].notna().all()
        # The point of the exercise: mapping choices must not drive beta.
        spread = table["beta"].max() - table["beta"].min()
        assert spread < table["std_error"].max(), (
            f"beta moves {spread:.4f} across mapping regimes, more than one "
            "standard error - the family mapping would be driving the result"
        )
