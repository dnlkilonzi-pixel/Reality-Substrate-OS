"""
System-wide event bus for the RS-CCE runtime.

Provides a lightweight publish/subscribe mechanism so that system
components, reality layers, and external adapters can inject events into
the causal graph without tight coupling.

Usage::

    bus = EventBus()

    # Subscribe to CPU events
    bus.subscribe("cpu_usage", lambda e: print(e))

    # Publish an event
    bus.publish(Event("cpu_usage", {"value": 92}))
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Event:
    """
    A discrete occurrence in the system.

    Attributes
    ----------
    event_type : str
        Identifies the kind of event (e.g. ``"cpu_usage"``, ``"packet_loss"``).
    data : dict
        Arbitrary payload attached to the event.
    timestamp : float
        Wall-clock time when the event was created (seconds since epoch).
    source : str, optional
        Identifier of the component that produced the event.
    """

    event_type: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"Event(type={self.event_type!r}, "
            f"data={self.data}, "
            f"ts={self.timestamp:.3f})"
        )


class EventBus:
    """
    A simple synchronous publish/subscribe event bus.

    Subscribers register a callback for a specific *event_type* (or the
    wildcard ``"*"`` to receive every event).  When an event is
    published, all matching callbacks are invoked synchronously before
    :meth:`publish` returns.

    All published events are also appended to :attr:`history` so they
    can be replayed later.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = {}
        self.history: List[Event] = []

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        """
        Register *callback* to be called whenever an event of
        *event_type* is published.

        Use ``"*"`` as *event_type* to receive all events.
        """
        self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        """Remove a previously registered *callback* for *event_type*."""
        listeners = self._subscribers.get(event_type, [])
        try:
            listeners.remove(callback)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, event: Event) -> None:
        """
        Publish *event* to all matching subscribers.

        Dispatches to callbacks registered for ``event.event_type`` and
        to wildcards (``"*"``).  The event is also appended to
        :attr:`history`.
        """
        self.history.append(event)
        for callback in list(self._subscribers.get(event.event_type, [])):
            callback(event)
        for callback in list(self._subscribers.get("*", [])):
            callback(event)

    # ------------------------------------------------------------------
    # Inspection / replay
    # ------------------------------------------------------------------

    def get_events(self, event_type: Optional[str] = None) -> List[Event]:
        """
        Return events from history, optionally filtered by *event_type*.
        """
        if event_type is None:
            return list(self.history)
        return [e for e in self.history if e.event_type == event_type]

    def clear_history(self) -> None:
        """Discard all stored events (does not affect subscriptions)."""
        self.history.clear()

    def replay(self, events: Optional[List[Event]] = None) -> None:
        """
        Re-publish a sequence of events in order.

        If *events* is ``None``, the stored :attr:`history` is replayed.
        Useful for deterministic replay of past execution traces.
        """
        source = events if events is not None else list(self.history)
        for event in source:
            for callback in list(self._subscribers.get(event.event_type, [])):
                callback(event)
            for callback in list(self._subscribers.get("*", [])):
                callback(event)

    def __repr__(self) -> str:
        return (
            f"EventBus("
            f"subscribers={sum(len(v) for v in self._subscribers.values())}, "
            f"history={len(self.history)})"
        )
