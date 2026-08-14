# DATA_SOURCES.md

Additional data for the persistence study. Ordered by what each unlocks.

---

## 1. Oregon PERS — quarterly PDF archive (highest value)

Oregon publishes its private equity portfolio quarterly, and **past quarters
stay online at predictable URLs**. Observed pattern:

```
https://www.oregon.gov/treasury/invested-for-oregon/Documents/
  Invested-for-OR-Performance-and-Holdings/{YEAR}/
  OPERF_Private_Equity_Portfolio_-_Quarter_{N}_{YEAR}.pdf
```

Confirmed live: `2025/OPERF_Private_Equity_Portfolio_-_Quarter_1_2025.pdf`
and `2023/OPERF_Private_Equity_Portfolio_-_Quarter_4_2023.pdf`. Start from the
Oregon Treasury holdings page and confirm the current naming before assuming
the pattern holds for every year; it has changed in the past.

Columns: vintage year, partnership name, capital commitment, total capital
contributed, capital distributed, fair value (NAV), net IRR, TVPI. Funds held
under three years are marked NM, the same convention CalPERS uses.

**Why this is the priority.** A back archive of quarterly snapshots means
`reconstruct_flows_from_snapshots` works *now*. Differencing cumulative
contributions and distributions across consecutive quarters recovers
approximate quarterly cash flows, which makes Kaplan-Schoar PME and Direct
Alpha computable on real data. WORK_BRIEF Stage 4 assumed waiting quarters
for a second snapshot. Pull the archive instead and skip the wait.

Caveats to carry into the write-up: quarterly differencing dates every flow at
quarter-end, so within-quarter timing is lost and IRRs shift slightly.
Restatements appear as negative flows and must be zeroed, not passed through.
Secondary sales show up as large distributions that are not realisations in
the usual sense.

These are PDFs, not HTML. Use `pdfplumber` for table extraction — it handles
ruled tables better than `pypdf` for this shape. Expect the parser to be more
work than the CalPERS one, and write tests against saved fixture pages so the
suite does not depend on the network.

### Oregon's own disclaimer — quote it

The report carries an explicit warning from the plan itself: because the
industry lacks valuation standards, investment pace differs across
partnerships, and returns are understated early in a fund's life, the IRRs in
the report do not reflect current or expected returns and should not be used
to assess a partnership's success or to compare returns across partnerships.
It also notes the figures were never approved by the general partners.

This is a primary-source statement of the measurement problem, from the
disclosing institution, and it belongs in the limitations section. Paraphrase
it and cite the specific quarterly report. It is considerably stronger than
asserting the same point in your own voice.

---

## 2. Kenneth French Data Library — the PME benchmark

The market factor is a value-weighted total return on the entire US equity
market, monthly back to 1926, free.

```
https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
Direct: .../ken.french/ftp/F-F_Research_Data_Factors_CSV.zip
```

The file gives `Mkt-RF` and `RF` as monthly percentages. Market total return
is `Mkt-RF + RF`; compound it into a level series and it drops straight into
`load_benchmark`.

Use this rather than an S&P 500 price series. It is a total return including
dividends, it is the standard benchmark in the academic PME literature so your
numbers are comparable to published estimates, and it covers the whole market
rather than large caps only. Missing values are coded -99 or -99.99 in the raw
file and must become NaN before compounding, or the level series is destroyed.

Consider also reporting PME against a small-cap or value benchmark. Buyout
targets are not the market portfolio, and Korteweg-Nagel argue the risk
adjustment matters. A second benchmark column costs almost nothing and shows
you understand the choice is not innocuous.

---

## 3. Additional plans, in rough order of usefulness

Several states require fund-level disclosure under public records statutes.
Beyond CalPERS and Oregon, check CalSTRS, Washington State Investment Board,
Massachusetts PRIM, New York State Common Retirement Fund, and TRS Texas.

Check the published format before committing to any of them — some publish
HTML, some PDF, some spreadsheets, and the parsing effort varies by an order
of magnitude. Two well-parsed plans beat five half-parsed ones.

**The overlap is the prize, not the extra rows.** Every fund appearing in two
plans is one underlying fund reported twice, independently. That supports the
measurement-error work in WORK_BRIEF Stage 3.2, and it is the most distinctive
thing available in this project.

---

## 4. Things deliberately not on this list

- **Preqin, Burgiss, PitchBook, Cambridge Associates.** Paywalled. Some
  universities hold subscriptions through the library — worth checking, but do
  not build the project assuming access.
- **Secondary aggregator sites** reporting pension performance. Their numbers
  are derived from the same primary disclosures with unclear processing. Go to
  the plan's own publication.
- **SEC Form ADV.** Firm-level assets and ownership, no fund performance. Not
  useful here.

---

## Implementation order

1. Oregon quarterly archive, most recent quarter first. Confirm the parser
   against one PDF before pulling many.
2. Once two or more Oregon snapshots parse, difference them and compute PME
   with the French benchmark. This is the first real PME in the project.
3. Match Oregon against CalPERS on fund name to build the overlap sample, then
   estimate reporting-error variance from the paired differences.
4. Only then consider a third plan.

Keep every downloaded file under `data/snapshots/` with its source and date in
the filename, and never overwrite one. The archive is the asset.
