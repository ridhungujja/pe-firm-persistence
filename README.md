# Do good private equity funds stay good?

A private equity firm raises a fund. It spends about ten years buying
companies, improving them, and selling them. Then it raises another fund and
does it again.

This project asks one question. If a firm's last fund did well, does its next
fund do well too?

The question matters because pension funds and university endowments decide
where to put money largely on this basis. They back firms whose previous funds
performed. If past performance predicts future performance, that is sensible.
If it does not, a lot of money is being allocated on a pattern that is not
there.

I answer the question with data that US public pension plans are required by
law to publish. The estimate is in `RESULTS.md`. The code is in this
repository and runs end to end.

## What I found

I regress each fund's return on the return of the firm's previous fund. The
coefficient on the previous fund is the answer. Call it beta. A beta of 1 means
performance carries over completely. A beta of 0 means the previous fund tells
you nothing.

![Persistence estimate across specifications](figures/coefficients.png)

Beta is 0.214. The 95% confidence interval runs from -0.057 to 0.485. The
interval contains 0. On this data I cannot tell persistence apart from luck.

That estimate uses 65 pairs of funds drawn from 39 fund families.

A fund family is one firm's numbered series. Blackstone Capital Partners V
through IX is a family. Blackstone Tactical Opportunities is a different
family, run by a different team with a different mandate, even though the same
firm owns both. I measure persistence inside a family. Pooling everything a
firm manages would credit a buyout team with a credit team's results.

Two things about this result are worth more than the number itself.

**The answer depends on how carefully you ask.** Run the same data loosely and
beta is 0.390 with a p-value of 0.005, which looks conclusive. Loosely means
two things. It means pooling funds that are not consecutive, so a 2007 fund
gets treated as the predecessor of a 2021 fund. It means keeping funds that are
too young to have sold anything, so their reported returns are the manager's
own estimate of what the companies are worth. Restrict to consecutive funds
that are old enough to have sold real assets and beta falls to 0.214. The
significance disappears. Same data, opposite conclusion.

**The study could not have found what the literature reports.** I computed the
minimum detectable effect. That is the smallest true beta this sample would
catch most of the time. I simulated data with a known beta, ran my own test on
it, and counted how often the test found the effect. At a true beta of 0.43 the
test finds it 80% of the time. Below that it usually misses.

Studies of funds raised before 2000 report betas around 0.4 to 0.6. Studies of
funds raised after 2000 report well under 0.15. At a true beta of 0.1 my test
finds the effect 7 times in 100. At 0.2 it finds it 19 times in 100. Those are
measured, not interpolated.

So a null result was close to guaranteed before I started. That is a fact about
having 39 families, not a fact about private equity. It is a stronger and more
specific statement than "the estimate was not significant".

## What you need

Python 3.11 or newer. Nothing else is required to reproduce the results.

Install the packages:

```
pip install -r requirements.txt
```

The data is already in this repository. You do not need to download anything.
Two plans are included.

CalPERS publishes one HTML table covering 462 funds, and only for the current
quarter. Oregon PERS publishes a PDF each quarter and leaves old quarters
online. I have 18 of those, covering March 2021 to March 2026 and 490 funds.

I commit the Oregon files rather than downloading them at run time. Oregon
removes old quarters from its website. A file that disappears cannot be
fetched again. Committing them also means the numbers here do not change under
you.

Getting those files was harder than it should have been. Oregon has used five
different naming schemes for the same quarterly report, and files at least one
report in the folder for the wrong year. Guessing URLs from the current scheme
found 8 reports. Reading the links off the Treasury holdings page found 18. The
fetcher reads the page.

## How to run it

```
python -m pytest -q
./run_all.sh --offline
```

The test suite has 224 tests. On a fresh clone 8 of them skip, because they
check tables that the pipeline has not written yet. Run the pipeline and they
pass.

`--offline` uses the committed data and needs no network. Drop the flag to
re-download both plans. Do that only if you want fresher data, and expect the
numbers to move, because Oregon's archive will have shifted.

The whole run takes about ninety seconds. Most of that is two simulation
studies: the power calculation and a check on vintage-year errors.

## What you get

Tables in `data/`, as CSV. The specification table, the mapping robustness
table, the transition test, the power curve, and the cross-plan comparison.

Figures in `figures/`. Six of them, including the one above.

The write-up in `RESULTS.md`. That is the paper-shaped version: what is
estimated, the table, the inference, the limitations.

A record of the work in `DEVELOPMENT_LOG.md`. Design decisions, and the things
that turned out to be wrong.

The code:

```
src/pefund/metrics.py       TVPI, IRR, Kaplan-Schoar PME, Direct Alpha
src/pefund/persistence.py   the estimator and every test around it
src/pefund/ingest/          one adapter per data source, plus shared cleaning
analysis/                   one script per output
```

## How much you can trust it

I checked the estimate five ways. None of them changed the answer.

**The estimator recovers a known answer.** I simulate fund histories with a
persistence I choose myself, then run the real estimation code on them. Across
six settings with true betas from 0.00 to 0.44, every confidence interval
covers the truth.

**Standard errors use a wild cluster bootstrap.** Funds from the same firm are
not independent observations. The usual fix is clustering, which widens the
error bars to account for that. Clustering relies on having many groups. I have
39. To check whether that is enough I generated data with no persistence at
all and counted how often each method wrongly found some. At 20 groups the
standard method reported a false positive 9 to 13 times in 100, against the 5
it should. The bootstrap reported 4 to 6.

The bootstrap works by imposing the answer of zero on the data, then flipping
the sign of each firm's residuals at random, thousands of times, to see how
large a coefficient turns up by chance. Every p-value in the table is computed
this way. Every one is larger than the standard method's. The standard method
was manufacturing persistence, not hiding it.

**Fund-name matching does not drive the result.** The largest manual step in
this project is deciding which funds belong to the same family. Names are
inconsistent. "Advent International GPE V-D" and "Advent International GPE
VI-A" are the same series, but a share-class letter on the end stops any simple
rule from seeing it. I hand-checked and recorded 70 merge decisions, each with
a reason. Running the estimate with no merges, with only the certain merges,
and with all of them gives betas of 0.270, 0.245 and 0.214. The spread is
smaller than one standard error.

**No single firm or year carries it.** Dropping each family in turn and
refitting gives betas between 0.138 and 0.281 across 39 refits. Dropping each
year gives 0.118 to 0.308 across 17. None of them produces a negative beta.

**It is not an artefact of the functional form.** Ranking funds within their
year and correlating the ranks gives 0.230, with a permutation p-value of
0.239. Same sign, same rough size, same conclusion, and it does not assume the
relationship is a straight line.

**Reporting error is small.** 43 funds appear in both plans on the same
reporting date. That is two independent readings of the same fund. Seven of
them are funds Oregon sold on the secondary market, where the reported figure
is a sale price rather than a valuation, so I exclude them. On the remaining
36, the median disagreement between the two plans is 0.82%. Correcting the
estimate for that much noise moves beta from 0.214 to 0.217.

### A reasoning error that the simulation caught

I expected mislabelled vintage years to inflate beta. The vintage year is the
year a fund started investing, and I control for it, because funds that started
in 2006 all faced the same market. The two plans disagree about the vintage
year for 18 of the 43 shared funds. CalPERS is always the later of the two,
never earlier.

My argument was this. A fund assigned to the wrong year keeps some of its own
year's market movement in the residual. A firm's consecutive funds sit in
nearby years, so those leftovers are correlated across the pair. Correlated
leftovers are exactly what beta picks up. Therefore mislabelling inflates beta,
and 0.214 is an upper bound.

I simulated it before writing it down. The simulation gave the opposite sign.
Displacing the labels by the pattern I actually observe moves beta from 0.264
to 0.226 at a true beta of 0.25, and from 0.511 to 0.441 at 0.50. The bias is
about -14%, and it is 0 when the true beta is 0.

The argument was wrong because it followed the residual and forgot the
regressor. The same unabsorbed market movement lands in the previous fund's
return as well, and noise in a regressor pulls a coefficient toward 0. That
effect is the larger of the two. It is also the same mechanism this project
already documented for leaving vintage controls out entirely, which I had not
connected.

So beta is a lower bound with respect to this error, not an upper bound. There
are five tests pinning the direction so the write-up cannot drift back to my
first instinct.

## Limitations

**The sample is small, and that dominates everything.** 65 pairs, 39 families.
See the power calculation above.

**Only funds that are still open appear in the CalPERS table.** Funds that have
fully wound up are removed. So an old fund shows up only if it is still holding
something twenty years on, which is not a random reason to still be around.

**Most funds are too young to have sold much.** Their reported returns are the
manager's own valuation of companies it still owns, not cash returned. Those
valuations are known to be smoothed and out of date, which pulls beta toward 0.
The cross-plan comparison above measures only the part of that error where the
two plans differ. Both plans get their numbers from the same manager, so the
shared part of the error cancels and stays invisible. The real correction is
larger than 1.014 by an unknown amount.

**The vintage year itself is measured with error.** The two plans disagree for
40% of shared funds. Vintage is the main control in every specification.

**Only funds these two plans chose to buy are in the data.** Both are large,
sophisticated investors. The sample is conditioned on a fund having looked
attractive to them beforehand. Nothing in public data fixes this.

**PME is mostly not computable here, by design.** PME compares a fund against
what the money would have earned in the stock market. It needs dated cash
flows. Both plans publish running totals instead. I recover flows by
differencing consecutive snapshots, which only works for funds that had drawn
nothing when my archive starts. That is 63 funds out of 490. Their median PME
is 0.957, but 59 of the 63 still hold about 99% of their value as unsold
companies. That number describes managers' valuations against the market, not
realised returns, and I would not quote it as anything else.

**Neither plan publishes what strategy a fund follows.** So I cannot separate
buyouts from venture capital or credit. I considered guessing from fund names
and did not, because "Ares Corporate Opportunities" and "GSO Energy Partners"
are credit funds whose names do not say so.

## Sources

The data comes from two public disclosures:

- CalPERS Private Equity Program Fund Performance.
- Oregon PERS OPERF Private Equity Portfolio, quarterly.

The benchmark for PME is the market factor from the Kenneth French data
library. It is a total return, which includes dividends. A price index such as
the headline S&P 500 leaves dividends out, worth about two percentage points a
year, which compounds to roughly 22% of the benchmark over a ten-year fund
life. Using one would make every PME look better than it is.

The Oregon report carries a warning from the plan itself. It says its IRRs
"SHOULD NOT be used to assess the investment success of a partnership or to
compare returns across partnerships" and "HAVE NOT been approved by the
individual general partners". That is the disclosing institution describing the
measurement problem in its own words, and it is quoted in the code that parses
the file.

The files under `data/snapshots/` are public records. They are reproduced here
so the analysis still runs after the plans remove them. They are not covered by
this repository's MIT license.

Papers this project leans on:

- Kaplan, S. and Schoar, A. 2005. "Private Equity Performance: Returns,
  Persistence, and Capital Flows." *Journal of Finance* 60 (4).
- Harris, R., Jenkinson, T. and Kaplan, S. 2014. "Private Equity Performance:
  What Do We Know?" *Journal of Finance* 69 (5).
- Braun, R., Jenkinson, T. and Stoff, I. 2017. "How Persistent is Private
  Equity Performance?" *Journal of Financial Economics* 123 (2).
- Korteweg, A. and Nagel, S. 2016. "Risk-Adjusting the Returns to Venture
  Capital." *Journal of Finance* 71 (3).
- Cameron, A.C., Gelbach, J. and Miller, D. 2008. "Bootstrap-Based Improvements
  for Inference with Clustered Errors." *Review of Economics and Statistics*
  90 (3).
- Gredil, O., Griffiths, B. and Stucke, R. 2014. "Benchmarking Private Equity:
  The Direct Alpha Method."
- Takahashi, D. and Alexander, S. 2002. "Illiquid Alternative Asset Fund
  Modeling." *Journal of Portfolio Management* 28 (2).
