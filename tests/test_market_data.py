"""Offline tests of pacing, cross-process quotas and circuit breaking."""

from unittest.mock import MagicMock, patch, PropertyMock
import pytest
from yfinance.exceptions import YFRateLimitError
from earnings_calculator.market_data import (
    RequestBudget,
    PacedYahooSession,
    DataRequestPaused,
)
from earnings_calculator.options import OptionsAnalyzer


class FakeClock:
    def __init__(self):
        self.now = 100000.0
        self.waits = []

    def time(self):
        return self.now

    def sleep(self, duration):
        self.waits.append(duration)
        self.now += duration


def budget(tmp_path, clock, **kwargs):
    return RequestBudget(
        tmp_path / "budget.sqlite3", clock=clock.time, sleep=clock.sleep, **kwargs
    )


def test_pacing_and_persistence(tmp_path):
    clock = FakeClock()
    first = budget(tmp_path, clock, interval=3)
    first.reserve()
    second = budget(tmp_path, clock, interval=3)
    second.reserve()
    assert clock.waits == [3]


def test_hourly_budget_stops_before_next_request(tmp_path):
    clock = FakeClock()
    gate = budget(tmp_path, clock, interval=0, hourly=2, daily=10)
    gate.reserve()
    gate.reserve()
    with pytest.raises(DataRequestPaused, match="budget"):
        gate.reserve()
    clock.now += 3600
    gate.reserve()


def test_daily_budget_survives_hour_rollover(tmp_path):
    clock = FakeClock()
    gate = budget(tmp_path, clock, interval=0, hourly=10, daily=2)
    gate.reserve()
    gate.reserve()
    clock.now += 3601
    with pytest.raises(DataRequestPaused):
        budget(tmp_path, clock, interval=0, daily=2).reserve()
    clock.now += 86400
    gate.reserve()


def test_429_stops_session_and_other_processes(tmp_path):
    clock = FakeClock()
    gate = budget(tmp_path, clock, interval=0)
    session = PacedYahooSession(gate)
    response = MagicMock(status_code=429, headers={"Retry-After": "7200"})
    with patch("curl_cffi.requests.Session.request", return_value=response) as request:
        with pytest.raises(DataRequestPaused):
            session.get("https://query2.finance.yahoo.com/v7/finance/options/TEST")
        with pytest.raises(DataRequestPaused):
            session.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
        assert request.call_count == 1
    with pytest.raises(DataRequestPaused):
        budget(tmp_path, clock).reserve()
    clock.now += 7200
    gate.reserve()


def test_options_rate_limit_is_not_retried():
    analyzer = OptionsAnalyzer()
    ticker = MagicMock()
    with (
        patch.object(
            type(ticker), "options", new_callable=PropertyMock, create=True
        ) as options,
        patch.object(analyzer, "get_ticker", return_value=ticker),
        patch(
            "earnings_calculator.options.stop_on_rate_limit",
            side_effect=DataRequestPaused("paused", 123),
        ) as stop,
    ):
        options.side_effect = YFRateLimitError()
        with pytest.raises(DataRequestPaused):
            analyzer.compute_recommendation("TEST")
        assert options.call_count == 1
        stop.assert_called_once()


def test_history_cache_drops_partial_today(tmp_path):
    import pandas as pd
    from earnings_calculator.market_data import price_history
    from earnings_calculator.monthly import eastern_today

    today = pd.Timestamp(eastern_today())
    ticker = MagicMock()
    ticker.history.return_value = pd.DataFrame(
        {"Close": [100, 101]}, index=[today - pd.Timedelta(days=1), today]
    )
    with patch("earnings_calculator.market_data.DATA_DIR", tmp_path):
        first = price_history("TEST", ticker=ticker)
        second = price_history("TEST", ticker=ticker)
    assert len(first) == len(second) == 1
    ticker.history.assert_called_once()
    assert ticker.history.call_args.kwargs["raise_errors"] is True


def test_concurrent_callers_cannot_overrun_shared_budget(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    clock = FakeClock()
    gate = budget(tmp_path, clock, interval=0, hourly=2, daily=10)

    def attempt(_):
        try:
            gate.reserve()
            return True
        except DataRequestPaused:
            return False

    with ThreadPoolExecutor(max_workers=5) as executor:
        assert sum(executor.map(attempt, range(10))) == 2
