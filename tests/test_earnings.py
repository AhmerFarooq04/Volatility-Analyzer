"""Calendar provider contract and failure handling."""
from unittest.mock import MagicMock, patch
import pytest
from earnings_calculator.calendar import EarningsCalendarFetcher, EarningsCalendarError


def session_for(rows):
    session = MagicMock()
    session.get.return_value.json.return_value = {"data": {"rows": rows}}
    return session


def test_timing_and_date_isolation():
    fetcher = EarningsCalendarFetcher()
    session = session_for([
        {"symbol": "AAPL", "time": "time-after-hours"},
        {"symbol": "MSFT", "time": "time-pre-market"},
        {"symbol": "TSLA", "time": "time-not-supplied"},
    ])
    with patch.object(fetcher.session_manager, "get_session", return_value=session):
        assert fetcher.fetch_earnings_data("2026-10-08") == ["AAPL", "MSFT", "TSLA"]
        session.get.return_value.json.return_value = {"data": {"rows": []}}
        assert fetcher.fetch_earnings_data("2026-10-09") == []
    assert fetcher.get_earnings_time("AAPL", "2026-10-08") == "Post Market"
    assert fetcher.get_earnings_time("MSFT", "2026-10-08") == "Pre Market"
    assert fetcher.get_earnings_time("TSLA", "2026-10-08") == "Unknown"
    assert fetcher.get_earnings_time("AAPL", "2026-10-09") == "Unknown"
    assert session.get.call_args.kwargs["timeout"] == 20


@pytest.mark.parametrize("rows", [[], None])
def test_empty_calendar(rows):
    fetcher = EarningsCalendarFetcher()
    with patch.object(fetcher.session_manager, "get_session", return_value=session_for(rows)):
        assert fetcher.fetch_earnings_data("2026-10-08") == []


def test_provider_failure_is_not_empty_calendar():
    fetcher = EarningsCalendarFetcher()
    session = MagicMock()
    session.get.side_effect = RuntimeError("HTTP 403")
    with patch.object(fetcher.session_manager, "get_session", return_value=session):
        with pytest.raises(EarningsCalendarError, match="HTTP 403"):
            fetcher.fetch_earnings_data("2026-10-08")
    assert session.get.call_count == 2


def test_invalid_payload_is_failure():
    fetcher = EarningsCalendarFetcher()
    session = session_for([])
    session.get.return_value.json.return_value = {"data": None}
    with patch.object(fetcher.session_manager, "get_session", return_value=session):
        with pytest.raises(EarningsCalendarError):
            fetcher.fetch_earnings_data("2026-10-08")
