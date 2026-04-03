"""
Slow-Time Reality Layer.

Scales the perceived passage of time by a configurable factor.

* ``time_now()`` returns wall-clock time multiplied by *factor*.
  A factor of ``0.5`` makes time appear to flow at half speed;
  a factor of ``2.0`` doubles the perceived rate.

This is useful for:

* Stress-testing causal rules that depend on time thresholds.
* Simulating accelerated or decelerated execution environments.
* Debugging time-sensitive behaviour without modifying rule logic.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from .base_layer import BaseLayer


class SlowTimeLayer(BaseLayer):
    """
    Scales ``time_now()`` by a constant *factor*.

    Parameters
    ----------
    factor : float
        Time scaling factor (default ``1.0`` — no change).
        Values < 1.0 slow time; values > 1.0 speed it up.
    epoch : float, optional
        Reference wall-clock origin.  Defaults to the time this layer
        was instantiated.  Scaled time is computed relative to *epoch*
        so the returned value is always non-negative from the moment
        this layer is activated.
    """

    name: str = "slow_time_layer"

    def __init__(self, factor: float = 1.0, epoch: float | None = None) -> None:
        super().__init__()
        if factor <= 0:
            raise ValueError(f"time factor must be positive, got {factor!r}")
        self._factor: float = factor
        self._epoch: float = epoch if epoch is not None else time.time()

    # ------------------------------------------------------------------
    # Override
    # ------------------------------------------------------------------

    def time_now(self) -> float:
        """Return wall-clock elapsed time since *epoch*, scaled by *factor*."""
        elapsed = time.time() - self._epoch
        return self._epoch + elapsed * self._factor

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def factor(self) -> float:
        return self._factor

    @factor.setter
    def factor(self, value: float) -> None:
        if value <= 0:
            raise ValueError(f"time factor must be positive, got {value!r}")
        self._factor = value

    @property
    def epoch(self) -> float:
        return self._epoch
