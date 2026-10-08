# Maths audit and sandbox integration

## Corrected calculations

The earlier Yang-Zhang implementation used uncentered squared close-to-close
returns and divided Rogers-Satchell by n-1. The corrected estimator uses
centered sample variances of overnight and open-to-close log returns and the
arithmetic mean of Rogers-Satchell:

```
o[t] = log(Open[t] / Close[t-1])
c[t] = log(Close[t] / Open[t])
rs[t] = log(High[t]/Open[t]) * log(High[t]/Close[t])
      + log(Low[t]/Open[t]) * log(Low[t]/Close[t])
k = 0.34 / (1.34 + (n+1)/(n-1))
YZ = sqrt(252 * (sample_variance(o) + k*sample_variance(c) + (1-k)*mean(rs)))
```

Each component uses the same n=30 completed trading sessions. The overnight
component requires the preceding close, so at least 31 rows are needed. This
formulation is described in the [research hosted by CME](https://www.cmegroup.com/content/dam/cmegroup/education/files/improving-time-series-momentum-strategies.pdf).
The fallback is the annualized sample standard deviation of close-to-close
log returns. Zero or non-finite RV never becomes a fabricated large IV/RV
ratio. Incomplete history is unavailable. Ratios and option IVs are annualized
fractions; for example 0.30 means 30% annualized volatility.

ATR is explicitly a **simple 14-session mean of true range**, not Wilder's
recursive smoothed ATR. True range is max(High-Low, abs(High-previous Close),
abs(Low-previous Close)); the first bar uses High-Low. ATR% = 100*ATR/current
underlying price. The latest price is fetched separately from completed bars
for ATM strike selection and expected-move calculations. Today's partial
candle never enters realized volatility or the volume test.

Calls and puts use the same nearest available strike. IVs must be finite and
positive. Expirations are sorted/deduplicated, expired and 0-DTE contracts are
excluded, and only knots needed for front IV, IV30 and the 45-day endpoint are
requested. Linear IV interpolation requires actual expirations spanning both
30 and 45 days. Insufficient coverage is unavailable; clamping is not used to
manufacture a valid recommendation. The slope is:

```
(IV(45) - IV(front_DTE)) / (45 - front_DTE)
```

Units are annualized volatility fraction per calendar day. The existing
threshold remains -0.00406; the IV30/RV30 threshold remains 1.25. Correcting RV
can change recommendations. These thresholds have **not been recalibrated or
validated by a strategy backtest**.

Expected move is the nearest-expiry ATM straddle mid-price divided by the
latest underlying price, expressed as a percentage. Quotes must be positive,
finite, and non-crossed. Stale last-trade prices are not substituted for missing
bids/asks. This is a market-price proxy, not a probability bound or a pricing
model. Yahoo does not establish that quotes are executable or fresh enough
for an order. Missing valid straddle quotes make the scanner result unavailable.

The former IV Rank used historical realized volatility extrema and was
mislabelled. `iv_rank` is now null. A true IV Rank needs a historical series of
comparable implied-volatility observations, which this data source/workflow
does not collect.

Average volume is the arithmetic mean of the last 30 completed sessions and
must be >=1,500,000 shares. An incomplete rolling window does not pass. Monthly
volume data is a snapshot; daily scans recheck qualifying symbols. Companies
that gain liquidity after the monthly snapshot require a refreshed shortlist.

## Verification

`tests/test_math_audit.py` contains an independent scalar implementation using
Python `math` and `statistics`. It compares the production estimator across
10 random seeds and 3 window lengths with tight numeric tolerance. It also
checks scale invariance, constant drift, exact log-return sample volatility,
ATR including overnight gaps, known term-structure slope/IV30/straddle results,
latest spot versus cached close, zero/non-finite RV, invalid IV, crossed quotes,
insufficient expiry coverage and insufficient volume history.

`tests/test_market_data.py` verifies persistent hourly/daily budgets, pacing,
shared cooldown after 429, no immediate options retry after rate limiting and
exclusion/reuse of partial daily candles. `tests/test_monthly.py` checks
checkpoint resumption, safe month replacement, failed refresh preservation,
incomplete-file rejection, checksum validation, weekends, holidays and early
closes using [exchange-calendars](https://github.com/gerrymanoim/exchange_calendars).
GUI tests check removal of proxy controls, visible failure status and main-thread
callbacks. Existing classification branch/boundary tests remain in place.

## Sandbox consumer contract

This project contains no trading engine and no order submission. A future
sandbox consumer should:

1. Read `monthly_earnings.meta.json`, require `complete: true`, check its month
   and SHA-256 against the CSV, and reject schema versions it does not support.
2. Select rows with `status=ready`, `volume_pass=True`, a known release session,
   and an applicable `analysis_date`/ET analysis window. The monthly `ready`
   flag only means ready for analysis; it is not an order signal.
3. Confirm the event timing/date with a current calendar before running options
   analysis; monthly earnings estimates can change. Use the dates in the file
   with their ET offsets, including early closes, rather than weekday arithmetic.
4. Require the scanner's `analysis_status=ok`, `analysis_error=null`, finite
   required metrics and a measured expected move before using its label.
   `Unavailable`, a paused budget, empty history or a partial CSV must never
   be interpreted as an Avoid signal or a trading opportunity.
5. Recheck current price, liquidity and executable quotes in the sandbox's own
   market-data layer. Numerical tests verify calculation mechanics and failure
   handling, not trading profitability, fills or predictive accuracy.

No scheduled task performs options analysis or places orders. The CSV refresh
reuses a completed month, and a partially built month resumes under the same
persistent Yahoo budget instead of bypassing a provider block.
