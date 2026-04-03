"""
Base Reality Layer — provides default OS-level system call implementations.

All other layers inherit from :class:`BaseLayer` and override only the
methods they need to intercept.

:class:`LayerStack` composes multiple layers so that the topmost layer
that overrides a method is the one that handles the call.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class BaseLayer:
    """
    Default reality layer that delegates to real OS semantics.

    Override any method in a subclass to intercept or replace the
    corresponding system behaviour.

    Attributes
    ----------
    name : str
        Human-readable name for this layer.
    enabled : bool
        When ``False`` the layer is skipped by :class:`LayerStack`.
    """

    name: str = "base_layer"

    def __init__(self) -> None:
        self.enabled: bool = True
        self._injected_events: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Overridable system semantics
    # ------------------------------------------------------------------

    def time_now(self) -> float:
        """Return the current time as seconds since the Unix epoch."""
        return time.time()

    def memory_alloc(self, size: int) -> Dict[str, Any]:
        """
        Simulate allocating *size* bytes.

        Returns a dict representing the allocation handle.
        """
        return {"size": size, "address": id(bytearray(size))}

    def process_schedule(self, pid: int, priority: int = 0) -> Dict[str, Any]:
        """
        Simulate scheduling a process.

        Returns a dict with the effective scheduling parameters.
        """
        return {"pid": pid, "priority": priority, "scheduled": True}

    def io_read(self, path: str) -> bytes:
        """Read data from *path*.  Default implementation is a no-op stub."""
        return b""

    def io_write(self, path: str, data: bytes) -> int:
        """Write *data* to *path*.  Default implementation is a no-op stub."""
        return len(data)

    # ------------------------------------------------------------------
    # Event injection support
    # ------------------------------------------------------------------

    def inject_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Queue an event for injection into the causal graph.

        The runtime's execution loop drains this queue each tick.
        """
        self._injected_events.append({"event_type": event_type, "data": data or {}})

    def drain_events(self) -> List[Dict[str, Any]]:
        """Return and clear all queued events."""
        events, self._injected_events = self._injected_events, []
        return events

    def __repr__(self) -> str:
        return f"{type(self).__name__}(enabled={self.enabled})"


class LayerStack:
    """
    An ordered stack of :class:`BaseLayer` instances.

    The layer added *last* has the highest priority (it is checked first
    for each method call).  The first layer in the stack to provide a
    non-``BaseLayer`` implementation handles the call.

    Usage::

        stack = LayerStack()
        stack.push(BaseLayer())
        stack.push(SlowTimeLayer(factor=2.0))

        t = stack.time_now()  # uses SlowTimeLayer
    """

    def __init__(self) -> None:
        self._layers: List[BaseLayer] = []

    def push(self, layer: BaseLayer) -> "LayerStack":
        """Add *layer* on top of the stack and return *self* for chaining."""
        self._layers.append(layer)
        return self

    def pop(self) -> BaseLayer:
        """Remove and return the topmost layer."""
        return self._layers.pop()

    @property
    def layers(self) -> List[BaseLayer]:
        return list(self._layers)

    # ------------------------------------------------------------------
    # Delegating syscalls — topmost enabled layer wins
    # ------------------------------------------------------------------

    def _resolve(self, method_name: str) -> Optional[BaseLayer]:
        """
        Return the topmost enabled layer whose method differs from the
        :class:`BaseLayer` implementation (i.e. has been overridden).
        """
        base_impl = getattr(BaseLayer, method_name)
        for layer in reversed(self._layers):
            if not layer.enabled:
                continue
            layer_impl = getattr(type(layer), method_name, None)
            if layer_impl is not None and layer_impl is not base_impl:
                return layer
        # Fall back to the topmost enabled base layer
        for layer in reversed(self._layers):
            if layer.enabled:
                return layer
        return None

    def time_now(self) -> float:
        layer = self._resolve("time_now")
        return layer.time_now() if layer else time.time()

    def memory_alloc(self, size: int) -> Dict[str, Any]:
        layer = self._resolve("memory_alloc")
        return layer.memory_alloc(size) if layer else {"size": size}

    def process_schedule(self, pid: int, priority: int = 0) -> Dict[str, Any]:
        layer = self._resolve("process_schedule")
        return layer.process_schedule(pid, priority) if layer else {"pid": pid}

    def io_read(self, path: str) -> bytes:
        layer = self._resolve("io_read")
        return layer.io_read(path) if layer else b""

    def io_write(self, path: str, data: bytes) -> int:
        layer = self._resolve("io_write")
        return layer.io_write(path, data) if layer else len(data)

    def drain_all_events(self) -> List[Dict[str, Any]]:
        """Drain queued events from all layers."""
        events: List[Dict[str, Any]] = []
        for layer in self._layers:
            if layer.enabled:
                events.extend(layer.drain_events())
        return events

    def __repr__(self) -> str:
        names = [type(l).__name__ for l in self._layers]
        return f"LayerStack({' → '.join(names)})"
