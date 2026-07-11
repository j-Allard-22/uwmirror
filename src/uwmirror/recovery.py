"""Device-lost retry policy (pure, injectable clock).

Desktop Duplication dies on resolution changes, monitor sleep, and
exclusive-fullscreen transitions; the fix is always "recreate the camera".
This policy paces those recreation attempts with capped exponential backoff
and never gives up — a monitor can sleep for hours.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class RetryPolicy:
    """Capped exponential backoff between capture-recreation attempts."""

    def __init__(
        self,
        initial_delay: float = 0.5,
        max_delay: float = 5.0,
        factor: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if initial_delay <= 0 or max_delay < initial_delay or factor < 1.0:
            raise ValueError("invalid backoff parameters")
        self._initial_delay = initial_delay
        self._max_delay = max_delay
        self._factor = factor
        self._sleep = sleep
        self._current = initial_delay
        self.failures = 0

    def wait(self) -> None:
        """Sleep for the current delay and escalate the next one."""
        self.failures += 1
        self._sleep(self._current)
        self._current = min(self._current * self._factor, self._max_delay)

    def reset(self) -> None:
        """Call after a successful frame: next failure starts from the initial delay."""
        self._current = self._initial_delay
        self.failures = 0
