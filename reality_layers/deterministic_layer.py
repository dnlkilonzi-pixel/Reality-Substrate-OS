"""
Deterministic Reality Layer.

Removes all sources of non-determinism from the runtime:

* ``time_now()`` returns a monotonically advancing *logical* clock that
  increments by a fixed step each call (never reads the wall clock).
* ``memory_alloc()`` returns deterministic, sequential addresses.
* ``process_schedule()`` always assigns priority 0.
* ``io_read()`` returns empty bytes (no external I/O).
* ``io_write()`` is a no-op (discards data).

When this layer is active, the system produces identical behaviour
across runs given the same input event sequence — enabling reproducible
testing and replay.
"""
from __future__ import annotations

from typing import Any, Dict

from .base_layer import BaseLayer


class DeterministicLayer(BaseLayer):
    """
    Overrides all non-deterministic system calls with stable stubs.

    Parameters
    ----------
    start_time : float
        Initial logical clock value (default ``0.0``).
    time_step : float
        Amount to advance the logical clock per ``time_now()`` call
        (default ``1.0``).
    """

    name: str = "deterministic_layer"

    def __init__(self, start_time: float = 0.0, time_step: float = 1.0) -> None:
        super().__init__()
        self._logical_time: float = start_time
        self._time_step: float = time_step
        self._alloc_counter: int = 0x1000  # deterministic base address

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def time_now(self) -> float:
        """Advance and return the logical clock.  Never reads wall time."""
        t = self._logical_time
        self._logical_time += self._time_step
        return t

    def memory_alloc(self, size: int) -> Dict[str, Any]:
        """Return a deterministic allocation with a sequential address."""
        address = self._alloc_counter
        self._alloc_counter += size
        return {"size": size, "address": address}

    def process_schedule(self, pid: int, priority: int = 0) -> Dict[str, Any]:
        """Always schedule with priority 0 for reproducibility."""
        return {"pid": pid, "priority": 0, "scheduled": True}

    def io_read(self, path: str) -> bytes:
        """Return empty bytes — no external I/O in deterministic mode."""
        return b""

    def io_write(self, path: str, data: bytes) -> int:
        """Discard all writes — no external I/O in deterministic mode."""
        return len(data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def reset_clock(self, start_time: float = 0.0) -> None:
        """Reset the logical clock to *start_time*."""
        self._logical_time = start_time

    @property
    def current_time(self) -> float:
        """Current logical clock value (without advancing it)."""
        return self._logical_time
