"""Fetch US earnings release dates and market sessions from Nasdaq."""

from datetime import datetime
from earnings_calculator.logging_config import create_logger
from earnings_calculator.proxy import ProxyManager
from earnings_calculator.sessions import SessionManager


class EarningsCalendarError(RuntimeError):
    """The calendar could not be retrieved; this is not an empty calendar."""


class EarningsCalendarFetcher:
    def __init__(self, proxy_manager=None):
        self.earnings_times = {}
        self.date_times = {}
        self.proxy_manager = proxy_manager or ProxyManager()
        self.session_manager = SessionManager(self.proxy_manager)
        self.logger = create_logger("EarningsCalendarFetcher", "earnings_calendar_debug.log")

    def fetch_earnings_data(self, date: str):
        datetime.strptime(date, "%Y-%m-%d")
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/market-activity/earnings",
        }
        for attempt in range(2):
            try:
                response = self.session_manager.get_session().get(
                    "https://api.nasdaq.com/api/calendar/earnings",
                    params={"date": date}, headers=headers, timeout=20,
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data")
                if not isinstance(data, dict) or "rows" not in data:
                    raise ValueError("Unexpected Nasdaq calendar response")
                rows = data["rows"]
                if rows is not None and not isinstance(rows, list):
                    raise ValueError("Invalid calendar rows")
                timings = {}
                for row in rows or []:
                    ticker = (row.get("symbol") or "").strip().upper()
                    if not ticker:
                        continue
                    timings[ticker] = {
                        "time-pre-market": "Pre Market",
                        "time-after-hours": "Post Market",
                    }.get(row.get("time"), "Unknown")
                self.date_times[date] = timings
                self.earnings_times = timings.copy()
                self.logger.info("Found %s earnings releases for %s", len(timings), date)
                return list(timings)
            except Exception as exc:
                self.logger.warning("Calendar attempt %s failed: %s", attempt + 1, exc)
                if attempt == 0:
                    self.session_manager.rotate_session()
                else:
                    raise EarningsCalendarError(
                        f"Could not load earnings for {date} from Nasdaq: {exc}"
                    ) from exc

    def get_earnings_time(self, ticker: str, date=None):
        timings = self.date_times.get(date, {}) if date else self.earnings_times
        return timings.get(ticker.upper(), "Unknown")
