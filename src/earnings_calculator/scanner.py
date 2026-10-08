"""Earnings scanning orchestration and OTC ticker updater."""

import concurrent.futures
import os
import tempfile
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf

from earnings_calculator.calendar import EarningsCalendarFetcher
from earnings_calculator.logging_config import create_logger
from earnings_calculator.options import OptionsAnalyzer, MIN_AVG_VOLUME, IV_INTERPOLATION_DTE

MIN_IV30_RV30_RATIO = 1.25
MAX_TERM_SLOPE = -0.00406


def update_otc_tickers():
    """Download OTC tickers from StockAnalysis API and write to otc-tickers.txt."""
    base_url = "https://api.stockanalysis.com/api/screener/a/f"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) "
        "Gecko/20100101 Firefox/135.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://stockanalysis.com/",
        "Origin": "https://stockanalysis.com",
    }
    params = {
        "m": "marketCap",
        "s": "desc",
        "c": "no,s,n,marketCap,price,change,revenue",
        "cn": "1000",
        "f": "exchangeCode-is-OTC,subtype-is-stock",
        "i": "symbols",
    }
    all_tickers = []
    page = 1

    try:
        while True:
            params["p"] = page
            # Added timeout to prevent thread hanging
            response = requests.get(base_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            page_data = data.get("data", {}).get("data", [])

            if not page_data:
                break

            for item in page_data:
                full_symbol = item.get("s", "")
                ticker = full_symbol.split("/")[-1] if "/" in full_symbol else full_symbol
                all_tickers.append(ticker)

            print(f"Processed page {page}")
            page += 1

        # Only overwrite the file if we actually successfully fetched data
        if all_tickers:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", dir=".", delete=False) as tmp:
                for ticker in all_tickers:
                    tmp.write(f"{ticker}\n")
                tmp_path = tmp.name
            os.replace(tmp_path, "otc-tickers.txt")
            print("Total OTC tickers count:", len(all_tickers))
            print("OTC tickers have been written to otc-tickers.txt")
        else:
            print("Warning: API returned no OTC tickers. Keeping existing otc-tickers.txt if it exists.")

    except requests.exceptions.RequestException as e:
        print(f"Network error updating OTC tickers (API may have changed): {e}")
        print("Skipping OTC update. The app will continue using cached otc-tickers.txt if available.")
    except Exception as e:
        print(f"Unexpected error updating OTC tickers: {e}")
        print("Skipping OTC update. The app will continue using cached otc-tickers.txt if available.")


class EnhancedEarningsScanner:
    def __init__(self, analyzer: OptionsAnalyzer):
        self.analyzer = analyzer
        self.calendar_fetcher = EarningsCalendarFetcher(self.analyzer.proxy_manager)
        self.batch_size = 10
        self.logger = create_logger(
            "EnhancedEarningsScanner", "earnings_scanner_debug.log"
        )

    def batch_download_history(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        ticker_str = " ".join(tickers)
        try:
            data = yf.download(
                tickers=ticker_str,
                period="1y",
                group_by="ticker",
                auto_adjust=True,
                prepost=True,
                threads=True,
                progress=False,
            )
            res = {}
            for tk in tickers:
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        df = data.xs(tk, axis=1, level=0)
                    else:
                        df = data
                    df = df.dropna(subset=["Close", "Open", "High", "Low"])
                    if not df.empty:
                        res[tk] = df
                except Exception as e:
                    self.logger.debug(f"Could not extract data for {tk}: {e}")
                    continue
            return res
        except Exception as e:
            self.logger.error(f"batch download error: {e}")
            return {}

    def scan_earnings_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        progress_callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """Scan earnings across a range of business days.

        Loops over each business day from *start_date* to *end_date*
        (inclusive), calls ``scan_earnings_stocks`` per day, injects an
        ``earnings_date`` key, and aggregates all results.
        """
        dates = pd.bdate_range(start_date, end_date)
        if dates.empty:
            return []
        all_results: List[Dict] = []
        n_dates = len(dates)
        for idx, day in enumerate(dates):
            day_dt = day.to_pydatetime()
            day_str = day_dt.strftime("%Y-%m-%d")

            def day_progress(val, _idx=idx):
                if progress_callback:
                    base = _idx / n_dates * 100
                    progress_callback(base + val / n_dates)

            results = self.scan_earnings_stocks(day_dt, day_progress)
            for r in results:
                r["earnings_date"] = day_str
            all_results.extend(results)
        if progress_callback:
            progress_callback(100)
        return all_results

    def scan_overnight_earnings(self, date: datetime, progress_callback=None):
        """Analyze tonight's releases and the following calendar morning's releases."""
        results = []
        for idx, (day, timing) in enumerate([
            (date, "Post Market"), (date + timedelta(days=1), "Pre Market")
        ]):
            def progress(value, offset=idx):
                if progress_callback:
                    progress_callback(offset * 50 + value / 2)
            results.extend(self.scan_earnings_stocks(day, progress, timing))
        return results

    def scan_earnings_stocks(self, date: datetime, progress_callback=None,
                             earnings_time=None) -> List[Dict]:
        """Use fresh history to filter liquidity before requesting options data."""
        ds = date.strftime("%Y-%m-%d")
        tickers = self.calendar_fetcher.fetch_earnings_data(ds)
        timings = {tk: self.calendar_fetcher.get_earnings_time(tk, ds) for tk in tickers}
        try:
            with open("otc-tickers.txt") as stream:
                otc = {line.strip().upper() for line in stream}
        except FileNotFoundError:
            otc = set()
        tickers = [tk for tk in tickers if tk not in otc and
                   (earnings_time is None or timings[tk] == earnings_time)]
        results = []
        done = 0
        for offset in range(0, len(tickers), self.batch_size):
            batch = tickers[offset:offset + self.batch_size]
            histories = self.batch_download_history(batch)
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = {}
                for ticker in batch:
                    history = histories.get(ticker)
                    if history is None or history.empty:
                        try:
                            history = self.analyzer.get_ticker(ticker).history(period="1y")
                        except Exception:
                            self.logger.exception("Could not retrieve history for %s", ticker)
                            history = None
                    volume = (history["Volume"].rolling(IV_INTERPOLATION_DTE).mean().iloc[-1]
                              if history is not None and not history.empty and
                              "Volume" in history else float("nan"))
                    if pd.notna(volume) and volume >= MIN_AVG_VOLUME:
                        futures[executor.submit(self.analyze_stock, ticker, history,
                                                earnings_date=ds,
                                                earnings_time=timings[ticker])] = ticker
                    else:
                        done += 1
                        self.logger.info("Skipping %s: insufficient 30-session volume", ticker)
                        if progress_callback:
                            progress_callback(done / len(tickers) * 100)
                for future in concurrent.futures.as_completed(futures):
                    done += 1
                    try:
                        result = future.result()
                        if result:
                            results.append(result)
                    except Exception:
                        self.logger.exception("Analysis failed for %s", futures[future])
                    if progress_callback:
                        progress_callback(done / len(tickers) * 100)
        results.sort(key=lambda r: (r["recommendation"] != "Recommended", r["ticker"]))
        if progress_callback:
            progress_callback(100)
        return results

    def analyze_stock(
        self,
        ticker: str,
        history_data: Optional[pd.DataFrame] = None,
        skip_otc_check: bool = False,
        earnings_date: Optional[str] = None,
        earnings_time: Optional[str] = None,
    ) -> Optional[Dict]:
        try:
            st2 = self.analyzer.get_ticker(ticker)
            if not skip_otc_check:
                exchange = st2.info.get("exchange", "")
                otc_exchanges = {"PNK", "Other OTC", "OTC", "GREY"}
                if exchange in otc_exchanges:
                    self.logger.info(
                        f"[SKIP] Ticker '{ticker}' is OTC (exchange='{exchange}')."
                    )
                    return None
            if history_data is None or history_data.empty:
                hd = st2.history(period="1y")
                if hd.empty:
                    hd = st2.history(period="1mo")
                if hd.empty:
                    self.logger.warning(f"No data for {ticker}; skipping.")
                    return None
                history_data = hd.dropna(subset=["Close", "Open", "High", "Low"])
                if history_data.empty:
                    self.logger.warning(f"No valid data after dropna for {ticker}; skipping.")
                    return None

            if isinstance(history_data.columns, pd.MultiIndex):
                history_data = history_data.copy()
                for level in range(history_data.columns.nlevels):
                    if "Close" in history_data.columns.get_level_values(level):
                        history_data.columns = history_data.columns.get_level_values(level)
                        break
            if "Close" in history_data.columns:
                cp = history_data["Close"].iloc[-1]
            elif "Adj Close" in history_data.columns:
                cp = history_data["Adj Close"].iloc[-1]
            else:
                raise ValueError("No close price data available.")
            voldata = history_data["Volume"]
            hv = self.analyzer.yang_zhang_volatility(history_data)
            tv = voldata.iloc[-1] if not voldata.empty else 0
            od = self.analyzer.compute_recommendation(ticker, history_data=history_data)
            if isinstance(od, dict) and "error" not in od:
                avb = od["avg_volume"]
                ivcheck = od["iv30_rv30"] >= MIN_IV30_RV30_RATIO
                slopecheck = od["term_slope"] <= MAX_TERM_SLOPE
                if avb and ivcheck and slopecheck:
                    rec = "Recommended"
                elif slopecheck and ((avb and not ivcheck) or (ivcheck and not avb)):
                    rec = "Consider"
                else:
                    rec = "Avoid"
                edate = earnings_date or "N/A"
                try:
                    cal = st2.calendar if not earnings_date else None
                    if not earnings_date and cal and "Earnings Date" in cal and cal["Earnings Date"]:
                        edate = cal["Earnings Date"][0].strftime("%Y-%m-%d")
                except Exception:
                    pass

                etime = earnings_time or self.calendar_fetcher.get_earnings_time(ticker)
                if earnings_time is None and etime == "Unknown" and edate != "N/A":
                    self.calendar_fetcher.fetch_earnings_data(edate)
                    etime = earnings_time or self.calendar_fetcher.get_earnings_time(ticker)

                return {
                    "ticker": ticker,
                    "earnings_date": edate,
                    "current_price": cp,
                    "market_cap": st2.info.get("marketCap", 0),
                    "volume": tv,
                    "avg_volume": avb,
                    "avg_volume_value": od.get("avg_volume_value", 0),
                    "earnings_time": etime,
                    "recommendation": rec,
                    "expected_move": od.get("expected_move", "N/A"),
                    "atr14": od.get("atr14", 0),
                    "atr14_pct": od.get("atr14_pct", 0),
                    "iv30_rv30": od.get("iv30_rv30", 0),
                    "term_slope": od.get("term_slope", 0),
                    "term_structure": od.get("term_structure", 0),
                    "historical_volatility": hv,
                    "current_iv": od.get("current_iv", None),
                    "iv_rank": od.get("iv_rank", None),
                }
            return {
                "ticker": ticker,
                "earnings_date": earnings_date or "N/A",
                "current_price": cp,
                "market_cap": 0,
                "volume": tv,
                "avg_volume": bool(voldata.rolling(IV_INTERPOLATION_DTE).mean().iloc[-1] >= MIN_AVG_VOLUME),
                "avg_volume_value": voldata.rolling(IV_INTERPOLATION_DTE).mean().iloc[-1],
                "analysis_error": od.get("error", "Options analysis unavailable") if isinstance(od, dict) else str(od),
                "earnings_time": earnings_time or self.calendar_fetcher.get_earnings_time(ticker),
                "recommendation": "Avoid",
                "expected_move": "N/A",
                "atr14": 0,
                "atr14_pct": 0,
                "iv30_rv30": 0,
                "term_slope": 0,
                "term_structure": 0,
                "historical_volatility": hv,
                "current_iv": None,
                "iv_rank": None,
            }
        except Exception as e:
            self.logger.error(f"Analyze error for {ticker}: {e}", exc_info=True)
            return None
