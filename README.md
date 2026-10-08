# Earnings Volatility Calculator

A Python-based tool that analyzes options data around earnings events, calculates volatility metrics (like IV30/RV30, ATR, and Yang-Zhang volatility), and provides **Recommended**, **Consider**, or **Avoid** labels based on user-defined criteria. The calculator includes a Tkinter GUI for Windows (or other OS), interactive candlestick charts, and multi-threaded earnings scanning.

> **Disclaimer**: All information contained in this repository, including the source code and associated resources, is provided **for educational and research purposes only**. It does **not** constitute financial advice or recommendation of any investment strategy. Trading options carries significant risk. Always consult a licensed financial advisor before making any investment decisions.

---

## Table of Contents

- [Earnings Volatility Calculator](#earnings-volatility-calculator)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Core Features](#core-features)
  - [Motivation \& Strategy Background](#motivation--strategy-background)
  - [Installation Instructions](#installation-instructions)
    - [Prerequisites](#prerequisites)
    - [Steps](#steps)
  - [Usage](#usage)
    - [Single Stock Analysis](#single-stock-analysis)
    - [Earnings Scan](#earnings-scan)
    - [Interactive Charts](#interactive-charts)
    - [Exporting Data](#exporting-data)
  - [Configuration \& Customization](#configuration--customization)
  - [Troubleshooting \& Common Issues](#troubleshooting--common-issues)
  - [Contributing](#contributing)
  - [License](#license)
  - [Additional Resources](#additional-resources)

---

## Overview

**Earnings Volatility Calculator** leverages market data from [Yahoo Finance](https://finance.yahoo.com/) and [Nasdaq](https://www.nasdaq.com/market-activity/earnings) to identify earnings events, retrieve option chains, and analyze a stock’s implied volatility (IV) relative to its historical or realized volatility (RV). It assigns a recommendation based on volume, IV/RV ratios, and implied volatility term structure slopes.

This project was inspired by research indicating that **shorting volatility during earnings** can provide an edge if specific conditions (e.g., high implied volatility, steep term structure) are met. The included GUI offers a user-friendly way to:

- **Scan** for upcoming earnings.
- **Filter** by timing (Pre/Post/During Market) and recommendation.
- **View** recommended setups.
- **Generate** a candlestick chart with a double-click.

---

## Core Features

- **Tkinter-Based GUI**  
  - Table with sortable columns, color-coded rows, filtering options, and direct CSV export.

- **Paced market data**
  - Shared Yahoo request pacing, persistent budgets and cooldowns.
  - Completed daily history is cached for reuse; scans run sequentially.

- **Options Analysis**  
  - Computes 30-day realized volatility (Yang-Zhang or fallback method).  
  - Fetches Implied Volatilities from ATM calls/puts.  
  - Builds a simple term structure to approximate IV at different expirations.

- **Recommendation Logic**  
  - **Recommended**: Average daily volume ≥ 1,500,000 shares, IV30/RV30 ≥ 1.25, and term slope ≤ –0.00406.  
  - **Consider**: Partial overlap of conditions.  
  - **Avoid**: Fails key criteria or missing data.

- **Candlestick Charts**  
  - Double-click a row to pop up a Matplotlib “candle” chart showing up to 1 year of price data.

---

## Motivation & Strategy Background

This code is loosely based on the insights shared in the [Volatility Vibes YouTube channel](https://www.youtube.com/@VolatilityVibes) video, **“This Option Strategy Turned $10k Into $1 Million In One Year”**. The primary strategy revolves around **selling implied volatility (IV) around earnings** based on the observation that markets often **overprice** near-term earnings volatility.

Key points from the research:

1. **Term Structure & IV Overpricing**  
   Earnings events concentrate uncertainty into near-term options, often causing **implied volatility** to spike and the term structure to invert (negative slope).  
2. **Volume Matters**  
   Stocks with healthy trading volume (both shares and options) often see heightened demand for protection and speculative bets, leading to higher IV.  
3. **IV30 vs. RV30**  
   When short-dated implied volatility is significantly higher than recent realized volatility, it may suggest **overpricing**.  
4. **Risk Management**  
   Selling naked straddles can be highly profitable but also suffers large drawdowns; the referenced video suggests **calendar spreads** might offer a safer risk profile.

For a deep-dive into the underlying concepts, see the [video transcript](#) in the repository or the original YouTube link above.


## Installation Instructions

### Prerequisites

- **Operating System**:
  - Windows 10 or higher (also works on macOS / Linux with minor adjustments)
- **Python**:
  - Version 3.10+ required
- **uv** (recommended):
  - Fast Python package manager. [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Internet Connection**:
  - Required for fetching stock market data from Yahoo Finance and Nasdaq

### Steps (with uv - recommended)

1. **Install uv**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone the Repository**
   ```bash
   git clone https://github.com/AhmerFarooq04/Volatility-Analyzer.git
   cd Volatility-Analyzer
   ```

3. **Install Dependencies**
   ```bash
   uv sync
   ```
   This creates a `.venv/`, installs all dependencies from `uv.lock`, and installs the project as a package.

4. **Run the Application**
   ```bash
   uv run earnings-calculator
   ```
   Or alternatively:
   ```bash
   uv run python -m earnings_calculator
   ```
   The Tkinter UI should open.

5. **Run Tests**
   ```bash
   uv run pytest tests/ -v
   ```

### Steps (with pip - alternative)

1. **Install Python 3.10+**
   - [Download here](https://www.python.org/downloads/) and make sure to check **"Add Python to PATH"** during installation.
   - macOS: `brew install python@3.10 python-tk@3.10`

2. **Clone the Repository and Create a Virtual Environment**
   ```bash
   git clone https://github.com/AhmerFarooq04/Volatility-Analyzer.git
   cd Volatility-Analyzer
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -e .
   ```

4. **Run the Application**
   ```bash
   earnings-calculator
   ```
   The Tkinter UI should open.

---

## Windows PowerShell quick start

From your existing workspace, use the installed virtual environment directly
(no activation required):

```powershell
cd "C:\Users\Mohammed Ahmer\Desktop\volatility advantage\Earnings-Volatility-Calculator"
..\venv\Scripts\python.exe -m earnings_calculator
```

For a fresh checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m earnings_calculator
```

Run from the repository directory so runtime logs and the OTC list stay together.
Launching the app does not perform Git operations. To publish future code edits,
review `git diff`, then stage the intended files, commit, and run `git push origin main`.

## Usage

### Single Stock Analysis

1. Launch the GUI (`python -m earnings_calculator`).
2. In the **“Enter Stock Symbol”** field (top panel), type the stock ticker (e.g. `AAPL`).  
3. Click **“Analyze”**.  

### Earnings Scan

1. Select a date using the **tkcalendar** date picker.  
2. Click **“Scan Earnings”** to fetch a list of all US stocks with earnings on that date.  

### Interactive Charts

- **Double‐click** on any row in the table.  
- A Matplotlib “candle” chart appears, showing approximately 1 year of price/volume history.

### Exporting Data

- Click **“Export CSV”** at the bottom-right of the GUI.  
- Choose a file name and location.

---

## Configuration & Customization

- **Logging & Debug**  
  - Debug logs are written to files (e.g., `options_analyzer_debug.log`).  

---

## Troubleshooting & Common Issues

1. **“No module named tkcalendar”**  
   - Install with `pip install tkcalendar`.
2. **Network or Rate-Limit Failures**
   - Check your network connection. A rate-limit pause must expire before new Yahoo requests can run.
3. **Missing Data or “N/A”**  
   - Some stocks may lack options or have incomplete data.  

---

## Contributing

Contributions, bug reports, and feature requests are welcome!  
- Open an issue or create a pull request on [GitHub](https://github.com/AhmerFarooq04/Volatility-Analyzer).

---

## License

This project is licensed under the [MIT License](./LICENSE).

---

## Additional Resources

- **Volatility Vibes Channel**  
  [This Option Strategy Turned \$10k Into \$1 Million In One Year](https://www.youtube.com/@VolatilityVibes)  

- **Trade Tracker Template**  
  Google Sheets link: [Trade Tracker Template](https://docs.google.com/spreadsheets/)  

- **Further Reading**  
  - *Option Volatility & Pricing* by Sheldon Natenberg  
  - *Options as a Strategic Investment* by Lawrence G. McMillan

**Happy researching!**


### Overnight earnings scan

Select **Tonight + Tomorrow Morning** (the default) and click **Scan**.
The scanner uses today's date in US Eastern time and includes after-hours
releases today plus pre-market releases on the next calendar day. Friday's
scan therefore checks Saturday morning, not Monday. Unknown release times
are excluded from this mode; use Selected Date or a range to include them.
These are earnings release sessions, not exact conference-call times.

The Nasdaq calendar replaces the blocked Investing.com scraper. Calendar
failures appear as `Scan failed` instead of being reported as no earnings.
Each scan checks completed daily history and only runs options analysis for
stocks with a mean volume of at least 1,500,000 shares over 30 trading sessions.
Stocks without sufficient history are skipped. Scan results do not reuse the
old seven-day analysis cache. Completed daily price history is cached and shared with charts and monthly screening. Single-symbol analysis remains available.


## Rate limits and monthly CSV

Proxy controls and rotation have been removed from the application. Yahoo
requests use one shared paced session. The local defaults are a minimum of
3 seconds between request dispatches, at most 120 in a rolling hour and 500
in a rolling 24 hours. The budget is stored under `runtime_data/`, so restarting
the app or running a second monthly process does not reset it. Cookies and
crumb requests use the same session. These are local safeguards, not a Yahoo
quota guarantee; internal redirects can add traffic. Any detected Yahoo 429
or `YFRateLimitError` stops Yahoo requests for at least one hour, respecting
longer numeric Retry-After values. Do not delete the budget database to retry.

Build or resume this month's screening file:

```powershell
..\venv\Scripts\python.exe -m earnings_calculator.monthly
```

The GUI also provides **Refresh Monthly CSV**. A run processes up to 50 new
symbols and saves checkpoints. Rerunning resumes without repeating successful
calendar/volume checks. It does not fetch options. `monthly_earnings.csv`
contains every company supplied by the calendar (including the next month's first trading morning for boundary coverage), volume status, release date
and session, and `analysis_date`, `run_after_et`, `run_before_et`. The window is
the last 30 minutes before the relevant NYSE session closes, including early
closes. Pre-market releases use the preceding trading session. Unknown release
times have no analysis window. The window is a scheduling convention, not a
trade instruction. Dates supplied by the provider can change.

`monthly_earnings.meta.json` declares whether the CSV is complete. Partial
files mark unprocessed rows `needs_data` and are never treated as a complete
shortlist. An old completed CSV is atomically replaced only after its
replacement completes; a failed refresh preserves it. The month check prevents
using last month's shortlist for this month's scan. The monthly screen is a
snapshot and can miss stocks whose volume increases later; use **--refresh**
to rebuild it. Daily analysis rechecks volume on the shortlisted stocks.

Install automatic monthly upkeep on another Windows installation:

```powershell
.\scripts\install-monthly-task.ps1
```

The task is named `VolatilityAnalyzer-MonthlyEarnings`. It starts at the next
7 AM in Windows local time and checks every two hours while your account is
logged in. The first check each new month starts a new file; subsequent checks
resume incomplete work. Once that month's file is complete, checks make no
market-data requests. Offline/asleep computers run when available. Logs go to
`monthly_refresh.log`. Market-data budgets can spread a large month across
several runs or days. Remove the task with:

```powershell
Unregister-ScheduledTask -TaskName VolatilityAnalyzer-MonthlyEarnings -Confirm:$false
```

See [MATH_AUDIT.md](MATH_AUDIT.md) for formulas, numeric tests and the sandbox
consumer contract. No component submits orders or connects to a broker.
