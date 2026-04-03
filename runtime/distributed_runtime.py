"""
Distributed Causal Consistency for RS-CCE.

Enables multiple RS-CCE nodes to synchronise their causal realities while
preserving causal ordering — turning the system into a "distributed reality
engine."

Architecture
------------
Each RS-CCE process is a :class:`CausalNodeRuntime` that:

* Maintains a :class:`VectorClock` for causal ordering across nodes.
* Produces :class:`DistributedCausalEvent` records enriched with clock
  timestamps.
* Stores events in a local :class:`DistributedEventLog`.
* Can synchronise its log with any other node's log to achieve causal
  consistency.

Vector Clocks
-------------
A :class:`VectorClock` assigns a logical timestamp vector to each event.
Event A *happens before* B (A → B) iff A's vector is component-wise ≤ B's
vector, with at least one strict inequality.  Events that are neither A → B
nor B → A are **concurrent** and may represent conflicts.

Deterministic Merge
-------------------
:meth:`DistributedEventLog.merge` produces a single causally-consistent log
from two logs by:

1. Unioning all events (deduplication by ``event_id``).
2. Topological sorting respecting the happens-before relation.
3. Breaking ties among concurrent events by ``(source_node, seq_no)`` for
   full determinism.

Conflict Detection
------------------
A conflict occurs when two concurrent events both mutate the same state key.
:meth:`DistributedEventLog.conflicts` returns all such pairs.

The :class:`ConflictPolicy` enum selects the resolution strategy applied
during :meth:`~DistributedEventLog.merge`:

* ``LAST_WRITER_WINS``  — keep the event with the higher ``seq_no``.
* ``FIRST_WRITER_WINS`` — keep the event with the lower ``seq_no``.
* ``KEEP_BOTH``         — retain both events; caller handles merging.

Usage::

    node_a = CausalNodeRuntime("A", graph_a, peers=["B"])
    node_b = CausalNodeRuntime("B", graph_b, peers=["A"])

    ev = node_a.emit("cpu_spike", data={"value": 95},
                     state_mutations={"throttle": True})
    node_b.receive(ev)

    merged = node_a.sync(node_b.log)
    for event in merged.causal_order():
        print(event.event_type, event.vector_clock)
"""
from __future__ import annotations

import heapq
import time as _time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple


# ===========================================================================
# Vector Clock
# ===========================================================================

class VectorClock:
    """
    A Lamport vector clock for causal ordering across distributed nodes.

    Each RS-CCE node maintains its own :class:`VectorClock`.  Every event
    emitted by a node carries a snapshot of the clock at emission time.

    Causal ordering rule (Lamport, 1978)::

        A → B  ⟺  ∀k: VC(A)[k] ≤ VC(B)[k]  AND  ∃k: VC(A)[k] < VC(B)[k]

    Usage::

        vc_a = VectorClock("A", peers=["B"])
        vc_b = VectorClock("B", peers=["A"])

        ts_a1 = vc_a.tick()        # A emits event 1
        vc_b.update(ts_a1)         # B receives event 1 from A
        ts_b1 = vc_b.tick()        # B emits event 1 (causally after ts_a1)
        assert VectorClock.happens_before(ts_a1, ts_b1)
    """

    def __init__(self, node_id: str, peers: Optional[List[str]] = None) -> None:
        self.node_id = node_id
        self._clock: Dict[str, int] = {node_id: 0}
        for peer in (peers or []):
            self._clock.setdefault(peer, 0)

    def tick(self) -> Dict[str, int]:
        """Increment own counter and return a snapshot of the current clock."""
        self._clock[self.node_id] = self._clock.get(self.node_id, 0) + 1
        return dict(self._clock)

    def update(self, received: Dict[str, int]) -> None:
        """
        Merge *received* clock (from an incoming event) into this clock.

        Sets each component to ``max(local, received)``.
        """
        for node, ts in received.items():
            self._clock[node] = max(self._clock.get(node, 0), ts)

    def snapshot(self) -> Dict[str, int]:
        """Return a copy of the current clock without incrementing."""
        return dict(self._clock)

    @staticmethod
    def happens_before(vc_a: Dict[str, int], vc_b: Dict[str, int]) -> bool:
        """
        Return ``True`` iff the event with clock *vc_a* happened before *vc_b*.

        ``A → B``  iff  ``∀k: vc_a[k] ≤ vc_b[k]``  AND  ``∃k: vc_a[k] < vc_b[k]``
        """
        all_keys = set(vc_a) | set(vc_b)
        le = all(vc_a.get(k, 0) <= vc_b.get(k, 0) for k in all_keys)
        lt = any(vc_a.get(k, 0) < vc_b.get(k, 0) for k in all_keys)
        return le and lt

    @staticmethod
    def concurrent(vc_a: Dict[str, int], vc_b: Dict[str, int]) -> bool:
        """
        Return ``True`` iff *vc_a* and *vc_b* are concurrent (neither
        happens-before the other).
        """
        return (
            not VectorClock.happens_before(vc_a, vc_b)
            and not VectorClock.happens_before(vc_b, vc_a)
        )

    def __repr__(self) -> str:
        return f"VectorClock({self.node_id!r}, {self._clock})"


# ===========================================================================
# Distributed Causal Event
# ===========================================================================

@dataclass
class DistributedCausalEvent:
    """
    An event emitted by a specific RS-CCE node, enriched with causal metadata.

    Attributes
    ----------
    event_type : str
        Semantic event type (same namespace as the RS-CCE event bus).
    source_node : str
        ID of the RS-CCE node that emitted this event.
    vector_clock : dict
        Vector clock snapshot at the moment of emission.
    data : Any
        Event payload.
    event_id : str
        Globally unique identifier (auto-generated UUID) used for
        deduplication during log merge.
    local_timestamp : float
        Wall-clock time of emission (diagnostic only; not used for causal
        ordering).
    seq_no : int
        Monotonically increasing sequence number within *source_node*.
        Used as a deterministic tiebreaker for concurrent events.
    state_mutations : dict
        Key/value pairs this event mutates in the state store, if any.
        Used for conflict detection during merge.
    """

    event_type: str
    source_node: str
    vector_clock: Dict[str, int]
    data: Any = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    local_timestamp: float = 0.0
    seq_no: int = 0
    state_mutations: Dict[str, Any] = field(default_factory=dict)

    def happens_before(self, other: "DistributedCausalEvent") -> bool:
        """Return ``True`` iff this event happened before *other*."""
        return VectorClock.happens_before(self.vector_clock, other.vector_clock)

    def concurrent_with(self, other: "DistributedCausalEvent") -> bool:
        """Return ``True`` iff this event and *other* are concurrent."""
        return VectorClock.concurrent(self.vector_clock, other.vector_clock)

    def __repr__(self) -> str:
        return (
            f"DistributedCausalEvent("
            f"type={self.event_type!r}, "
            f"src={self.source_node!r}, "
            f"seq={self.seq_no}, "
            f"vc={self.vector_clock})"
        )


# ===========================================================================
# Conflict Policy
# ===========================================================================

class ConflictPolicy(Enum):
    """Strategy for resolving concurrent conflicting events during merge."""

    LAST_WRITER_WINS  = auto()   # Higher seq_no wins
    FIRST_WRITER_WINS = auto()   # Lower seq_no wins
    KEEP_BOTH         = auto()   # Retain both; caller resolves


# ===========================================================================
# Distributed Event Log
# ===========================================================================

class DistributedEventLog:
    """
    A causally-ordered, merge-able log of :class:`DistributedCausalEvent`.

    Usage::

        log_a = DistributedEventLog("A")
        log_b = DistributedEventLog("B")

        log_a.append(event_from_a)
        log_b.append(event_from_b)

        merged = log_a.merge(log_b)
        for ev in merged.causal_order():
            print(ev)
    """

    def __init__(self, owner_node: str) -> None:
        self.owner_node = owner_node
        self._events: Dict[str, DistributedCausalEvent] = {}   # event_id → event

    def append(self, event: DistributedCausalEvent) -> None:
        """Add *event* to this log (idempotent by ``event_id``)."""
        self._events[event.event_id] = event

    @property
    def events(self) -> List[DistributedCausalEvent]:
        """All events in insertion order."""
        return list(self._events.values())

    def merge(
        self,
        other: "DistributedEventLog",
        conflict_policy: ConflictPolicy = ConflictPolicy.LAST_WRITER_WINS,
    ) -> "DistributedEventLog":
        """
        Merge *other* into a **new** log and return the merged result.

        The merge is **deterministic**: given the same two input logs it always
        produces the same output regardless of argument order.

        Steps:

        1. Union of all events (deduplication by ``event_id``).
        2. Conflict resolution (when *conflict_policy* is not ``KEEP_BOTH``).
        3. Return the new log.

        Parameters
        ----------
        other : DistributedEventLog
            The log to merge with.
        conflict_policy : ConflictPolicy
            How to handle concurrent events that mutate the same state key.
        """
        merged = DistributedEventLog(
            owner_node=f"merged({self.owner_node},{other.owner_node})"
        )

        all_events: Dict[str, DistributedCausalEvent] = {
            **self._events,
            **other._events,
        }

        if conflict_policy != ConflictPolicy.KEEP_BOTH:
            all_events = _resolve_conflicts(all_events, conflict_policy)

        for event in all_events.values():
            merged.append(event)

        return merged

    def causal_order(self) -> List[DistributedCausalEvent]:
        """
        Return all events sorted in causal order.

        Events are ordered by:

        1. Topological happens-before order (A → B ⟹ A comes first).
        2. Concurrent events: deterministic tiebreak by
           ``(source_node, seq_no)``.
        """
        return _topological_sort(list(self._events.values()))

    def conflicts(self) -> List[Tuple[DistributedCausalEvent, DistributedCausalEvent]]:
        """
        Return all pairs of concurrent events that mutate the same state key.

        These are the pairs that require conflict resolution during merge.
        """
        events = list(self._events.values())
        found: List[Tuple[DistributedCausalEvent, DistributedCausalEvent]] = []
        for i, ev_a in enumerate(events):
            for ev_b in events[i + 1:]:
                if not ev_a.concurrent_with(ev_b):
                    continue
                shared_keys = set(ev_a.state_mutations) & set(ev_b.state_mutations)
                if shared_keys:
                    found.append((ev_a, ev_b))
        return found

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        return f"DistributedEventLog(owner={self.owner_node!r}, events={len(self._events)})"


# ===========================================================================
# Causal Node Runtime
# ===========================================================================

class CausalNodeRuntime:
    """
    One RS-CCE node in a distributed causal system.

    Wraps an optional causal graph and adds:

    * A :class:`VectorClock` for causal ordering.
    * A local :class:`DistributedEventLog`.
    * :meth:`emit` — produce :class:`DistributedCausalEvent` objects.
    * :meth:`receive` — ingest events from other nodes and update the clock.
    * :meth:`sync` — merge another node's log into this one.

    Usage::

        node_a = CausalNodeRuntime("A", graph_a, peers=["B"])
        node_b = CausalNodeRuntime("B", graph_b, peers=["A"])

        # A emits, B receives
        ev = node_a.emit("cpu_spike", data={"value": 95})
        node_b.receive(ev)

        # Check causal ordering
        ev_b = node_b.emit("alert", data={"level": "high"})
        assert ev.happens_before(ev_b)

        # Sync logs
        merged = node_a.sync(node_b.log)
    """

    def __init__(
        self,
        node_id: str,
        graph: Any = None,
        peers: Optional[List[str]] = None,
    ) -> None:
        self.node_id = node_id
        self.graph = graph
        self.clock = VectorClock(node_id, peers=peers or [])
        self.log = DistributedEventLog(node_id)
        self._seq: int = 0

    def emit(
        self,
        event_type: str,
        data: Any = None,
        state_mutations: Optional[Dict[str, Any]] = None,
    ) -> DistributedCausalEvent:
        """
        Emit a new event from this node.

        Increments the vector clock, creates a
        :class:`DistributedCausalEvent`, appends it to the local log, and
        returns it for forwarding to peer nodes.
        """
        self._seq += 1
        vc = self.clock.tick()
        event = DistributedCausalEvent(
            event_type=event_type,
            source_node=self.node_id,
            vector_clock=vc,
            data=data or {},
            local_timestamp=_time.time(),
            seq_no=self._seq,
            state_mutations=state_mutations or {},
        )
        self.log.append(event)
        return event

    def receive(self, event: DistributedCausalEvent) -> None:
        """
        Ingest an event received from another node.

        Updates the local vector clock and appends the event to the log.
        Receiving the same event multiple times is idempotent.
        """
        self.clock.update(event.vector_clock)
        self.log.append(event)

    def sync(
        self,
        other_log: DistributedEventLog,
        conflict_policy: ConflictPolicy = ConflictPolicy.LAST_WRITER_WINS,
    ) -> DistributedEventLog:
        """
        Merge *other_log* into this node's log.

        The local log is updated in-place with any new events from
        *other_log*, the local vector clock is updated, and the merged log
        is returned for inspection.
        """
        merged = self.log.merge(other_log, conflict_policy=conflict_policy)

        # Update local clock from all incoming events
        for ev in other_log.events:
            self.clock.update(ev.vector_clock)

        # Absorb new events into local log
        known_ids: Set[str] = {e.event_id for e in self.log.events}
        for ev in merged.events:
            if ev.event_id not in known_ids:
                self.log.append(ev)
                known_ids.add(ev.event_id)

        return merged

    def __repr__(self) -> str:
        return (
            f"CausalNodeRuntime("
            f"id={self.node_id!r}, "
            f"clock={self.clock.snapshot()}, "
            f"log_events={len(self.log)})"
        )


# ===========================================================================
# Internal helpers
# ===========================================================================

def _topological_sort(
    events: List[DistributedCausalEvent],
) -> List[DistributedCausalEvent]:
    """
    Sort *events* in causal order using Kahn's topological sort algorithm.

    Concurrent events are ordered deterministically by
    ``(source_node, seq_no)``.
    """
    if not events:
        return []

    n = len(events)
    in_degree = [0] * n
    successors: List[List[int]] = [[] for _ in range(n)]

    for i, ev_a in enumerate(events):
        for j, ev_b in enumerate(events):
            if i != j and VectorClock.happens_before(ev_a.vector_clock, ev_b.vector_clock):
                successors[i].append(j)
                in_degree[j] += 1

    # Min-heap: (tiebreak_key, index)
    heap: List[Tuple[Any, int]] = []
    for i, deg in enumerate(in_degree):
        if deg == 0:
            heapq.heappush(heap, ((events[i].source_node, events[i].seq_no), i))

    result: List[DistributedCausalEvent] = []
    while heap:
        _, idx = heapq.heappop(heap)
        result.append(events[idx])
        for j in successors[idx]:
            in_degree[j] -= 1
            if in_degree[j] == 0:
                heapq.heappush(heap, ((events[j].source_node, events[j].seq_no), j))

    # Safety: append any events skipped due to unexpected cycles
    seen_ids: Set[str] = {e.event_id for e in result}
    result.extend(e for e in events if e.event_id not in seen_ids)
    return result


def _resolve_conflicts(
    events: Dict[str, DistributedCausalEvent],
    policy: ConflictPolicy,
) -> Dict[str, DistributedCausalEvent]:
    """
    Apply *policy* to concurrent events that mutate the same state key.

    Returns a new dict with losing events removed.
    """
    ev_list = list(events.values())
    to_remove: Set[str] = set()

    for i, ev_a in enumerate(ev_list):
        for ev_b in ev_list[i + 1:]:
            if ev_a.event_id in to_remove or ev_b.event_id in to_remove:
                continue
            if not ev_a.concurrent_with(ev_b):
                continue
            shared_keys = set(ev_a.state_mutations) & set(ev_b.state_mutations)
            if not shared_keys:
                continue

            if policy == ConflictPolicy.LAST_WRITER_WINS:
                loser = ev_a if ev_a.seq_no < ev_b.seq_no else ev_b
            else:   # FIRST_WRITER_WINS
                loser = ev_a if ev_a.seq_no > ev_b.seq_no else ev_b

            to_remove.add(loser.event_id)

    return {eid: ev for eid, ev in events.items() if eid not in to_remove}
