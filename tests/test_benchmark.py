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


class TestAttenuation:
    """Validation path: recover a known reliability ratio.

    The attenuation factor is only worth reporting if it returns the right
    answer when the error variance is known by construction, so these tests
    build two noisy reports of a known truth and check lambda comes back.
    """

    @staticmethod
    def _reports(sd_true, sd_error, n=4000, seed=3):
        rng = np.random.default_rng(seed)
        truth = rng.normal(0, sd_true, n)
        return (
            truth + rng.normal(0, sd_error, n),
            truth + rng.normal(0, sd_error, n),
        )

    def test_recovers_a_known_lambda(self):
        from run_overlap import attenuation

        sd_true, sd_error = 0.30, 0.10
        expected = sd_true**2 / (sd_true**2 + sd_error**2)
        result = attenuation(*self._reports(sd_true, sd_error))
        assert result["lambda"] == pytest.approx(expected, abs=0.03)

    def test_error_variance_is_half_the_difference_variance(self):
        from run_overlap import attenuation

        sd_error = 0.20
        result = attenuation(*self._reports(0.4, sd_error))
        assert result["var_error"] == pytest.approx(sd_error**2, rel=0.15)

    def test_noiseless_reports_give_lambda_one(self):
        from run_overlap import attenuation

        rng = np.random.default_rng(1)
        truth = rng.normal(0, 0.3, 500)
        result = attenuation(truth, truth)
        assert result["lambda"] == pytest.approx(1.0, abs=1e-9)
        assert result["var_error"] == pytest.approx(0.0, abs=1e-12)

    def test_more_noise_lowers_lambda(self):
        from run_overlap import attenuation

        quiet = attenuation(*self._reports(0.3, 0.05))
        loud = attenuation(*self._reports(0.3, 0.30))
        assert quiet["lambda"] > loud["lambda"]

    def test_lambda_never_exceeds_one(self):
        from run_overlap import attenuation

        for sd_error in (0.01, 0.1, 0.5, 1.0):
            result = attenuation(*self._reports(0.3, sd_error))
            assert 0.0 <= result["lambda"] <= 1.0

    def test_correction_inflates_beta(self):
        from run_overlap import attenuation

        result = attenuation(*self._reports(0.3, 0.15))
        beta_raw = 0.2
        assert beta_raw / result["lambda"] > beta_raw


class TestVintageErrorSimulation:
    """The vintage-label error must have a validated direction, not an argued one.

    The intuitive story is that unabsorbed vintage shocks correlate across a
    family's funds and inflate apparent persistence. These tests pin down that
    the opposite happens, so the write-up cannot drift back to the intuition.
    """

    def test_displacement_matches_the_observed_pattern(self):
        from simulate_vintage_error import OBSERVED_SHIFTS, OBSERVED_WEIGHTS, displace

        assert OBSERVED_SHIFTS == (0, 1, 2), "CalPERS is never earlier than Oregon"
        assert sum(OBSERVED_WEIGHTS) == pytest.approx(1.0)
        rng = np.random.default_rng(0)
        original = pd.Series([2000] * 4000)
        shifted = displace(original, rng)
        # Never earlier, at most two years later.
        assert (shifted >= original).all()
        assert (shifted - original).max() <= 2
        assert (shifted - original).mean() == pytest.approx(
            sum(s * w for s, w in zip(OBSERVED_SHIFTS, OBSERVED_WEIGHTS)), abs=0.05
        )

    def test_mislabelling_attenuates_rather_than_inflates(self):
        from simulate_vintage_error import run

        result = run(n_reps=120, beta=0.35, seed=5)
        bias = (result["beta_mislabelled"] - result["beta_true_labels"]).mean()
        assert bias < 0, (
            f"displaced vintage labels attenuate beta; got bias {bias:+.4f}. "
            "If this ever turns positive the write-up's direction is wrong."
        )

    def test_no_bias_when_there_is_no_persistence_to_attenuate(self):
        from simulate_vintage_error import run

        result = run(n_reps=120, beta=0.0, seed=6)
        bias = (result["beta_mislabelled"] - result["beta_true_labels"]).mean()
        # Attenuation is multiplicative, so it has nothing to act on at zero.
        assert abs(bias) < 0.03

    def test_bias_scales_with_beta(self):
        from simulate_vintage_error import run

        small = run(n_reps=120, beta=0.20, seed=7)
        large = run(n_reps=120, beta=0.50, seed=7)
        bias_small = (small["beta_mislabelled"] - small["beta_true_labels"]).mean()
        bias_large = (large["beta_mislabelled"] - large["beta_true_labels"]).mean()
        assert bias_large < bias_small, "proportional attenuation, not an additive shift"

    def test_estimator_is_unbiased_with_correct_labels(self):
        from simulate_vintage_error import run

        # Guards the comparison: if the clean arm were biased, the difference
        # between arms would not isolate the labelling error.
        result = run(n_reps=150, beta=0.25, seed=8)
        assert result["beta_true_labels"].mean() == pytest.approx(0.25, abs=0.05)


class TestMinimumDetectableEffect:
    """Power curves are only meaningful if the test they use is calibrated.

    These check the machinery rather than the headline number: correct size
    under the null, monotone power, and interpolation that finds the crossing.
    """

    def test_interpolation_finds_the_crossing(self):
        from minimum_detectable_effect import interpolate_mde

        betas = [0.0, 0.1, 0.2, 0.3, 0.4]
        powers = [0.05, 0.10, 0.40, 0.70, 0.90]
        mde = interpolate_mde(betas, powers, target=0.80)
        assert 0.3 < mde < 0.4

    def test_interpolation_returns_nan_when_target_never_reached(self):
        from minimum_detectable_effect import interpolate_mde

        assert np.isnan(
            interpolate_mde([0.0, 0.1], [0.05, 0.10], target=0.80)
        )

    def test_exact_hit_is_returned(self):
        from minimum_detectable_effect import interpolate_mde

        assert interpolate_mde([0.0, 0.5], [0.05, 0.80], target=0.80) == pytest.approx(0.5)

    def test_shipped_power_curve_is_calibrated_and_monotone(self, repo_data):
        path = repo_data / "minimum_detectable_effect.csv"
        if not path.exists():
            pytest.skip("run analysis/minimum_detectable_effect.py first")
        table = pd.read_csv(path).dropna(subset=["beta"])
        for cluster, group in table.groupby("clustered_on"):
            group = group.sort_values("beta")
            size = group[group["beta"] == 0]["power"].iloc[0]
            assert 0.01 <= size <= 0.10, (
                f"{cluster}: size {size:.3f} is not near the nominal 5%, so the "
                "power curve is measuring a miscalibrated test"
            )
            powers = group["power"].to_numpy()
            # Allow small Monte Carlo dips but require the curve to rise.
            assert powers[-1] > powers[0] + 0.5
            assert all(
                b >= a - 0.06 for a, b in zip(powers, powers[1:])
            ), f"{cluster}: power curve is not monotone"
