"""Exchange rates, currency conversion and a background rate refresher."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Iterable

from ledgerkit.errors import RateNotFoundError
from ledgerkit.money import Money, minor_digits, to_decimal

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rate:
    """``1 base = value quote`` on ``as_of``: EUR/USD 1.10 means one euro costs 1.10 dollars."""

    base: str
    quote: str
    value: Decimal
    as_of: date


class RateTable:
    def __init__(self, max_age_days: int = 7):
        self.max_age = timedelta(days=max_age_days)
        self._rates: dict[tuple[str, str], dict[date, Rate]] = {}
        self._lock = threading.Lock()

    def add(self, base: str, quote: str, value: Decimal | str | int, as_of: date) -> Rate:
        minor_digits(base), minor_digits(quote)
        rate = Rate(base, quote, to_decimal(value), as_of)
        if rate.value <= 0:
            raise ValueError("exchange rates must be positive")
        with self._lock:
            self._rates.setdefault((base, quote), {})[as_of] = rate
        return rate

    def update(self, rates: Iterable[Rate]) -> int:
        return len([self.add(r.base, r.quote, r.value, r.as_of) for r in rates])

    def _latest(self, base: str, quote: str, on: date | None) -> Rate | None:
        with self._lock:
            series = [r for d, r in sorted(self._rates.get((base, quote), {}).items()) if on is None or d <= on]
        return series[-1] if series else None

    def rate(self, base: str, quote: str, on: date | None = None) -> Decimal:
        """Units of ``quote`` bought by one unit of ``base`` at the latest rate on or before ``on``."""
        if base == quote:
            return Decimal(1)
        found = self._latest(base, quote, on)
        if found is not None:
            value = found.value
        elif (found := self._latest(quote, base, on)) is not None:
            value = 1 / found.value
        else:
            raise RateNotFoundError(f"no {base}/{quote} rate" + (f" on or before {on}" if on else ""))
        if on is not None and on - found.as_of > self.max_age:
            logging.warn("using stale %s/%s rate from %s for %s", found.base, found.quote, found.as_of, on)
        return value

    def convert(self, money: Money, currency: str, on: date | None = None) -> Money:
        """Convert ``money`` into ``currency``, rounded to the target currency's minor unit."""
        if money.currency == currency:
            return money
        return Money(money.amount * self.rate(currency, money.currency, on), currency).rounded()


class RateRefresher:
    """Polls ``provider`` from a daemon thread and loads the returned rates into ``table``."""

    def __init__(self, table: RateTable, provider: Callable[[], Iterable[Rate]], interval: float = 3600.0):
        self.table, self.provider, self.interval = table, provider, interval
        self.refreshes = 0
        self.last_error: Exception | None = None
        self._stop = threading.Event()
        self._refreshed = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh_once(self) -> int:
        try:
            count = self.table.update(self.provider())
        except Exception as exc:  # a failing provider must not kill the refresher
            self.last_error = exc
            log.error("rate refresh failed: %s", exc)
            return 0
        self.refreshes += 1
        self._refreshed.set()
        return count

    def _run(self) -> None:
        while not self._stop.isSet():
            self.refresh_once()
            self._stop.wait(self.interval)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.isSet()

    def start(self) -> None:
        if self.running:
            raise RuntimeError("rate refresher is already running")
        self._stop.clear()
        self._refreshed.clear()
        thread = threading.Thread(target=self._run)
        thread.setName("ledgerkit-rate-refresher")
        thread.setDaemon(True)
        thread.start()
        self._thread = thread

    def wait_for_refresh(self, timeout: float | None = None) -> bool:
        return self._refreshed.wait(timeout)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
