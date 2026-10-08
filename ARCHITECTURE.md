# Architecture

The installed application lives in `src/earnings_calculator`. The console
command `earnings-calculator` and `python -m earnings_calculator` both launch
`gui.main()`. `src/Legacy` and `src/Experimental` contain reference scripts;
they are preserved but are not part of the installed package.

## Runtime modules

| Module | Responsibility |
|---|---|
| `gui.py` | Tkinter controls, filters, sortable results, CSV export, background workers |
| `scanner.py` | Earnings scan orchestration, liquidity filtering, stock analysis, OTC list updater |
| `calendar.py` | Nasdaq calendar JSON, date-specific release sessions, explicit fetch errors |
| `options.py` | Yahoo price/options data, Yang-Zhang volatility, ATR, IV interpolation, expected move |
| `chart.py` | Interactive candlestick charts using yfinance and mplfinance |
| `proxy.py` | Optional proxy discovery, validation, cancellation and rotation |
| `sessions.py` | Requests sessions for calendar HTTP calls; yfinance manages its own sessions |
| `logging_config.py` | Shared file and console logging helpers |
| `cache.py` | Public, tested pickle cache utility retained for reuse; not used by current scans |
| `__init__.py` | Public exports |

## Earnings scan flow

1. The GUI selects dates, using US Eastern time for the current date.
2. The default overnight mode requests today's after-hours releases and the
   next calendar morning's pre-market releases. Unknown times are excluded.
   Other modes scan a date or business-day range.
3. The calendar fetcher requests Nasdaq JSON with a timeout, retries once,
   and raises `EarningsCalendarError` on failure. A failed fetch is distinct
   from a successful empty calendar. Timing belongs to earnings releases,
   not exact conference-call times.
4. The scanner excludes known OTC tickers, downloads one year of price
   history in batches of ten, and checks mean volume over 30 trading sessions.
   Stocks below 1,500,000 shares or without sufficient history are skipped
   before fetching options. Each scan uses fresh history.
5. Up to five workers analyze qualifying stocks. The supplied history is
   reused for volatility and options calculations. The earnings date and
   session from the calendar are preserved in each result.
6. The GUI receives progress and results through `root.after()` callbacks.
   Calendar failures appear in the status bar. Results support filtering,
   chart display and CSV export.

## Analysis criteria

`options.py` defines `FILTER_MAX_DTE = 45`, `IV_INTERPOLATION_DTE = 30`, and
`MIN_AVG_VOLUME = 1_500_000`. `scanner.py` defines the classification thresholds:

| Label | Criteria |
|---|---|
| Recommended | Volume passes, IV30/RV30 >= 1.25, term slope <= -0.00406 |
| Consider | Term slope passes and exactly one of volume or IV ratio passes |
| Avoid | Remaining combinations or unavailable options analysis |

Single-symbol analysis can include stocks that fail volume. Earnings scans
apply the volume threshold before analysis. Volatility uses Yang-Zhang with
simple return volatility as a fallback; ATR uses 14 sessions. ATM call and put
IVs across expirations supply the interpolated IV30 and term slope.

## Connections and runtime files

Proxies are disabled on GUI startup. Optional proxies apply to requests
sessions; Yahoo requests use yfinance's own session management. The OTC updater
runs at startup, uses timeouts and atomically replaces its file only when it
retrieves data successfully.

Logs, `otc-tickers.txt`, virtual environments, and `stock_cache/` are ignored
by Git. The retained `DataCache` utility has a seven-day expiry, missing-field
tracking, and locked updates. No scan results currently use that cache.

## Dependencies and checks

`pyproject.toml` declares runtime and development dependencies; `uv.lock`
records resolved versions. BeautifulSoup supports proxy HTML parsing;
curl-cffi supplies yfinance's HTTP implementation. Matplotlib and mplfinance
render charts, scipy interpolates IV, and tkcalendar supplies date selection.

Run checks from the repository directory:

```powershell
..\venv\Scripts\python.exe -m pytest tests -q
```

Tests mock external market-data requests. GUI integration tests need a display
and skip when Tk cannot start. Legacy and experimental scripts are outside the
application test suite. Publishing source changes is a separate Git operation;
app startup never commits or pushes files.
