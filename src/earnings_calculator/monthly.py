"""Resumable monthly earnings/volume screening; no option-chain requests."""

import argparse
import calendar
import csv
import hashlib
import io
import json
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import exchange_calendars as xcals
import numpy as np
from yfinance.exceptions import YFPricesMissingError, YFTzMissingError
from earnings_calculator.calendar import EarningsCalendarFetcher
from earnings_calculator.market_data import DataRequestPaused, price_history
from earnings_calculator.options import MIN_AVG_VOLUME, IV_INTERPOLATION_DTE

ROOT = Path(__file__).resolve().parents[2]
FIELDS = [
    "schema_version",
    "month",
    "ticker",
    "earnings_date",
    "earnings_time",
    "analysis_date",
    "run_after_et",
    "run_before_et",
    "avg_volume_30",
    "volume_pass",
    "volume_as_of",
    "status",
    "error",
]


def eastern_today():
    return datetime.now(ZoneInfo("America/New_York")).date()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(value, allow_nan=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def analysis_window(earnings_day, timing):
    """Analyze before the preceding release, using actual NYSE sessions/early closes."""
    if timing not in {"Pre Market", "Post Market"}:
        return "", "", ""
    exchange = xcals.get_calendar("XNYS")
    candidate = (
        earnings_day - timedelta(days=1) if timing == "Pre Market" else earnings_day
    )
    session = exchange.date_to_session(candidate.isoformat(), direction="previous")
    close = exchange.session_close(session).tz_convert("America/New_York")
    return (
        session.date().isoformat(),
        (close - timedelta(minutes=30)).isoformat(),
        close.isoformat(),
    )


class MonthlyEarningsCache:
    def __init__(
        self,
        root=None,
        calendar_fetcher=None,
        history_loader=price_history,
        today=eastern_today,
        calendar_delay=1.0,
    ):
        self.root = Path(root or ROOT)
        self.output = self.root / "monthly_earnings.csv"
        self.meta = self.root / "monthly_earnings.meta.json"
        self.runtime = self.root / "runtime_data"
        self.checkpoint = self.runtime / "monthly_checkpoint.json"
        self.calendar = calendar_fetcher or EarningsCalendarFetcher()
        self.history_loader, self.today, self.calendar_delay = (
            history_loader,
            today,
            calendar_delay,
        )

    def _metadata(self):
        if not self.meta.exists() or not self.output.exists():
            return None
        try:
            metadata = json.loads(self.meta.read_text(encoding="utf-8"))
            if (
                metadata.get("sha256")
                != hashlib.sha256(self.output.read_bytes()).hexdigest()
            ):
                return None
            return metadata
        except (ValueError, OSError):
            return None

    def events_for_date(self, day):
        """None means unavailable; an empty list means a complete screened empty day."""
        metadata = self._metadata()
        if not metadata or not metadata.get("complete") or day[:7] != metadata["month"]:
            return None
        # One monthly screen is only a shortlist: daily scans recheck current volume.
        content = self.output.read_bytes()
        if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
            return None
        return [
            row
            for row in csv.DictReader(io.StringIO(content.decode("utf-8")))
            if row["earnings_date"] == day and row["volume_pass"] == "True"
        ]

    def ensure_current(self, max_symbols=50, force=False, progress=print):
        today = self.today()
        month = today.strftime("%Y-%m")
        metadata = self._metadata()
        pending_refresh = False
        if self.checkpoint.exists():
            previous_state = json.loads(self.checkpoint.read_text(encoding="utf-8"))
            pending_refresh = previous_state.get(
                "month"
            ) == month and previous_state.get("refreshing", False)
        if (
            not pending_refresh
            and metadata
            and metadata.get("complete")
            and metadata.get("month") == month
            and not force
        ):
            return self.output
        self.runtime.mkdir(parents=True, exist_ok=True)
        # A separate sqlite lock coordinates GUI, CLI and scheduled jobs. OS releases it on exit.
        lock = sqlite3.connect(
            self.runtime / "monthly_job.sqlite3", timeout=0, isolation_level=None
        )
        lock.execute("CREATE TABLE IF NOT EXISTS job (id INTEGER)")
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            lock.close()
            raise RuntimeError("Another monthly refresh is already running") from exc
        try:
            state = {}
            if self.checkpoint.exists() and not force:
                state = json.loads(self.checkpoint.read_text(encoding="utf-8"))
            if state.get("month") != month:
                state = {
                    "month": month,
                    "calendar": {},
                    "volume": {},
                    "refreshing": True,
                }
            state["refreshing"] = True
            atomic_json(self.checkpoint, state)
            days = calendar.monthrange(today.year, today.month)[1]
            first = date(today.year, today.month, 1)
            # Cover the next month's first trading morning, including intervening weekends.
            next_month = first + timedelta(days=days)
            first_next_session = (
                xcals.get_calendar("XNYS")
                .date_to_session(next_month.isoformat(), direction="next")
                .date()
            )
            for offset in range((first_next_session - first).days + 1):
                day = (first + timedelta(days=offset)).isoformat()
                if day not in state["calendar"]:
                    tickers = self.calendar.fetch_earnings_data(day)
                    state["calendar"][day] = {
                        ticker: self.calendar.get_earnings_time(ticker, day)
                        for ticker in tickers
                    }
                    atomic_json(self.checkpoint, state)
                    progress(f"Calendar saved: {day} ({len(tickers)} companies)")
                    time.sleep(self.calendar_delay)
            universe = sorted(
                {ticker for timings in state["calendar"].values() for ticker in timings}
            )
            upcoming = {
                ticker
                for day, timings in state["calendar"].items()
                if day >= today.isoformat()
                for ticker in timings
            }
            universe.sort(key=lambda ticker: (ticker not in upcoming, ticker))
            pending = [ticker for ticker in universe if ticker not in state["volume"]]
            processed = 0
            pause = None
            for ticker in pending:
                if processed >= max_symbols:
                    break
                try:
                    history = self.history_loader(ticker)
                    volume = (
                        float(
                            history["Volume"]
                            .rolling(IV_INTERPOLATION_DTE)
                            .mean()
                            .iloc[-1]
                        )
                        if not history.empty and "Volume" in history
                        else float("nan")
                    )
                    valid = np.isfinite(volume) and volume >= 0
                    state["volume"][ticker] = {
                        "value": volume if valid else None,
                        "as_of": history.index[-1].date().isoformat()
                        if not history.empty
                        else "",
                        "error": "" if valid else "Insufficient 30 completed sessions",
                    }
                except DataRequestPaused as exc:
                    pause = exc
                    break
                except (YFPricesMissingError, YFTzMissingError) as exc:
                    state["volume"][ticker] = {
                        "value": None,
                        "as_of": "",
                        "error": str(exc),
                    }
                except Exception as exc:
                    # Keep unavailable tickers visible and retry on the next scheduled run.
                    progress(f"History unavailable for {ticker}: {exc}")
                    processed += 1
                    continue
                processed += 1
                atomic_json(self.checkpoint, state)
                progress(
                    f"Volume saved: {ticker} ({len(state['volume'])}/{len(universe)})"
                )
            complete = all(ticker in state["volume"] for ticker in universe)
            atomic_json(self.checkpoint, state)
            rows = []
            for day, timings in sorted(state["calendar"].items()):
                for ticker, timing in sorted(timings.items()):
                    item = state["volume"].get(ticker, {})
                    value = item.get("value")
                    passed = value is not None and value >= MIN_AVG_VOLUME
                    analysis_day, after, before = analysis_window(
                        date.fromisoformat(day), timing
                    )
                    status = (
                        "needs_data"
                        if not item
                        else "data_unavailable"
                        if value is None
                        else "volume_fail"
                        if not passed
                        else "unknown_time"
                        if not analysis_day
                        else "ready"
                    )
                    rows.append(
                        dict(
                            zip(
                                FIELDS,
                                [
                                    1,
                                    month,
                                    ticker,
                                    day,
                                    timing,
                                    analysis_day,
                                    after,
                                    before,
                                    value if value is not None else "",
                                    passed if item else "",
                                    item.get("as_of", ""),
                                    status,
                                    item.get("error", ""),
                                ],
                            )
                        )
                    )
            # Preserve a prior completed CSV until its replacement is complete.
            target = (
                self.output
                if complete or not self.output.exists()
                else self.runtime / "monthly_partial.csv"
            )
            temp = target.with_suffix(f".{os.getpid()}.tmp")
            with temp.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temp, target)
            if target == self.output:
                atomic_json(
                    self.meta,
                    {
                        "schema_version": 1,
                        "month": month,
                        "complete": complete,
                        "screened_symbols": len(state["volume"]),
                        "total_symbols": len(universe),
                        "generated_at": datetime.now(
                            ZoneInfo("America/New_York")
                        ).isoformat(),
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    },
                )
            state["refreshing"] = not complete
            atomic_json(self.checkpoint, state)
            if pause:
                raise pause
            if not complete:
                raise RuntimeError(
                    f"Monthly screen saved but incomplete: {len(state['volume'])}/{len(universe)}. "
                    "Run again to resume; daily scans do not treat a partial CSV as complete."
                )
            return target
        finally:
            lock.rollback()
            lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=50,
        help="Maximum new volume checks this run; reruns resume checkpoints",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild even if this month's cache is complete",
    )
    args = parser.parse_args()
    if args.max_symbols < 1:
        parser.error("--max-symbols must be positive")
    try:
        print(MonthlyEarningsCache().ensure_current(args.max_symbols, args.refresh))
    except (RuntimeError, DataRequestPaused) as exc:
        print(str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
