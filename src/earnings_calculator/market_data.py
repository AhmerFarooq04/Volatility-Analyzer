"""One paced Yahoo session, persistent budgets and a shared circuit breaker."""

import os
from contextlib import contextmanager
import sqlite3
import threading
import time
from pathlib import Path
from curl_cffi.requests import Session
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

DATA_DIR = Path(__file__).resolve().parents[2] / "runtime_data"


class DataRequestPaused(YFRateLimitError):
    def __init__(self, reason, retry_at):
        self.reason = reason
        self.retry_at = retry_at
        Exception.__init__(self, reason)

    def __str__(self):
        return self.reason


class RequestBudget:
    """Count guarded request dispatches, including cookies/crumbs, across processes."""

    def __init__(
        self,
        path=None,
        interval=3.0,
        hourly=120,
        daily=500,
        clock=time.time,
        sleep=time.sleep,
    ):
        self.path = Path(path or DATA_DIR / "yahoo_budget.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.interval, self.hourly, self.daily = interval, hourly, daily
        self.clock, self.sleep = clock, sleep
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (at REAL NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value REAL)"
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            yield connection
        finally:
            connection.close()

    def reserve(self):
        while True:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                now = self.clock()
                blocked = db.execute(
                    "SELECT value FROM state WHERE key='blocked'"
                ).fetchone()
                if blocked and now < blocked[0]:
                    db.rollback()
                    raise DataRequestPaused(
                        "Yahoo requests paused after a rate limit; try after "
                        + time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(blocked[0])
                        ),
                        blocked[0],
                    )
                db.execute("DELETE FROM calls WHERE at <= ?", (now - 86400,))
                calls = [r[0] for r in db.execute("SELECT at FROM calls ORDER BY at")]
                recent = [at for at in calls if at > now - 3600]
                retry = None
                if len(calls) >= self.daily:
                    retry = calls[0] + 86400
                if len(recent) >= self.hourly:
                    retry = max(retry or 0, recent[0] + 3600)
                if retry is not None:
                    db.rollback()
                    raise DataRequestPaused(
                        "Local Yahoo request budget reached; no more requests until "
                        + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(retry)),
                        retry,
                    )
                delay = max(0, calls[-1] + self.interval - now) if calls else 0
                if delay <= 0:
                    db.execute("INSERT INTO calls VALUES (?)", (now,))
                    db.commit()
                    return
                db.rollback()
            self.sleep(delay)

    def trip(self, seconds=3600):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            until = self.clock() + max(3600, seconds)
            old = db.execute("SELECT value FROM state WHERE key='blocked'").fetchone()
            until = max(until, old[0] if old else 0)
            db.execute("INSERT OR REPLACE INTO state VALUES ('blocked', ?)", (until,))
            db.commit()
        return until


class PacedYahooSession(Session):
    def __init__(self, budget=None):
        super().__init__(impersonate="chrome", trust_env=False)
        self.budget = budget or RequestBudget()
        self.request_lock = threading.RLock()

    def request(self, *args, **kwargs):
        with self.request_lock:
            self.budget.reserve()
            response = super().request(*args, **kwargs)
            if response.status_code == 429:
                try:
                    retry = float(response.headers.get("Retry-After", 3600))
                except (TypeError, ValueError):
                    retry = 3600
                until = self.budget.trip(retry)
                raise DataRequestPaused(
                    "Yahoo rate limit: requests stopped for at least one hour.", until
                )
            return response


_SESSION = None
_SESSION_LOCK = threading.Lock()


def yahoo_session():
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = PacedYahooSession()
        return _SESSION


def yahoo_ticker(symbol):
    return yf.Ticker(symbol, session=yahoo_session())


def stop_on_rate_limit(exc):
    if isinstance(exc, DataRequestPaused):
        raise exc
    until = yahoo_session().budget.trip()
    raise DataRequestPaused(
        "Yahoo rate limit: requests stopped for at least one hour.", until
    ) from exc


def price_history(symbol, ticker=None, period="1y", max_age=86400):
    """Reuse completed daily bars; never cache today's partial daily candle."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import pandas as pd

    safe_symbol = "".join(c for c in symbol.upper() if c.isalnum() or c in "-._")
    if not safe_symbol:
        raise ValueError("Invalid ticker")
    path = DATA_DIR / "history" / f"{safe_symbol}-{period}.csv"
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if (
        path.exists()
        and time.time() - path.stat().st_mtime < max_age
        and datetime.fromtimestamp(
            path.stat().st_mtime, ZoneInfo("America/New_York")
        ).date()
        == today
    ):
        return pd.read_csv(path, index_col=0, parse_dates=True)
    try:
        history = (ticker or yahoo_ticker(symbol)).history(
            period=period, auto_adjust=True, prepost=False, raise_errors=True
        )
    except YFRateLimitError as exc:
        stop_on_rate_limit(exc)
    if history.empty:
        return history
    today = datetime.now(ZoneInfo("America/New_York")).date()
    history = history[[stamp.date() < today for stamp in history.index]].copy()
    # Daily session labels are dates, not timestamps spanning two DST offsets.
    history.index = pd.DatetimeIndex(
        [stamp.date() for stamp in history.index], name="Date"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    history.to_csv(temp)
    os.replace(temp, path)
    return history
