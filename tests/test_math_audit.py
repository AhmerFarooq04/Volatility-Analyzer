"""Independent numeric reference and pathological-input tests for sandbox use."""

import math
import statistics
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest
from earnings_calculator.options import OptionsAnalyzer


def reference_yang_zhang(frame, n=30, annual=252):
    # Independent scalar implementation: centered sample variances and RS arithmetic mean.
    tail = frame.iloc[-n:]
    previous = frame["Close"].shift(1).iloc[-n:]
    overnight = [math.log(o / p) for o, p in zip(tail.Open, previous)]
    intraday = [math.log(c / o) for c, o in zip(tail.Close, tail.Open)]
    rs = [
        math.log(h / o) * math.log(h / c) + math.log(l / o) * math.log(l / c)
        for o, h, l, c in zip(tail.Open, tail.High, tail.Low, tail.Close)
    ]
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    return math.sqrt(
        annual
        * (
            statistics.variance(overnight)
            + k * statistics.variance(intraday)
            + (1 - k) * statistics.mean(rs)
        )
    )


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("window", [5, 14, 30])
def test_yang_zhang_matches_independent_reference(seed, window):
    rng = np.random.default_rng(seed)
    close = np.exp(np.cumsum(rng.normal(0.001, 0.02, 100))) * 100
    opened = close * np.exp(rng.normal(0, 0.01, 100))
    frame = pd.DataFrame(
        {
            "Open": opened,
            "Close": close,
            "High": np.maximum(opened, close) * 1.01,
            "Low": np.minimum(opened, close) * 0.99,
        }
    )
    result = OptionsAnalyzer().yang_zhang_volatility(frame, window=window)
    assert result == pytest.approx(reference_yang_zhang(frame, window), rel=1e-12)


def test_constant_drift_is_not_random_volatility():
    close = 100 * np.exp(np.arange(80) * 0.01)
    opened = close / math.exp(0.01)
    frame = pd.DataFrame({"Open": opened, "Close": close, "High": close, "Low": opened})
    assert OptionsAnalyzer().yang_zhang_volatility(frame) == pytest.approx(0, abs=1e-12)


def test_yang_zhang_scale_invariance(ohlcv_dataframe):
    analyzer = OptionsAnalyzer()
    scaled = ohlcv_dataframe.copy()
    scaled[["Open", "High", "Low", "Close"]] *= 1000
    assert analyzer.yang_zhang_volatility(scaled) == pytest.approx(
        analyzer.yang_zhang_volatility(ohlcv_dataframe)
    )


def test_simple_volatility_is_sample_std_of_log_returns():
    closes = pd.DataFrame({"Close": np.exp([0, 0.01, -0.02, 0.03, 0.04])})
    expected = statistics.stdev([0.01, -0.03, 0.05, 0.01]) * math.sqrt(252)
    assert OptionsAnalyzer().calculate_simple_volatility(
        closes, window=4
    ) == pytest.approx(expected)


def test_atr_includes_gaps_and_is_simple_14_session_mean():
    frame = pd.DataFrame(
        {"High": [102, 111, 107], "Low": [98, 109, 104], "Close": [100, 110, 106]}
    )
    assert OptionsAnalyzer().compute_atr(frame, window=3) == pytest.approx(
        (4 + 11 + 6) / 3
    )


def recommendation_case(ohlcv_dataframe):
    analyzer = OptionsAnalyzer()
    ticker = MagicMock()
    today = datetime.today().date()
    dates = [(today + timedelta(days=d)).isoformat() for d in (15, 45)]
    ticker.options = dates
    ticker.history.return_value = pd.DataFrame({"Close": [100.0]})
    history = ohlcv_dataframe.copy()
    history["Close"] = 100.0
    history["Volume"] = 2_000_000

    def chain(exp):
        iv = 0.6 if exp == dates[0] else 0.3
        result = MagicMock()
        result.calls = pd.DataFrame(
            {
                "strike": [95, 100, 105],
                "bid": [4, 1.5, 0.1],
                "ask": [5, 2.5, 0.2],
                "impliedVolatility": [iv] * 3,
            }
        )
        result.puts = pd.DataFrame(
            {
                "strike": [95, 100, 105],
                "bid": [0.1, 1.5, 4],
                "ask": [0.2, 2.5, 5],
                "impliedVolatility": [iv] * 3,
            }
        )
        return result

    ticker.option_chain.side_effect = chain
    return analyzer, ticker, history, dates


def test_complete_recommendation_exact_known_numbers(ohlcv_dataframe):
    analyzer, ticker, history, dates = recommendation_case(ohlcv_dataframe)
    with (
        patch.object(analyzer, "get_ticker", return_value=ticker),
        patch.object(analyzer, "yang_zhang_volatility", return_value=0.2),
    ):
        result = analyzer.compute_recommendation("TEST", history)
    assert result["term_structure"] == pytest.approx(0.45)
    assert result["term_slope"] == pytest.approx(-0.01)
    assert result["iv30_rv30"] == pytest.approx(2.25)
    assert result["current_iv"] == pytest.approx(0.6)
    assert result["expected_move"] == "4.0%"
    assert result["avg_volume_value"] == 2_000_000
    assert result["iv_rank"] is None
    assert ticker.option_chain.call_count == 2
    ticker.history.assert_called_once_with(
        period="1d", auto_adjust=False, raise_errors=True
    )


@pytest.mark.parametrize("hv", [0, float("nan"), float("inf"), -0.2])
def test_bad_realized_volatility_cannot_generate_ratio(hv, ohlcv_dataframe):
    analyzer, ticker, history, _ = recommendation_case(ohlcv_dataframe)
    with (
        patch.object(analyzer, "get_ticker", return_value=ticker),
        patch.object(analyzer, "yang_zhang_volatility", return_value=hv),
    ):
        result = analyzer.compute_recommendation("TEST", history)
    assert "error" in result
    assert "iv30_rv30" not in result


@pytest.mark.parametrize("iv", [float("nan"), float("inf"), 0, -0.3])
def test_bad_chain_iv_is_rejected(iv, ohlcv_dataframe):
    analyzer, ticker, history, _ = recommendation_case(ohlcv_dataframe)
    chain = ticker.option_chain.side_effect(ticker.options[0])
    chain.calls["impliedVolatility"] = iv
    ticker.option_chain.side_effect = None
    ticker.option_chain.return_value = chain
    with patch.object(analyzer, "get_ticker", return_value=ticker):
        result = analyzer.compute_recommendation("TEST", history)
    assert "error" in result


def test_short_expiry_coverage_is_unavailable(ohlcv_dataframe):
    analyzer, ticker, history, dates = recommendation_case(ohlcv_dataframe)
    ticker.options = [dates[0]]
    with patch.object(analyzer, "get_ticker", return_value=ticker):
        assert "error" in analyzer.compute_recommendation("TEST", history)


def test_crossed_quotes_do_not_produce_expected_move(ohlcv_dataframe):
    analyzer, ticker, history, _ = recommendation_case(ohlcv_dataframe)
    get_chain = ticker.option_chain.side_effect

    def crossed(exp):
        chain = get_chain(exp)
        chain.calls["bid"] = 10
        return chain

    ticker.option_chain.side_effect = crossed
    with (
        patch.object(analyzer, "get_ticker", return_value=ticker),
        patch.object(analyzer, "yang_zhang_volatility", return_value=0.2),
    ):
        result = analyzer.compute_recommendation("TEST", history)
    assert result["expected_move"] == "N/A"


def test_volume_needs_full_30_sessions(ohlcv_dataframe):
    analyzer, ticker, history, _ = recommendation_case(ohlcv_dataframe)
    with (
        patch.object(analyzer, "get_ticker", return_value=ticker),
        patch.object(analyzer, "yang_zhang_volatility", return_value=0.2),
    ):
        assert "error" in analyzer.compute_recommendation("TEST", history.iloc[-29:])


def test_expected_move_uses_current_spot_not_cached_close(ohlcv_dataframe):
    analyzer, ticker, history, _ = recommendation_case(ohlcv_dataframe)
    history["Close"] = 95  # Yesterday's close differs from today's latest price of 100.
    with (
        patch.object(analyzer, "get_ticker", return_value=ticker),
        patch.object(analyzer, "yang_zhang_volatility", return_value=0.2),
    ):
        result = analyzer.compute_recommendation("TEST", history)
    assert result["underlying_price"] == 100
    assert result["expected_move"] == "4.0%"
