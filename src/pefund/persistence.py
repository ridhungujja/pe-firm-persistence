"""Performance persistence estimators.

The object of interest is beta in

    y_{i,k} = alpha + beta * y_{i,k-1} + gamma' X_{i,k} + delta_v + u_{i,k}

where i indexes the GP, k the fund's sequence number within that GP, and
delta_v a vintage fixed effect. y is a performance measure in logs (log TVPI
or log PME) so that beta is a unit-free elasticity and the left tail is not
compressed against zero.

Three things make this harder than a standard AR(1) panel and each has a
counterpart in the reporting code below:

1.  Selection. A GP appears with fund k+1 only if it managed to raise one.
    Poor funds are censored, which attenuates beta.
2.  Look-ahead. Predecessor performance is usually observed at its *final*
    value, which was not knowable when the successor was raised. Using it
    overstates what an LP could have acted on.
3.  Measurement error. Interim NAVs are stale and smoothed, so y_{i,k-1}
    measured early is a noisy proxy; classical attenuation applies and beta
    is biased toward zero.

Standard errors are clustered two-way on firm and vintage by default: funds
of the same GP share a skill component, and funds of the same vintage share
a market shock.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import patsy
import statsmodels.formula.api as smf


@dataclass
class PersistenceResult:
    spec: str
    n_obs: int
    n_firms: int
    beta: float
    se: float
    tstat: float
    pvalue: float
    r_squared: float
    model: object = None

    def as_row(self) -> dict:
        return {
            "specification": self.spec,
            "beta": round(self.beta, 4),
            "std_error": round(self.se, 4),
            "t": round(self.tstat, 2),
            "p": round(self.pvalue, 4),
            "n_funds": self.n_obs,
            "n_firms": self.n_firms,
            "r2": round(self.r_squared, 3),
        }


def build_panel(
    funds: pd.DataFrame,
    metrics: pd.DataFrame,
    performance_col: str = "tvpi",
    predecessor_col: str | None = None,
) -> pd.DataFrame:
    """Join fund attributes to metrics and attach the predecessor fund.

    Parameters
    ----------
    funds : must contain fund_id, firm_id, sequence, vintage.
    metrics : output of `pefund.metrics.summarise_panel`.
    performance_col : column in `metrics` used as the dependent variable.
    predecessor_col : column holding the predecessor's performance *as known
        at the successor's fundraise date*. When None, the predecessor's
        final performance is used and the estimate carries look-ahead bias.
    """
    required = {"fund_id", "firm_id", "sequence", "vintage"}
    missing = required - set(funds.columns)
    if missing:
        raise ValueError(f"funds is missing columns: {sorted(missing)}")

    df = funds.merge(metrics, on="fund_id", how="inner", validate="one_to_one")
    df = df.sort_values(["firm_id", "sequence"]).reset_index(drop=True)

    df["y"] = np.log(df[performance_col].clip(lower=0.01))

    grouped = df.groupby("firm_id", sort=False)
    if predecessor_col is None:
        df["y_lag"] = grouped["y"].shift(1)
        df["lag_source"] = "final"
    else:
        df["y_lag"] = np.log(grouped[predecessor_col].shift(1).clip(lower=0.01))
        df["lag_source"] = "interim"

    df["prior_sequence"] = grouped["sequence"].shift(1)
    df["log_commitment"] = np.log(df["commitment"]) if "commitment" in df else np.nan

    # `sequence` is a rank within the family, not the fund's own number. If a
    # plan holds Silver Lake III and VII, those rank 1 and 2 and the regression
    # silently treats a 2007 fund as the immediate predecessor of a 2021 one.
    # That estimates "does any earlier fund predict any later fund", which is a
    # different and weaker claim than "does fund k predict fund k+1". The gaps
    # below let a specification say which question it is answering.
    if "fund_number" in df.columns:
        df["prior_fund_number"] = grouped["fund_number"].shift(1)
        df["fund_number_gap"] = df["fund_number"] - df["prior_fund_number"]
    else:
        df["prior_fund_number"] = np.nan
        df["fund_number_gap"] = np.nan

    df["prior_vintage"] = grouped["vintage"].shift(1)
    df["vintage_gap"] = df["vintage"] - df["prior_vintage"]

    if "vintage_anomaly" in df.columns:
        df["prior_vintage_anomaly"] = grouped["vintage_anomaly"].shift(1)
    return df


def _prepare(
    panel: pd.DataFrame,
    controls: tuple[str, ...],
    vintage_fe: bool,
    cluster_on: tuple[str, ...],
    max_gap: int | None,
    drop_vintage_anomalies: bool,
    spec_name: str = "spec",
) -> pd.DataFrame:
    """Apply the sample restrictions a specification asks for.

    Shared by `estimate` and `wild_cluster_bootstrap` so the two can never
    disagree about which observations they are describing. A bootstrap p-value
    computed on a different sample from the coefficient it qualifies would be
    worse than no bootstrap at all.
    """
    cols = ["y", "y_lag", *controls, *cluster_on]
    if vintage_fe and "vintage" not in cols:
        cols.append("vintage")
    df = panel.dropna(subset=[c for c in cols if c in panel.columns]).copy()

    if max_gap is not None:
        if "fund_number_gap" not in df.columns or df["fund_number_gap"].isna().all():
            raise ValueError(
                f"{spec_name}: max_gap needs a fund_number_gap column with at "
                "least one parsed gap; build_panel produces it when funds carry "
                "a fund_number, so check that parse_fund_number ran upstream"
            )
        df = df[df["fund_number_gap"].notna() & (df["fund_number_gap"] <= max_gap)]

    if drop_vintage_anomalies and "vintage_anomaly" in df.columns:
        # Drop the pair when either end is suspect: a bad predecessor vintage
        # corrupts y_lag just as surely as a bad own one.
        bad = df["vintage_anomaly"].fillna(False).astype(bool)
        if "prior_vintage_anomaly" in df.columns:
            bad = bad | df["prior_vintage_anomaly"].fillna(False).astype(bool)
        df = df[~bad]

    if df.empty:
        raise ValueError(f"{spec_name}: no complete observations")
    return df


def _cluster_codes(df: pd.DataFrame, cluster_on: tuple[str, ...]) -> np.ndarray:
    codes = [pd.Categorical(df[c]).codes for c in cluster_on]
    return np.column_stack(codes) if len(codes) > 1 else codes[0]


def estimate(
    panel: pd.DataFrame,
    spec_name: str,
    controls: tuple[str, ...] = (),
    vintage_fe: bool = True,
    cluster_on: tuple[str, ...] = ("firm_id", "vintage"),
    max_gap: int | None = None,
    drop_vintage_anomalies: bool = False,
) -> PersistenceResult:
    """OLS of y on y_lag with optional vintage fixed effects and controls.

    max_gap : restrict to pairs whose fund numbers are at most this far apart.
        `max_gap=1` gives adjacent funds only, which is the LP's actual
        decision problem: fund k has just been raised and fund k+1 is being
        marketed. The default of None keeps every consecutive pair the plan
        happens to hold and answers a looser question. Pairs with an unknown
        fund number are dropped when this is set, because the gap cannot be
        verified for them.
    drop_vintage_anomalies : exclude funds whose reported vintage contradicts
        their position in the series. Never on by default; the estimate should
        be shown both ways.
    """
    df = _prepare(
        panel, controls, vintage_fe, cluster_on, max_gap, drop_vintage_anomalies,
        spec_name,
    )

    terms = ["y_lag", *controls]
    if vintage_fe:
        terms.append("C(vintage)")
    formula = "y ~ " + " + ".join(terms)

    ols = smf.ols(formula, data=df)
    fit = ols.fit(
        cov_type="cluster",
        cov_kwds={"groups": _cluster_codes(df, cluster_on), "df_correction": True},
    )

    # A two-way clustered covariance matrix is a sum and difference of three
    # matrices and is not guaranteed positive semi-definite in finite samples;
    # when it fails, some variances come back negative and statsmodels returns
    # NaN standard errors. Falling back to one-way clustering on the first
    # dimension is the conservative choice, and the spec label records it so
    # the change never disappears into a results table unannounced.
    if not np.isfinite(fit.bse.get("y_lag", np.nan)):
        warnings.warn(
            f"{spec_name}: two-way clustered covariance was not PSD; "
            f"falling back to clustering on {cluster_on[0]} only.",
            RuntimeWarning,
            stacklevel=2,
        )
        cluster_on = (cluster_on[0],)
        spec_name = f"{spec_name} [1-way cluster]"
        fit = ols.fit(
            cov_type="cluster",
            cov_kwds={"groups": _cluster_codes(df, cluster_on), "df_correction": True},
        )

    return PersistenceResult(
        spec=spec_name,
        n_obs=int(fit.nobs),
        n_firms=df["firm_id"].nunique(),
        beta=float(fit.params["y_lag"]),
        se=float(fit.bse["y_lag"]),
        tstat=float(fit.tvalues["y_lag"]),
        pvalue=float(fit.pvalues["y_lag"]),
        r_squared=float(fit.rsquared),
        model=fit,
    )


@dataclass
class BootstrapResult:
    spec: str
    beta: float
    t_observed: float
    p_analytic: float
    p_bootstrap: float
    n_boot: int
    n_clusters: int
    t_null: np.ndarray = None

    def as_row(self) -> dict:
        return {
            "specification": self.spec,
            "beta": round(self.beta, 4),
            "t": round(self.t_observed, 2),
            "p_analytic": round(self.p_analytic, 4),
            "p_bootstrap": round(self.p_bootstrap, 4),
            "clusters": self.n_clusters,
        }


def _design(
    panel: pd.DataFrame,
    controls: tuple[str, ...],
    vintage_fe: bool,
    cluster_col: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Return (y, X, cluster codes, index of the y_lag column)."""
    terms = ["y_lag", *controls]
    if vintage_fe:
        terms.append("C(vintage)")
    formula = "y ~ " + " + ".join(terms)
    y, X = patsy.dmatrices(formula, data=panel, return_type="dataframe")
    lag_idx = list(X.columns).index("y_lag")
    codes = pd.Categorical(panel.loc[X.index, cluster_col]).codes
    return (
        np.asarray(y).ravel(),
        np.asarray(X, dtype=float),
        np.asarray(codes),
        lag_idx,
    )


def _clustered_t(
    y: np.ndarray,
    X: np.ndarray,
    codes: np.ndarray,
    lag_idx: int,
    xtx_inv: np.ndarray,
    projector: np.ndarray,
    leverage: np.ndarray,
    indicator: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Coefficient and cluster-robust t on `lag_idx`, vectorised over columns of y.

    Uses the identity that the clustered variance of a single coefficient j is
    sum_g (sum_{i in g} h_i e_i)^2 with h = X @ (X'X)^-1 e_j, so only one
    n-vector has to be recomputed per bootstrap replication instead of a full
    k x k sandwich.
    """
    y = np.atleast_2d(y.T).T if y.ndim > 1 else y[:, None]
    beta = projector @ y                       # k x B
    resid = y - X @ beta                       # n x B
    cluster_sums = indicator @ (leverage[:, None] * resid)   # G x B
    variance = (cluster_sums**2).sum(axis=0)

    n, k = X.shape
    n_clusters = indicator.shape[0]
    correction = (n_clusters / (n_clusters - 1)) * ((n - 1) / (n - k))
    se = np.sqrt(variance * correction)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = beta[lag_idx] / se
    return beta[lag_idx], t


def wild_cluster_bootstrap(
    panel: pd.DataFrame,
    spec_name: str,
    controls: tuple[str, ...] = (),
    vintage_fe: bool = True,
    cluster_col: str = "firm_id",
    max_gap: int | None = None,
    drop_vintage_anomalies: bool = False,
    n_boot: int = 9999,
    seed: int = 20240813,
) -> BootstrapResult:
    """Wild cluster bootstrap-t for H0: beta = 0, with Rademacher weights.

    Cluster-robust asymptotics need many clusters. Cameron, Gelbach and Miller
    (2008) put the rule of thumb near 40, and the finite-sample distortion is
    worst when cluster sizes are unbalanced, which a public-plan panel always
    is: a handful of families contribute six or seven funds and most contribute
    one pair. With roughly 75 families here the analytic p-value is a
    borderline object, and it errs toward over-rejection -- it finds
    persistence that is not there rather than missing persistence that is.

    The procedure imposes the null before resampling, which is what makes it
    work at small cluster counts:

    1. Fit the restricted model, dropping y_lag, so the null beta = 0 holds by
       construction. Keep its fitted values and residuals.
    2. Draw a weight in {-1, +1} for each cluster, not each observation, so the
       within-family error correlation is preserved.
    3. Rebuild the outcome as fitted + weight * residual, re-estimate the
       *unrestricted* model, and record the t-statistic on y_lag.
    4. The bootstrap p-value is the share of null t-statistics at least as
       extreme as the observed one.

    Rademacher weights are used rather than Mammen's because with a two-point
    distribution the bootstrap is exact up to the number of distinct weight
    vectors; with fewer than about 12 clusters that becomes a binding
    constraint (2^G draws), but at 75 it is not.

    Where the analytic and bootstrap p-values disagree, report the bootstrap.
    """
    result = estimate(
        panel,
        spec_name,
        controls=controls,
        vintage_fe=vintage_fe,
        cluster_on=(cluster_col,),
        max_gap=max_gap,
        drop_vintage_anomalies=drop_vintage_anomalies,
    )
    df = _prepare(
        panel, controls, vintage_fe, (cluster_col,), max_gap,
        drop_vintage_anomalies, spec_name,
    )

    y, X, codes, lag_idx = _design(df, controls, vintage_fe, cluster_col)
    n_clusters = int(codes.max()) + 1
    indicator = np.zeros((n_clusters, len(codes)))
    indicator[codes, np.arange(len(codes))] = 1.0

    xtx_inv = np.linalg.pinv(X.T @ X)
    projector = xtx_inv @ X.T
    leverage = X @ xtx_inv[:, lag_idx]

    _, t_obs = _clustered_t(
        y, X, codes, lag_idx, xtx_inv, projector, leverage, indicator
    )
    t_observed = float(t_obs[0])

    # Restricted fit: the null is imposed by removing y_lag entirely.
    X_r = np.delete(X, lag_idx, axis=1)
    beta_r = np.linalg.pinv(X_r.T @ X_r) @ X_r.T @ y
    fitted_r = X_r @ beta_r
    resid_r = y - fitted_r

    rng = np.random.default_rng(seed)
    weights = rng.choice((-1.0, 1.0), size=(n_clusters, n_boot))
    y_star = fitted_r[:, None] + weights[codes, :] * resid_r[:, None]

    _, t_null = _clustered_t(
        y_star, X, codes, lag_idx, xtx_inv, projector, leverage, indicator
    )
    t_null = np.asarray(t_null, dtype=float)
    finite = t_null[np.isfinite(t_null)]

    # The +1 in numerator and denominator keeps the p-value from ever being
    # exactly zero, which would misstate the resolution of a finite bootstrap.
    p_boot = (1 + np.sum(np.abs(finite) >= abs(t_observed))) / (len(finite) + 1)

    return BootstrapResult(
        spec=spec_name,
        beta=result.beta,
        t_observed=t_observed,
        p_analytic=result.pvalue,
        p_bootstrap=float(p_boot),
        n_boot=len(finite),
        n_clusters=n_clusters,
        t_null=finite,
    )


def results_table(results: list[PersistenceResult]) -> pd.DataFrame:
    return pd.DataFrame([r.as_row() for r in results])


def quartile_transitions(
    panel: pd.DataFrame, within: str = "vintage"
) -> pd.DataFrame:
    """Kaplan-Schoar style transition matrix.

    Rows are the predecessor fund's performance quartile, columns the
    successor's; cells are conditional probabilities. Quartiles are assigned
    within `within` so that a good vintage does not masquerade as a good GP.
    """
    df = panel.dropna(subset=["y", "y_lag"]).copy()
    if df.empty:
        return pd.DataFrame()

    def q(s: pd.Series) -> pd.Series:
        if s.nunique() < 4:
            return pd.Series(np.nan, index=s.index)
        return pd.qcut(s, 4, labels=[1, 2, 3, 4]).astype(float)

    df["q_now"] = df.groupby(within)["y"].transform(q)
    df["q_prev"] = df.groupby(within)["y_lag"].transform(q)
    df = df.dropna(subset=["q_now", "q_prev"])

    table = pd.crosstab(df["q_prev"], df["q_now"], normalize="index")
    table.index.name = "predecessor quartile"
    table.columns.name = "successor quartile"
    return table
