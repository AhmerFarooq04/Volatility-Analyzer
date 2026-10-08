"""Options analysis: volatility calculations and recommendation engine."""

import warnings
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd
import yfinance as yf

from earnings_calculator.logging_config import create_logger
from earnings_calculator.market_data import (
    yahoo_ticker,
    price_history,
    stop_on_rate_limit,
)
from yfinance.exceptions import YFRateLimitError

FILTER_MAX_DTE = 45
IV_INTERPOLATION_DTE = 30
MIN_AVG_VOLUME = 1_500_000


class OptionsAnalyzer:
    def __init__(self):
        self.warnings_shown = False
        self.logger = create_logger("OptionsAnalyzer", "options_analyzer_debug.log")

    def safe_log(self, val: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.log(val)

    def safe_sqrt(self, val: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore"):
            return np.sqrt(val)

    def get_ticker(self, symbol: str) -> yf.Ticker:
        return yahoo_ticker(symbol)

    def filter_dates(self, dates: List[str]) -> List[str]:
        today = datetime.today().date()
        cutoff = today + timedelta(days=FILTER_MAX_DTE)
        sdates = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in dates})
        # Filter out today's date (0-DTE) before processing
        filtered = [d for d in sdates if d > today]
        if not filtered:
            return []
        arr = []
        for i, d in enumerate(filtered):
            if d >= cutoff:
                arr = [x.strftime("%Y-%m-%d") for x in filtered[: i + 1]]
                break
        if arr:
            return arr
        else:
            return [x.strftime("%Y-%m-%d") for x in filtered]

    def yang_zhang_volatility(
        self,
        pdf: pd.DataFrame,
        window=30,
        trading_periods=252,
        return_last_only=True,
    ):
        try:
            log_ho = self.safe_log(pdf["High"] / pdf["Open"])
            log_lo = self.safe_log(pdf["Low"] / pdf["Open"])
            log_co = self.safe_log(pdf["Close"] / pdf["Open"])
            log_oc = self.safe_log(pdf["Open"] / pdf["Close"].shift(1))
            if window < 2 or trading_periods <= 0:
                raise ValueError("Invalid volatility window or annualization")
            if (
                not np.isfinite(pdf[["Open", "High", "Low", "Close"]]).all().all()
                or (pdf[["Open", "High", "Low", "Close"]] <= 0).any().any()
            ):
                raise ValueError("OHLC must be finite and positive")
            rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
            close_vol = log_co.rolling(window=window).var(ddof=1)
            open_vol = log_oc.rolling(window=window).var(ddof=1)
            rs_ = rs.rolling(window=window).mean()
            k = 0.34 / (1.34 + (window + 1) / (window - 1))
            out = self.safe_sqrt(
                open_vol + k * close_vol + (1 - k) * rs_
            ) * self.safe_sqrt(trading_periods)
            if return_last_only:
                return out.iloc[-1]
            else:
                return out.dropna()
        except Exception as e:
            if not self.warnings_shown:
                warnings.warn(f"Error in Yang-Zhang: {e}")
                self.warnings_shown = True
            return self.calculate_simple_volatility(
                pdf, window, trading_periods, return_last_only
            )

    def calculate_simple_volatility(
        self,
        pdf: pd.DataFrame,
        window=30,
        trading_periods=252,
        return_last_only=True,
    ):
        try:
            rets = np.log(pdf["Close"] / pdf["Close"].shift(1)).dropna()
            vol = rets.rolling(window=window).std() * np.sqrt(trading_periods)
            if return_last_only:
                return vol.iloc[-1]
            return vol
        except Exception as e:
            warnings.warn(f"Error in fallback volatility: {e}")
            return np.nan

    def compute_atr(self, pdf: pd.DataFrame, window=14):
        """Compute Average True Range over the given window."""
        high = pdf["High"]
        low = pdf["Low"]
        close = pdf["Close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr = tr.rolling(window=window, min_periods=window).mean()
        return atr.iloc[-1] if not atr.empty else np.nan

    def build_term_structure(self, days: List[int], ivs: List[float]) -> callable:
        try:
            from scipy.interpolate import interp1d

            da = np.array(days)
            va = np.array(ivs)
            idx = da.argsort()
            da, va = da[idx], va[idx]
            if (
                len(da) == 0
                or len(da) != len(va)
                or not np.isfinite(va).all()
                or (va <= 0).any()
                or len(set(da)) != len(da)
            ):
                raise ValueError("Invalid term structure points")
            if len(da) == 1:
                return lambda dte: float(va[0])
            f = interp1d(da, va, kind="linear", bounds_error=True)

            def tspline(dte):
                if dte < da[0]:
                    return float(va[0])
                elif dte > da[-1]:
                    return float(va[-1])
                else:
                    return float(f(dte))

            return tspline
        except Exception as e:
            warnings.warn(f"Error building term structure: {e}")
            return lambda x: np.nan

    def get_current_price(self, ticker: yf.Ticker):
        for attempt in range(3):
            try:
                td = ticker.history(period="1d", auto_adjust=False, raise_errors=True)
                if td.empty:
                    raise ValueError("No price data for 1d.")
                if "Close" in td.columns:
                    return td["Close"].iloc[-1]
                elif "Adj Close" in td.columns:
                    return td["Adj Close"].iloc[-1]
                else:
                    raise ValueError("No Close or Adj Close data found.")
            except YFRateLimitError as exc:
                stop_on_rate_limit(exc)
            except Exception as e:
                if attempt < 2:
                    self.logger.warning(f"Failed to get price: {e}. Retrying.")
                else:
                    raise ValueError(f"Cannot get price: {e}")

    def compute_recommendation(
        self, symbol: str, history_data: pd.DataFrame = None
    ) -> Dict:
        try:
            s = symbol.strip().upper()
            if not s:
                return {"error": "No symbol provided."}
            t = self.get_ticker(s)
            exps = list(t.options)
            if not exps:
                return {"error": f"No options for {s}."}
            exps = self.filter_dates(exps)
            # Only request knots needed for the front IV, IV30 and the 45-day endpoint.
            today = datetime.today().date()
            chosen = {exps[0]} if exps else set()
            for target in (IV_INTERPOLATION_DTE, FILTER_MAX_DTE):
                before = [
                    exp
                    for exp in exps
                    if (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
                    <= target
                ]
                after = [
                    exp
                    for exp in exps
                    if (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
                    >= target
                ]
                if before:
                    chosen.add(before[-1])
                if after:
                    chosen.add(after[0])
            exps = sorted(chosen)
            oc = {}
            for e in exps:
                try:
                    oc[e] = t.option_chain(e)
                except YFRateLimitError as exc:
                    stop_on_rate_limit(exc)
                except Exception as ex_:
                    self.logger.warning(f"Couldn't get chain {e} for {s}: {ex_}")
            if history_data is not None and not history_data.empty:
                h3 = history_data.dropna(subset=["Close", "Open", "High", "Low"])
            else:
                h3 = price_history(s, ticker=t).dropna(
                    subset=["Close", "Open", "High", "Low"]
                )
            # Extract current price from history to avoid a redundant API call
            if h3.empty:
                return {"error": "No valid history data."}
            # ATM and expected move use the latest price; realized vol uses completed bars.
            up = float(self.get_current_price(t))
            if not np.isfinite(up) or up <= 0:
                return {"error": "Invalid underlying price."}
            atm_ivs = {}
            stprice = None
            fi_iv = None
            i = 0
            for e, chain in oc.items():
                calls, puts = chain.calls, chain.puts
                if calls.empty or puts.empty:
                    continue
                common = sorted(set(calls["strike"]) & set(puts["strike"]))
                if not common:
                    continue
                strike = min(common, key=lambda value: abs(value - up))
                call_idx = calls.index[calls["strike"] == strike][0]
                put_idx = puts.index[puts["strike"] == strike][0]
                civ = calls.loc[call_idx, "impliedVolatility"]
                piv = puts.loc[put_idx, "impliedVolatility"]
                if not np.isfinite([civ, piv]).all() or min(civ, piv) <= 0:
                    continue
                av = (civ + piv) / 2
                atm_ivs[e] = av
                if i == 0:
                    cbid = calls.loc[call_idx, "bid"]
                    cask = calls.loc[call_idx, "ask"]
                    pbid = puts.loc[put_idx, "bid"]
                    pask = puts.loc[put_idx, "ask"]
                    quotes = [cbid, cask, pbid, pask]
                    if (
                        np.isfinite(quotes).all()
                        and min(quotes) > 0
                        and cbid <= cask
                        and pbid <= pask
                    ):
                        stprice = (cbid + cask + pbid + pask) / 2
                i += 1
            if atm_ivs:
                sorted_exps = sorted(atm_ivs.keys())
                fi_iv = atm_ivs[sorted_exps[0]]
            if not atm_ivs:
                return {"error": "No ATM IV found."}
            today = datetime.today().date()
            ds, vs = [], []
            for exp_, iv_ in atm_ivs.items():
                dtobj = datetime.strptime(exp_, "%Y-%m-%d").date()
                dd = (dtobj - today).days
                ds.append(dd)
                vs.append(iv_)
            if (
                min(ds) > IV_INTERPOLATION_DTE
                or max(ds) < FILTER_MAX_DTE
                or len(ds) < 2
            ):
                return {
                    "error": "Insufficient expirations to cover IV30 and 45-day slope."
                }
            spline = self.build_term_structure(ds, vs)
            iv30 = spline(IV_INTERPOLATION_DTE)
            d0 = min(ds)
            if d0 == FILTER_MAX_DTE:
                slope = 0
            else:
                dden = (FILTER_MAX_DTE - d0) if (FILTER_MAX_DTE - d0) != 0 else 1
                slope = (spline(FILTER_MAX_DTE) - spline(d0)) / dden
            hv = self.yang_zhang_volatility(h3)
            # Historical implied volatility is required for a true IV Rank.
            iv_rank = None
            if not np.isfinite(hv) or hv <= 0:
                return {"error": "Realized volatility unavailable or zero."}
            iv30_rv30 = iv30 / hv
            avgv = h3["Volume"].rolling(IV_INTERPOLATION_DTE).mean().iloc[-1]
            if not np.isfinite(avgv):
                return {"error": "Insufficient 30-session volume history."}
            if not np.isfinite(up) or up <= 0:
                return {"error": "Invalid underlying price."}
            if stprice and up != 0:
                exmo = f"{round(stprice / up * 100, 2)}%"
            else:
                exmo = "N/A"
            atr14 = self.compute_atr(h3, window=14) if not h3.empty else 0
            atr14_pct = (atr14 / up) * 100 if up else 0
            return {
                "avg_volume": bool(avgv >= MIN_AVG_VOLUME),
                "avg_volume_value": float(avgv),
                "iv30_rv30": float(iv30_rv30),
                "term_slope": float(slope),
                "term_structure": float(iv30),
                "expected_move": exmo,
                "underlying_price": float(up),
                "historical_volatility": float(hv),
                "current_iv": float(fi_iv),
                "atr14": float(atr14),
                "atr14_pct": float(atr14_pct),
                "iv_rank": iv_rank,
            }
        except YFRateLimitError as exc:
            stop_on_rate_limit(exc)
        except Exception as exc:
            self.logger.warning("Analysis unavailable for %s: %s", symbol, exc)
            return {"error": str(exc)}
