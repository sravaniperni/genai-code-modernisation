"""Uplink forwarding: a background worker that periodically drains pending readings to the uplink."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any

log = logging.getLogger(__name__)


class Forwarder:
    """Daemon thread that calls ``send(fetch())`` every ``interval`` seconds or when :meth:`flush` is called.

    ``send`` returns True once the uplink accepted the batch; failures are logged and retried next cycle.
    """

    def __init__(self, fetch: Callable[[], Sequence[Any]], send: Callable[[Sequence[Any]], bool],
                 interval: float = 30.0, name: str = "sensorpipe-uplink"):
        self._fetch, self._send, self.interval = fetch, send, interval
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._done = threading.Event()
        self.delivered = 0
        self.failures = 0
        self._thread = threading.Thread(target=self._run, name=name)
        self._thread.setDaemon(True)

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stop.isSet()

    def start(self) -> Forwarder:
        self._thread.start()
        return self

    def flush(self, timeout: float = 10.0) -> bool:
        """Run a forwarding cycle now and wait for it; False if it did not finish within ``timeout``."""
        self._done.clear()
        self._wake.set()
        return self._done.wait(timeout)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.isSet():
            self._wake.wait(self.interval)
            self._wake.clear()
            if self._stop.isSet():
                break
            self._cycle()
            self._done.set()

    def _cycle(self) -> None:
        try:
            batch = self._fetch()
            if batch and not self._send(batch):
                raise RuntimeError("uplink rejected the batch")
            self.delivered += len(batch or ())
        except Exception as exc:  # the worker must survive uplink outages
            self.failures += 1
            log.warning("uplink forwarding failed: %s", exc)
