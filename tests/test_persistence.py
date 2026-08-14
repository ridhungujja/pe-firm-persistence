"""Tests for the persistence panel and estimator.

The headline test is `test_recovers_known_beta`: in a synthetic panel built
with a specified autoregressive coefficient, the estimator has to return
that coefficient inside its own confidence interval. An estimator that
cannot do this on data it was handed cleanly will not be believable on
pension-plan data.
"""

import numpy as np
import pandas as pd
import pytest

from pefund.persistence import (
    build_panel,
    estimate,
    leave_one_out,
    quartile_transitions,
    spearman_within,
    transition_permutation_test,
    wild_cluster_bootstrap,
    winsorise,
)


def make_ar_panel(beta=0.35, n_firms=400, funds_per_firm=4, sd=0.3, seed=7):
    """Firm-sequence panel where log performance follows an AR(1) in k."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_firms):
        y = rng.normal(0, sd)
        vintage = int(rng.integers(1995, 2005))
        for k in range(1, funds_per_firm + 1):
            rows.append(
                {
                    "fund_id": f"GP{i:03d}-F{k}",
                    "firm_id": f"GP{i:03d}",
                    "sequence": k,
                    "vintage": vintage + 4 * (k - 1),
                    "commitment": 100.0,
                    "tvpi": float(np.exp(y)),
                }
            )
            y = beta * y + rng.normal(0, sd)
    df = pd.DataFrame(rows)
    funds = df.drop(columns=["tvpi"])
    metrics = df[["fund_id", "tvpi"]]
    return funds, metrics


class TestPanelConstruction:
    def test_lag_is_within_firm(self):
        funds, metrics = make_ar_panel(n_firms=3, funds_per_firm=3)
        panel = build_panel(funds, metrics)
        first_funds = panel[panel["sequence"] == 1]
        assert first_funds["y_lag"].isna().all()
        later = panel[panel["sequence"] > 1]
        assert later["y_lag"].notna().all()

    def test_missing_columns_raise(self):
        funds = pd.DataFrame({"fund_id": ["A"], "firm_id": ["G"]})
        metrics = pd.DataFrame({"fund_id": ["A"], "tvpi": [1.5]})
        with pytest.raises(ValueError, match="missing columns"):
            build_panel(funds, metrics)

    def test_dependent_variable_is_logged(self):
        funds, metrics = make_ar_panel(n_firms=5)
        panel = build_panel(funds, metrics)
        expected = np.log(panel["tvpi"].iloc[0])
        assert panel["y"].iloc[0] == pytest.approx(expected)


class TestEstimator:
    def test_recovers_known_beta(self):
        funds, metrics = make_ar_panel(beta=0.35)
        panel = build_panel(funds, metrics)
        res = estimate(panel, "AR(1), vintage FE")
        assert res.beta == pytest.approx(0.35, abs=3 * res.se)
        assert res.n_obs > 1000

    def test_zero_persistence_is_not_rejected_when_true(self):
        funds, metrics = make_ar_panel(beta=0.0, seed=11)
        panel = build_panel(funds, metrics)
        res = estimate(panel, "no persistence")
        assert abs(res.beta) < 3 * res.se

    def test_clustered_se_exceeds_naive_se(self):
        funds, metrics = make_ar_panel(beta=0.4)
        panel = build_panel(funds, metrics)
        clustered = estimate(panel, "clustered")
        naive = clustered.model.model.fit()
        assert clustered.se >= naive.bse["y_lag"] * 0.9

    def test_empty_panel_raises(self):
        funds, metrics = make_ar_panel(n_firms=2, funds_per_firm=1)
        panel = build_panel(funds, metrics)
        with pytest.raises(ValueError, match="no complete observations"):
            estimate(panel, "empty")


class TestTransitions:
    def test_rows_sum_to_one(self):
        funds, metrics = make_ar_panel(beta=0.4)
        panel = build_panel(funds, metrics)
        table = quartile_transitions(panel)
        assert np.allclose(table.sum(axis=1), 1.0)

    def test_diagonal_dominates_under_strong_persistence(self):
        funds, metrics = make_ar_panel(beta=0.8, n_firms=600)
        panel = build_panel(funds, metrics)
        table = quartile_transitions(panel)
        assert table.loc[4, 4] > table.loc[1, 4]


class TestFundNumberGaps:
    """`sequence` ranks a family's funds; `fund_number` is the fund's own number.

    They differ whenever a plan holds a subset of a series, which is the normal
    case for a single LP. These tests pin the distinction down.
    """

    @staticmethod
    def _gappy_panel(n_firms=120, seed=3):
        """Half the families hold adjacent funds, half hold a four-fund gap."""
        rng = np.random.default_rng(seed)
        rows = []
        for i in range(n_firms):
            adjacent = i % 2 == 0
            first, second = (5.0, 6.0) if adjacent else (3.0, 7.0)
            v0 = int(rng.integers(1995, 2010))
            y = rng.normal(0, 0.3)
            for number, vintage in ((first, v0), (second, v0 + (3 if adjacent else 14))):
                rows.append(
                    {
                        "fund_id": f"GP{i:03d}-F{int(number)}",
                        "firm_id": f"GP{i:03d}",
                        "sequence": 1 if number == first else 2,
                        "fund_number": number,
                        "vintage": vintage,
                        "commitment": 100.0,
                        "tvpi": float(np.exp(y)),
                    }
                )
                y = 0.35 * y + rng.normal(0, 0.3)
        df = pd.DataFrame(rows)
        return df.drop(columns=["tvpi"]), df[["fund_id", "tvpi"]]

    def test_gaps_are_computed_from_fund_numbers_not_ranks(self):
        panel = build_panel(*self._gappy_panel())
        # GP001 is a gapped family: funds III and VII, ranked 1 and 2.
        second = panel[(panel["firm_id"] == "GP001") & (panel["sequence"] == 2)].iloc[0]
        assert second["sequence"] == 2, "rank within the family is still 2"
        assert second["fund_number_gap"] == 4.0, "but III -> VII is a four-fund gap"
        assert second["vintage_gap"] == 14.0

    def test_adjacent_family_has_unit_gap(self):
        panel = build_panel(*self._gappy_panel())
        second = panel[(panel["firm_id"] == "GP000") & (panel["sequence"] == 2)].iloc[0]
        assert second["fund_number_gap"] == 1.0
        assert second["vintage_gap"] == 3.0

    def test_first_fund_has_no_gap(self):
        panel = build_panel(*self._gappy_panel())
        firsts = panel[panel["sequence"] == 1]
        assert firsts["fund_number_gap"].isna().all()

    def test_max_gap_drops_non_adjacent_pairs(self):
        panel = build_panel(*self._gappy_panel())
        unrestricted = estimate(
            panel, "all pairs", vintage_fe=False, cluster_on=("firm_id",)
        )
        adjacent = estimate(
            panel, "adjacent", vintage_fe=False, cluster_on=("firm_id",), max_gap=1
        )
        assert unrestricted.n_obs == 120, "every family contributes one pair"
        assert adjacent.n_obs == 60, "only the adjacent half survives max_gap=1"

    def test_max_gap_without_fund_numbers_raises(self):
        funds, metrics = make_ar_panel(n_firms=5)
        panel = build_panel(funds, metrics)
        with pytest.raises(ValueError, match="max_gap needs a fund_number_gap"):
            estimate(panel, "x", max_gap=1)

    def test_vintage_anomalies_can_be_dropped(self):
        funds, metrics = self._gappy_panel()
        # Flag the successor of every gapped family.
        funds["vintage_anomaly"] = (funds["fund_number"] == 7.0)
        panel = build_panel(funds, metrics)
        kept = estimate(panel, "kept", vintage_fe=False, cluster_on=("firm_id",))
        dropped = estimate(
            panel,
            "dropped",
            vintage_fe=False,
            cluster_on=("firm_id",),
            drop_vintage_anomalies=True,
        )
        assert kept.n_obs == 120
        assert dropped.n_obs == 60

    def test_dropping_anomalies_does_not_rewrite_vintages(self):
        funds, metrics = self._gappy_panel()
        funds["vintage_anomaly"] = (funds["fund_number"] == 7.0)
        before = funds["vintage"].tolist()
        build_panel(funds, metrics)
        assert funds["vintage"].tolist() == before


class TestWildClusterBootstrap:
    """Validation path: the bootstrap must have correct size under a true null.

    A p-value is only worth reporting if it rejects a true null at its nominal
    rate. These tests generate data with beta = 0 by construction and check
    that the bootstrap rejects near 5% of the time -- and that the analytic
    p-value, which is the thing being replaced, over-rejects.
    """

    def test_internal_t_matches_statsmodels(self):
        # The bootstrap computes its own clustered t from a fast identity
        # rather than statsmodels. If the two ever diverge, the bootstrap is
        # qualifying a different statistic from the one being reported.
        funds, metrics = make_ar_panel(beta=0.35, n_firms=80, funds_per_firm=3, seed=1)
        panel = build_panel(funds, metrics)
        analytic = estimate(panel, "x", vintage_fe=False, cluster_on=("firm_id",))
        boot = wild_cluster_bootstrap(panel, "x", vintage_fe=False, n_boot=99)
        assert boot.t_observed == pytest.approx(analytic.tstat, rel=1e-8)
        assert boot.beta == pytest.approx(analytic.beta, rel=1e-10)

    @staticmethod
    def _sizes(n_firms, n_samples=300, seed_block=5000):
        rejections_boot, rejections_analytic = [], []
        for s in range(n_samples):
            funds, metrics = make_ar_panel(
                beta=0.0, n_firms=n_firms, funds_per_firm=3, seed=seed_block + s
            )
            panel = build_panel(funds, metrics)
            analytic = estimate(panel, "x", vintage_fe=False, cluster_on=("firm_id",))
            boot = wild_cluster_bootstrap(
                panel, "x", vintage_fe=False, n_boot=399, seed=s
            )
            rejections_analytic.append(analytic.pvalue < 0.05)
            rejections_boot.append(boot.p_bootstrap < 0.05)
        return float(np.mean(rejections_analytic)), float(np.mean(rejections_boot))

    def test_bootstrap_size_is_near_nominal_under_a_true_null(self):
        _, size_boot = self._sizes(n_firms=20)
        # Monte Carlo error on 300 draws at p = 0.05 is about 1.3pp, so this
        # band is roughly +/- 3 standard errors of the nominal rate.
        assert 0.015 <= size_boot <= 0.09, f"bootstrap size {size_boot:.3f} off nominal"

    def test_analytic_p_over_rejects_where_the_bootstrap_does_not(self):
        # The reason for doing any of this. At 20 clusters the cluster-robust
        # asymptotic rejects a true null roughly twice as often as it should,
        # and the error is one-directional: it manufactures persistence rather
        # than hiding it. Measured across four independent seed blocks the
        # analytic rate sits at 0.09-0.13 and the bootstrap at 0.04-0.06, so
        # the ordering below is a property of the estimators, not of a seed.
        size_analytic, size_boot = self._sizes(n_firms=20)
        assert size_analytic > 0.075, (
            f"analytic size {size_analytic:.3f}: expected over-rejection at this "
            "cluster count"
        )
        assert size_boot < size_analytic

    def test_bootstrap_p_values_are_roughly_uniform_under_the_null(self):
        p_values = []
        for s in range(150):
            funds, metrics = make_ar_panel(
                beta=0.0, n_firms=40, funds_per_firm=3, seed=9000 + s
            )
            panel = build_panel(funds, metrics)
            p_values.append(
                wild_cluster_bootstrap(
                    panel, "x", vintage_fe=False, n_boot=399, seed=3 + s
                ).p_bootstrap
            )
        p_values = np.array(p_values)
        assert 0.40 <= p_values.mean() <= 0.60
        for quantile in (0.25, 0.50, 0.75):
            share = float(np.mean(p_values <= quantile))
            assert abs(share - quantile) < 0.12, (
                f"P(p <= {quantile}) = {share:.3f}, too far from uniform"
            )

    def test_bootstrap_detects_real_persistence(self):
        # Size is only half the story; the test must also have power.
        funds, metrics = make_ar_panel(beta=0.5, n_firms=80, funds_per_firm=4, seed=2)
        panel = build_panel(funds, metrics)
        boot = wild_cluster_bootstrap(panel, "x", vintage_fe=False, n_boot=999)
        assert boot.p_bootstrap < 0.05
        assert boot.beta > 0.2

    def test_bootstrap_uses_the_same_sample_as_estimate(self):
        funds, metrics = TestFundNumberGaps._gappy_panel()
        panel = build_panel(funds, metrics)
        analytic = estimate(
            panel, "adj", vintage_fe=False, cluster_on=("firm_id",), max_gap=1
        )
        boot = wild_cluster_bootstrap(
            panel, "adj", vintage_fe=False, max_gap=1, n_boot=99
        )
        assert boot.beta == pytest.approx(analytic.beta, rel=1e-10)
        assert boot.n_clusters == analytic.n_firms


class TestTransitionPermutation:
    """Validation path: the test must not see persistence in independent data.

    With four categories the diagonal of a transition matrix holds 25% of the
    mass under pure noise. The whole point of the permutation test is to say
    whether an observed diagonal is further from that than sampling error
    explains, so the two tests that matter are its behaviour under a true null
    and under perfect dependence.
    """

    @staticmethod
    def _panel(rho, n_firms=400, seed=11):
        """Pairs whose successor performance correlates rho with predecessor."""
        rng = np.random.default_rng(seed)
        lag = rng.normal(size=n_firms)
        now = rho * lag + np.sqrt(max(1 - rho**2, 0)) * rng.normal(size=n_firms)
        return pd.DataFrame(
            {
                "firm_id": [f"F{i}" for i in range(n_firms)],
                # Several vintages, each large enough to cut into quartiles.
                "vintage": rng.integers(2000, 2010, size=n_firms),
                "y": now,
                "y_lag": lag,
            }
        )

    def test_independent_data_does_not_reject(self):
        result = transition_permutation_test(self._panel(0.0), n_permutations=999)
        assert result.p_value > 0.05
        # The null diagonal must sit at chance for four quartiles.
        assert result.null_mean == pytest.approx(0.25, abs=0.03)

    def test_strong_persistence_is_detected(self):
        result = transition_permutation_test(self._panel(0.8), n_permutations=999)
        assert result.p_value < 0.01
        assert result.observed_diagonal > result.null_mean

    def test_counts_sum_to_the_pair_count(self):
        result = transition_permutation_test(self._panel(0.3), n_permutations=99)
        assert result.counts.to_numpy().sum() == result.n_pairs

    def test_counts_are_integers_not_proportions(self):
        result = transition_permutation_test(self._panel(0.3), n_permutations=99)
        assert result.counts.to_numpy().max() > 1

    def test_p_value_is_never_exactly_zero(self):
        # A finite permutation set cannot resolve p = 0, and reporting it
        # would overstate the test's resolution.
        result = transition_permutation_test(self._panel(0.95), n_permutations=99)
        assert result.p_value >= 1 / 100

    def test_too_few_pairs_returns_nan_rather_than_a_number(self):
        tiny = pd.DataFrame(
            {"firm_id": ["A", "B"], "vintage": [2000, 2000],
             "y": [1.0, 2.0], "y_lag": [1.0, 2.0]}
        )
        result = transition_permutation_test(tiny, n_permutations=99)
        assert np.isnan(result.p_value)

    def test_shuffling_happens_within_vintage(self):
        # If the shuffle crossed vintages it would also destroy the vintage
        # structure, and the null would no longer be "the predecessor carries
        # no information" but "nothing carries information".
        panel = self._panel(0.0, n_firms=300, seed=5)
        panel["y"] = panel["y"] + panel["vintage"] * 10.0   # huge vintage effects
        panel["y_lag"] = panel["y_lag"] + panel["vintage"] * 10.0
        result = transition_permutation_test(panel, n_permutations=999)
        assert result.p_value > 0.05, (
            "vintage effects alone must not register as persistence"
        )


class TestLevelsDependentVariable:
    def test_log_false_leaves_the_outcome_untransformed(self):
        funds, metrics = make_ar_panel(n_firms=20)
        metrics = metrics.rename(columns={"tvpi": "net_irr"})
        metrics["net_irr"] = metrics["net_irr"] - 1.0     # can be negative
        panel = build_panel(funds, metrics, "net_irr", log=False)
        assert panel["y"].equals(panel["net_irr"])

    def test_negative_outcomes_survive_when_not_logged(self):
        funds, metrics = make_ar_panel(n_firms=20)
        metrics = metrics.rename(columns={"tvpi": "net_irr"})
        metrics["net_irr"] = -0.2
        panel = build_panel(funds, metrics, "net_irr", log=False)
        assert (panel["y"] < 0).all(), "logging an IRR would drop every losing fund"


class TestRobustnessTools:
    def test_winsorise_uses_common_bounds_for_y_and_lag(self):
        panel = pd.DataFrame({
            "y":     [-9.0, 0.0, 0.1, 0.2, 9.0],
            "y_lag": [-9.0, 0.0, 0.1, 0.2, 9.0],
        })
        out = winsorise(panel, 0.1, 0.9)
        # Same variable at different k, so the same bounds must apply to both.
        assert out["y"].min() == out["y_lag"].min()
        assert out["y"].max() == out["y_lag"].max()

    def test_winsorise_pulls_in_the_tails(self):
        funds, metrics = make_ar_panel(n_firms=200)
        panel = build_panel(funds, metrics)
        out = winsorise(panel, 0.05, 0.95)
        assert out["y"].max() < panel["y"].max()
        assert out["y"].min() > panel["y"].min()

    def test_winsorise_preserves_row_count(self):
        funds, metrics = make_ar_panel(n_firms=50)
        panel = build_panel(funds, metrics)
        assert len(winsorise(panel, 0.01, 0.99)) == len(panel)

    def test_leave_one_out_refits_once_per_level(self):
        funds, metrics = make_ar_panel(n_firms=30, funds_per_firm=3)
        panel = build_panel(funds, metrics)
        loo = leave_one_out(panel, by="firm_id", vintage_fe=False,
                            cluster_on=("firm_id",))
        assert len(loo) == 30
        assert loo["n_obs"].max() < len(panel.dropna(subset=["y", "y_lag"]))

    def test_leave_one_out_levels_argument_restricts_refits(self):
        funds, metrics = make_ar_panel(n_firms=30, funds_per_firm=3)
        panel = build_panel(funds, metrics)
        chosen = panel["firm_id"].unique()[:5]
        loo = leave_one_out(panel, by="firm_id", levels=chosen, vintage_fe=False,
                            cluster_on=("firm_id",))
        assert len(loo) == 5
        assert set(loo["dropped"]) == set(chosen)

    def test_leave_one_out_is_stable_when_no_family_dominates(self):
        # 400 balanced families: no single one should move beta much.
        funds, metrics = make_ar_panel(beta=0.35, n_firms=400)
        panel = build_panel(funds, metrics)
        full = estimate(panel, "full", vintage_fe=False, cluster_on=("firm_id",))
        loo = leave_one_out(panel, by="firm_id", vintage_fe=False,
                            cluster_on=("firm_id",))
        assert (loo["beta"] - full.beta).abs().max() < 0.05

    def test_spearman_detects_monotone_dependence_that_is_not_linear(self):
        rng = np.random.default_rng(4)
        lag = rng.normal(size=400)
        panel = pd.DataFrame({
            "vintage": rng.integers(2000, 2008, size=400),
            "y_lag": lag,
            "y": np.exp(3 * lag),      # strongly monotone, wildly non-linear
        })
        result = spearman_within(panel, n_permutations=999)
        assert result["rho"] > 0.5
        assert result["p_value"] < 0.01

    def test_spearman_does_not_reject_under_independence(self):
        rng = np.random.default_rng(9)
        panel = pd.DataFrame({
            "vintage": rng.integers(2000, 2008, size=400),
            "y_lag": rng.normal(size=400),
            "y": rng.normal(size=400),
        })
        result = spearman_within(panel, n_permutations=999)
        assert result["p_value"] > 0.05

    def test_spearman_is_not_fooled_by_vintage_effects(self):
        rng = np.random.default_rng(2)
        vintage = rng.integers(2000, 2008, size=400)
        panel = pd.DataFrame({
            "vintage": vintage,
            "y_lag": rng.normal(size=400) + vintage * 5.0,
            "y": rng.normal(size=400) + vintage * 5.0,
        })
        result = spearman_within(panel, n_permutations=999)
        assert result["p_value"] > 0.05, (
            "ranking within vintage must remove the common vintage component"
        )

    def test_spearman_returns_nan_on_a_tiny_sample(self):
        panel = pd.DataFrame({"vintage": [2000] * 4, "y": [1, 2, 3, 4],
                              "y_lag": [1, 2, 3, 4]})
        assert np.isnan(spearman_within(panel, n_permutations=99)["rho"])
