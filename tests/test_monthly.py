"""Monthly persistence, scheduling and failure safety, with offline providers."""

import csv
import json
from datetime import date
from unittest.mock import MagicMock
import pytest
from earnings_calculator.monthly import MonthlyEarningsCache, analysis_window
from earnings_calculator.market_data import DataRequestPaused


def cache(tmp_path, history):
    provider = MagicMock()
    provider.fetch_earnings_data.side_effect = lambda day: (
        ["PASS", "LOW", "UNKNOWN"] if day == "2026-10-09" else []
    )
    provider.get_earnings_time.side_effect = lambda ticker, day: (
        "Unknown" if ticker == "UNKNOWN" else "Pre Market"
    )
    high = history.copy()
    high["Volume"] = 1_500_000
    low = history.copy()
    low["Volume"] = 1_499_999
    loader = MagicMock(side_effect=lambda ticker: low if ticker == "LOW" else high)
    result = MonthlyEarningsCache(
        tmp_path, provider, loader, today=lambda: date(2026, 10, 8), calendar_delay=0
    )
    return result, provider, loader


def test_complete_csv_filters_and_reuses(tmp_path, ohlcv_dataframe):
    monthly, provider, loader = cache(tmp_path, ohlcv_dataframe)
    path = monthly.ensure_current(progress=lambda msg: None)
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 3
    assert {row["ticker"] for row in monthly.events_for_date("2026-10-09")} == {
        "PASS",
        "UNKNOWN",
    }
    ready = [row for row in rows if row["status"] == "ready"]
    assert ready[0]["ticker"] == "PASS"
    assert ready[0]["analysis_date"] == "2026-10-08"
    assert "15:30:00" in ready[0]["run_after_et"]
    monthly.ensure_current(progress=lambda msg: None)
    assert provider.fetch_earnings_data.call_count == 33
    assert loader.call_count == 3
    assert monthly.events_for_date("2026-10-10") == []
    assert monthly.events_for_date("2026-11-09") is None


def test_partial_jobs_resume_without_duplicate_requests(tmp_path, ohlcv_dataframe):
    monthly, provider, loader = cache(tmp_path, ohlcv_dataframe)
    with pytest.raises(RuntimeError, match="incomplete"):
        monthly.ensure_current(max_symbols=1, progress=lambda msg: None)
    assert monthly.events_for_date("2026-10-09") is None
    monthly.ensure_current(max_symbols=10, progress=lambda msg: None)
    assert loader.call_count == 3
    assert provider.fetch_earnings_data.call_count == 33


def test_rate_limit_saves_checkpoint_and_stops(tmp_path, ohlcv_dataframe):
    monthly, _, loader = cache(tmp_path, ohlcv_dataframe)
    loader.side_effect = DataRequestPaused("paused", 123)
    with pytest.raises(DataRequestPaused):
        monthly.ensure_current(progress=lambda msg: None)
    assert loader.call_count == 1
    assert monthly.checkpoint.exists()
    assert monthly.events_for_date("2026-10-09") is None


def test_calendar_failure_preserves_old_csv(tmp_path, ohlcv_dataframe):
    monthly, provider, _ = cache(tmp_path, ohlcv_dataframe)
    monthly.ensure_current(progress=lambda msg: None)
    original = monthly.output.read_bytes()
    monthly.today = lambda: date(2026, 11, 1)
    provider.fetch_earnings_data.side_effect = RuntimeError("calendar unavailable")
    with pytest.raises(RuntimeError):
        monthly.ensure_current(progress=lambda msg: None)
    assert monthly.output.read_bytes() == original
    assert monthly.events_for_date("2026-11-01") is None


def test_new_month_replaces_old_after_success(tmp_path, ohlcv_dataframe):
    monthly, provider, _ = cache(tmp_path, ohlcv_dataframe)
    monthly.ensure_current(progress=lambda msg: None)
    monthly.today = lambda: date(2026, 11, 1)
    provider.fetch_earnings_data.side_effect = lambda day: []
    monthly.ensure_current(progress=lambda msg: None)
    assert json.loads(monthly.meta.read_text())["month"] == "2026-11"
    assert list(csv.DictReader(monthly.output.open())) == []


@pytest.mark.parametrize(
    "release,timing,expected",
    [
        (date(2026, 10, 12), "Pre Market", "2026-10-09"),
        (date(2026, 7, 6), "Pre Market", "2026-07-02"),
        (date(2026, 10, 8), "Post Market", "2026-10-08"),
        (date(2026, 10, 8), "Unknown", ""),
    ],
)
def test_analysis_dates_respect_weekends_and_holidays(release, timing, expected):
    assert analysis_window(release, timing)[0] == expected


def test_early_close_window():
    day, start, end = analysis_window(date(2026, 11, 27), "Post Market")
    assert day == "2026-11-27"
    assert "12:30:00" in start
    assert "13:00:00" in end


def test_tampered_csv_not_used(tmp_path, ohlcv_dataframe):
    monthly, _, _ = cache(tmp_path, ohlcv_dataframe)
    monthly.ensure_current(progress=lambda msg: None)
    monthly.output.write_text("bad CSV")
    assert monthly.events_for_date("2026-10-09") is None


def test_explicit_refresh_resumes_without_discarding_previous_csv(
    tmp_path, ohlcv_dataframe
):
    monthly, provider, loader = cache(tmp_path, ohlcv_dataframe)
    monthly.ensure_current(progress=lambda msg: None)
    previous = monthly.output.read_bytes()
    with pytest.raises(RuntimeError, match="incomplete"):
        monthly.ensure_current(max_symbols=1, force=True, progress=lambda msg: None)
    assert monthly.output.read_bytes() == previous
    # No --refresh on the next call: it must resume the pending refresh, not return the old CSV.
    monthly.ensure_current(max_symbols=10, progress=lambda msg: None)
    assert loader.call_count == 6
    assert provider.fetch_earnings_data.call_count == 66
    assert json.loads(monthly.checkpoint.read_text())["refreshing"] is False
