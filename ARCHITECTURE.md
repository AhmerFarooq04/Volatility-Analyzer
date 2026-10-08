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
| `market_data.py` | Shared paced Yahoo session, SQLite request budget/cooldown, completed-bar CSV cache |
| `monthly.py` | Checkpointed monthly earnings/volume CSV, exchange-calendar analysis windows, CLI |
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
   before fetching options. Each scan checks current volume from completed daily bars; same-day cached
   bars are reused instead of downloaded repeatedly.
5. Stocks are analyzed sequentially with one paced Yahoo session. The supplied history is
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

There are no application proxy controls or rotation. Nasdaq uses a direct
requests session. Yahoo uses a shared curl-cffi session with a persistent
request budget and cooldown; every Yahoo operation goes through it. The OTC updater
runs at startup, uses timeouts and atomically replaces its file only when it
retrieves data successfully.

Logs, `otc-tickers.txt`, virtual environments, and `stock_cache/` are ignored
by Git. Monthly CSVs, metadata, request budgets, checkpoints and completed-bar
caches are also ignored. The retained `DataCache` utility has a seven-day expiry, missing-field
tracking, and locked updates. No scan results currently use that cache.

## Dependencies and checks

`pyproject.toml` declares runtime and development dependencies; `uv.lock`
records resolved versions. curl-cffi supplies the guarded Yahoo HTTP session;
exchange-calendars supplies NYSE sessions, holidays and early closes. Matplotlib and mplfinance
render charts, scipy interpolates IV, and tkcalendar supplies date selection.

Run checks from the repository directory:

```powershell
..\venv\Scripts\python.exe -m pytest tests -q
```

Tests mock external market-data requests. GUI integration tests need a display
and skip when Tk cannot start. Legacy and experimental scripts are outside the
application test suite. Publishing source changes is a separate Git operation;
app startup never commits or pushes files.


## Monthly upkeep and sandbox consumers

`scripts/install-monthly-task.ps1` registers a per-user, non-elevated scheduled
job. The hidden runner calls the CLI every two hours, starting at the next
7 AM local time. It collects a new month only when the month changes, then
resumes checkpoints until complete. The separate SQLite job lock prevents
simultaneous GUI/CLI builders. Market-data budgets are shared across all
processes. Publication uses atomic file replacement and a CSV hash in metadata;
readers reject incomplete or mismatched outputs. The current month also includes
the next month's first trading morning to cover the last session's overnight window.

`analysis_status` and `analysis_error` distinguish unavailable data from a
valid negative signal. See `MATH_AUDIT.md` for units and fail-closed sandbox
integration checks. There is no brokerage code, order submission or scheduled
options trading. The task refreshes screening data only.
