"""
Event Tracer — records and replays system event streams.

:class:`EventTracer` attaches to an :class:`~core.event_bus.EventBus` and
captures every event that flows through it.  The trace can be:

* Printed as a formatted timeline.
* Saved to / loaded from a plain JSON log file.
* Replayed through a fresh :class:`~core.event_bus.EventBus` to
  reproduce a past execution.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.event_bus import Event, EventBus


class EventTracer:
    """
    Observes and records events from an :class:`~core.event_bus.EventBus`.

    Usage::

        bus = EventBus()
        tracer = EventTracer(bus)

        bus.publish(Event("cpu_usage", {"value": 85}))

        print(tracer.timeline())        # human-readable trace
        tracer.save("/tmp/trace.json")  # persist to disk
    """

    def __init__(self, bus: EventBus, tag: str = "trace") -> None:
        self._bus = bus
        self.tag = tag
        self._trace: List[Dict[str, Any]] = []
        bus.subscribe("*", self._record)

    # ------------------------------------------------------------------
    # Internal record callback
    # ------------------------------------------------------------------

    def _record(self, event: Event) -> None:
        self._trace.append({
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "data": event.data,
            "source": event.source,
        })

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def trace(self) -> List[Dict[str, Any]]:
        """All recorded trace entries."""
        return list(self._trace)

    def filter(self, event_type: str) -> List[Dict[str, Any]]:
        """Return trace entries matching *event_type*."""
        return [e for e in self._trace if e["event_type"] == event_type]

    def timeline(self) -> str:
        """Return a human-readable chronological event timeline."""
        if not self._trace:
            return f"[{self.tag}] (no events recorded)"
        lines = [f"[{self.tag}] Event Timeline ({len(self._trace)} events)", "=" * 60]
        t0 = self._trace[0]["timestamp"]
        for entry in self._trace:
            elapsed = entry["timestamp"] - t0
            source = f"  src={entry['source']}" if entry["source"] else ""
            lines.append(
                f"  +{elapsed:7.3f}s  {entry['event_type']:20}  {entry['data']}{source}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save the trace to a JSON file at *path*."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as fh:
            json.dump({"tag": self.tag, "events": self._trace}, fh, indent=2)

    @classmethod
    def load(cls, path: str, bus: Optional[EventBus] = None) -> "EventTracer":
        """
        Load a trace from a JSON file.

        If *bus* is provided the tracer attaches to it; otherwise a new
        standalone :class:`~core.event_bus.EventBus` is created.
        """
        with open(path) as fh:
            payload = json.load(fh)
        b = bus if bus is not None else EventBus()
        tracer = cls(b, tag=payload.get("tag", "loaded"))
        tracer._trace = payload.get("events", [])
        return tracer

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    def replay(self, target_bus: Optional[EventBus] = None) -> None:
        """
        Re-publish all recorded events onto *target_bus* (or the
        original bus if not supplied) in chronological order.
        """
        bus = target_bus if target_bus is not None else self._bus
        for entry in self._trace:
            event = Event(
                event_type=entry["event_type"],
                data=entry["data"],
                timestamp=entry["timestamp"],
                source=entry.get("source"),
            )
            bus.publish(event)

    def clear(self) -> None:
        """Discard all recorded trace entries."""
        self._trace.clear()

    def __repr__(self) -> str:
        return f"EventTracer(tag={self.tag!r}, events={len(self._trace)})"
