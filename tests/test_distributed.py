"""
Tests for Upgrade 6 — Distributed Causal Consistency
(runtime/distributed_runtime.py).

Covers:
- VectorClock (tick, update, happens_before, concurrent)
- DistributedCausalEvent
- DistributedEventLog (append, merge, causal_order, conflicts)
- CausalNodeRuntime (emit, receive, sync)
- ConflictPolicy (LAST_WRITER_WINS, FIRST_WRITER_WINS, KEEP_BOTH)
- Deterministic merge (same result regardless of argument order)
"""
import pytest

from runtime.distributed_runtime import (
    CausalNodeRuntime,
    ConflictPolicy,
    DistributedCausalEvent,
    DistributedEventLog,
    VectorClock,
)


# ===========================================================================
# VectorClock
# ===========================================================================

class TestVectorClock:
    def test_initial_clock_has_zero_for_own_node(self):
        vc = VectorClock("A")
        assert vc.snapshot()["A"] == 0

    def test_initial_clock_includes_peers(self):
        vc = VectorClock("A", peers=["B", "C"])
        snap = vc.snapshot()
        assert snap["B"] == 0
        assert snap["C"] == 0

    def test_tick_increments_own_counter(self):
        vc = VectorClock("A")
        ts1 = vc.tick()
        ts2 = vc.tick()
        assert ts2["A"] == ts1["A"] + 1

    def test_tick_returns_snapshot(self):
        vc = VectorClock("A", peers=["B"])
        ts = vc.tick()
        assert isinstance(ts, dict)
        assert "A" in ts
        assert "B" in ts

    def test_update_merges_higher_values(self):
        vc = VectorClock("A")
        vc.update({"A": 5, "B": 3})
        snap = vc.snapshot()
        assert snap["A"] == 5
        assert snap["B"] == 3

    def test_update_does_not_lower_own_counter(self):
        vc = VectorClock("A")
        vc.tick()   # A=1
        vc.update({"A": 0})  # stale value — should be ignored
        assert vc.snapshot()["A"] == 1

    def test_happens_before_true(self):
        vc_a = {"A": 1, "B": 0}
        vc_b = {"A": 1, "B": 1}
        assert VectorClock.happens_before(vc_a, vc_b) is True

    def test_happens_before_false_when_equal(self):
        vc = {"A": 1, "B": 1}
        assert VectorClock.happens_before(vc, vc) is False

    def test_happens_before_false_when_b_before_a(self):
        vc_a = {"A": 2, "B": 0}
        vc_b = {"A": 0, "B": 2}
        assert VectorClock.happens_before(vc_a, vc_b) is False
        assert VectorClock.happens_before(vc_b, vc_a) is False

    def test_concurrent_when_neither_dominates(self):
        vc_a = {"A": 2, "B": 0}
        vc_b = {"A": 0, "B": 2}
        assert VectorClock.concurrent(vc_a, vc_b) is True

    def test_not_concurrent_when_one_before_other(self):
        vc_a = {"A": 1, "B": 0}
        vc_b = {"A": 2, "B": 0}
        assert VectorClock.concurrent(vc_a, vc_b) is False

    def test_causal_ordering_between_two_nodes(self):
        vc_a = VectorClock("A", peers=["B"])
        vc_b = VectorClock("B", peers=["A"])

        ts_a1 = vc_a.tick()           # A emits event 1
        vc_b.update(ts_a1)            # B receives from A
        ts_b1 = vc_b.tick()           # B emits event 1

        assert VectorClock.happens_before(ts_a1, ts_b1) is True

    def test_repr_contains_node_id(self):
        vc = VectorClock("myNode")
        assert "myNode" in repr(vc)


# ===========================================================================
# DistributedCausalEvent
# ===========================================================================

class TestDistributedCausalEvent:
    def _make_event(self, **kwargs) -> DistributedCausalEvent:
        defaults = dict(
            event_type="cpu_spike",
            source_node="A",
            vector_clock={"A": 1, "B": 0},
            data={"value": 95},
        )
        defaults.update(kwargs)
        return DistributedCausalEvent(**defaults)

    def test_event_has_unique_id(self):
        ev1 = self._make_event()
        ev2 = self._make_event()
        assert ev1.event_id != ev2.event_id

    def test_happens_before_delegation(self):
        ev_a = self._make_event(vector_clock={"A": 1, "B": 0})
        ev_b = self._make_event(vector_clock={"A": 1, "B": 1})
        assert ev_a.happens_before(ev_b) is True
        assert ev_b.happens_before(ev_a) is False

    def test_concurrent_with_delegation(self):
        ev_a = self._make_event(vector_clock={"A": 2, "B": 0})
        ev_b = self._make_event(vector_clock={"A": 0, "B": 2})
        assert ev_a.concurrent_with(ev_b) is True

    def test_repr_contains_type_and_source(self):
        ev = self._make_event(event_type="sig", source_node="nodeX")
        r = repr(ev)
        assert "sig" in r
        assert "nodeX" in r


# ===========================================================================
# DistributedEventLog
# ===========================================================================

class TestDistributedEventLog:
    def _make_log_pair(self):
        """Return two logs with one causally-ordered event chain."""
        vc_a = VectorClock("A", peers=["B"])
        vc_b = VectorClock("B", peers=["A"])

        log_a = DistributedEventLog("A")
        log_b = DistributedEventLog("B")

        ev_a = DistributedCausalEvent("e_a", "A", vc_a.tick(), seq_no=1)
        vc_b.update(ev_a.vector_clock)
        ev_b = DistributedCausalEvent("e_b", "B", vc_b.tick(), seq_no=1)

        log_a.append(ev_a)
        log_b.append(ev_b)
        return log_a, log_b, ev_a, ev_b

    def test_append_stores_event(self):
        log = DistributedEventLog("X")
        ev = DistributedCausalEvent("t", "X", {"X": 1})
        log.append(ev)
        assert len(log) == 1

    def test_append_is_idempotent(self):
        log = DistributedEventLog("X")
        ev = DistributedCausalEvent("t", "X", {"X": 1})
        log.append(ev)
        log.append(ev)  # same event_id
        assert len(log) == 1

    def test_merge_contains_all_events(self):
        log_a, log_b, ev_a, ev_b = self._make_log_pair()
        merged = log_a.merge(log_b)
        ids = {e.event_id for e in merged.events}
        assert ev_a.event_id in ids
        assert ev_b.event_id in ids

    def test_merge_deduplicates(self):
        log_a, log_b, ev_a, _ = self._make_log_pair()
        log_b.append(ev_a)  # add ev_a to log_b too
        merged = log_a.merge(log_b)
        # ev_a should appear only once
        count = sum(1 for e in merged.events if e.event_id == ev_a.event_id)
        assert count == 1

    def test_causal_order_respects_happens_before(self):
        log_a, log_b, ev_a, ev_b = self._make_log_pair()
        merged = log_a.merge(log_b)
        ordered = merged.causal_order()
        ids = [e.event_id for e in ordered]
        assert ids.index(ev_a.event_id) < ids.index(ev_b.event_id)

    def test_causal_order_is_deterministic(self):
        log_a, log_b, _, _ = self._make_log_pair()
        merged1 = log_a.merge(log_b)
        merged2 = log_a.merge(log_b)
        assert [e.event_id for e in merged1.causal_order()] == \
               [e.event_id for e in merged2.causal_order()]

    def test_merge_deterministic_regardless_of_order(self):
        """merge(A, B) and merge(B, A) must have the same causal order."""
        log_a, log_b, _, _ = self._make_log_pair()
        order_ab = [e.event_id for e in log_a.merge(log_b).causal_order()]
        order_ba = [e.event_id for e in log_b.merge(log_a).causal_order()]
        assert order_ab == order_ba

    def test_conflicts_detects_concurrent_mutation(self):
        log = DistributedEventLog("merged")
        ev_a = DistributedCausalEvent(
            "cpu_write", "A", {"A": 1, "B": 0}, seq_no=1,
            state_mutations={"cpu_throttle": True},
        )
        ev_b = DistributedCausalEvent(
            "cpu_write", "B", {"A": 0, "B": 1}, seq_no=1,
            state_mutations={"cpu_throttle": False},
        )
        log.append(ev_a)
        log.append(ev_b)
        conflicts = log.conflicts()
        assert len(conflicts) == 1

    def test_no_conflict_when_events_are_ordered(self):
        vc_a = VectorClock("A", peers=["B"])
        vc_b = VectorClock("B", peers=["A"])
        ts_a = vc_a.tick()
        vc_b.update(ts_a)
        ts_b = vc_b.tick()
        log = DistributedEventLog("merged")
        ev_a = DistributedCausalEvent("w", "A", ts_a, seq_no=1,
                                       state_mutations={"k": 1})
        ev_b = DistributedCausalEvent("w", "B", ts_b, seq_no=1,
                                       state_mutations={"k": 2})
        log.append(ev_a)
        log.append(ev_b)
        assert log.conflicts() == []

    def test_last_writer_wins_removes_lower_seq(self):
        log = DistributedEventLog("merged")
        ev_a = DistributedCausalEvent(
            "w", "A", {"A": 1, "B": 0}, seq_no=5,
            state_mutations={"k": "a"},
        )
        ev_b = DistributedCausalEvent(
            "w", "B", {"A": 0, "B": 1}, seq_no=3,
            state_mutations={"k": "b"},
        )
        log.append(ev_a)
        log.append(ev_b)
        merged = log.merge(DistributedEventLog("empty"),
                           conflict_policy=ConflictPolicy.LAST_WRITER_WINS)
        ids = {e.event_id for e in merged.events}
        # ev_a has higher seq_no — wins; ev_b removed
        assert ev_a.event_id in ids
        assert ev_b.event_id not in ids

    def test_first_writer_wins_removes_higher_seq(self):
        log = DistributedEventLog("merged")
        ev_a = DistributedCausalEvent(
            "w", "A", {"A": 1, "B": 0}, seq_no=5,
            state_mutations={"k": "a"},
        )
        ev_b = DistributedCausalEvent(
            "w", "B", {"A": 0, "B": 1}, seq_no=3,
            state_mutations={"k": "b"},
        )
        log.append(ev_a)
        log.append(ev_b)
        merged = log.merge(DistributedEventLog("empty"),
                           conflict_policy=ConflictPolicy.FIRST_WRITER_WINS)
        ids = {e.event_id for e in merged.events}
        # ev_b has lower seq_no — wins; ev_a removed
        assert ev_b.event_id in ids
        assert ev_a.event_id not in ids

    def test_keep_both_retains_conflicting_events(self):
        log = DistributedEventLog("merged")
        ev_a = DistributedCausalEvent(
            "w", "A", {"A": 1, "B": 0}, seq_no=1,
            state_mutations={"k": "a"},
        )
        ev_b = DistributedCausalEvent(
            "w", "B", {"A": 0, "B": 1}, seq_no=2,
            state_mutations={"k": "b"},
        )
        log.append(ev_a)
        log.append(ev_b)
        merged = log.merge(DistributedEventLog("empty"),
                           conflict_policy=ConflictPolicy.KEEP_BOTH)
        ids = {e.event_id for e in merged.events}
        assert ev_a.event_id in ids
        assert ev_b.event_id in ids

    def test_repr_contains_owner_and_count(self):
        log = DistributedEventLog("nodeX")
        r = repr(log)
        assert "nodeX" in r
        assert "events=" in r


# ===========================================================================
# CausalNodeRuntime
# ===========================================================================

class TestCausalNodeRuntime:
    def test_emit_increments_own_clock(self):
        node = CausalNodeRuntime("A", peers=["B"])
        ev1 = node.emit("e1")
        ev2 = node.emit("e2")
        assert ev2.vector_clock["A"] == ev1.vector_clock["A"] + 1

    def test_emit_appends_to_local_log(self):
        node = CausalNodeRuntime("A")
        node.emit("e1")
        node.emit("e2")
        assert len(node.log) == 2

    def test_emit_assigns_sequential_seq_no(self):
        node = CausalNodeRuntime("A")
        ev1 = node.emit("e1")
        ev2 = node.emit("e2")
        assert ev1.seq_no == 1
        assert ev2.seq_no == 2

    def test_emit_records_source_node(self):
        node = CausalNodeRuntime("myNode")
        ev = node.emit("e")
        assert ev.source_node == "myNode"

    def test_receive_updates_clock(self):
        node_a = CausalNodeRuntime("A", peers=["B"])
        node_b = CausalNodeRuntime("B", peers=["A"])
        ev = node_a.emit("from_a")
        node_b.receive(ev)
        # B's clock should reflect A's contribution
        assert node_b.clock.snapshot().get("A", 0) >= ev.vector_clock["A"]

    def test_receive_appends_to_log(self):
        node_a = CausalNodeRuntime("A", peers=["B"])
        node_b = CausalNodeRuntime("B", peers=["A"])
        ev = node_a.emit("e")
        node_b.receive(ev)
        assert len(node_b.log) == 1

    def test_receive_is_idempotent(self):
        node_a = CausalNodeRuntime("A", peers=["B"])
        node_b = CausalNodeRuntime("B", peers=["A"])
        ev = node_a.emit("e")
        node_b.receive(ev)
        node_b.receive(ev)  # duplicate
        assert len(node_b.log) == 1

    def test_event_from_a_happens_before_subsequent_b_event(self):
        node_a = CausalNodeRuntime("A", peers=["B"])
        node_b = CausalNodeRuntime("B", peers=["A"])
        ev_a = node_a.emit("ping")
        node_b.receive(ev_a)
        ev_b = node_b.emit("pong")
        assert VectorClock.happens_before(ev_a.vector_clock, ev_b.vector_clock)

    def test_sync_merges_other_log_into_local(self):
        node_a = CausalNodeRuntime("A", peers=["B"])
        node_b = CausalNodeRuntime("B", peers=["A"])
        node_a.emit("e1")
        node_b.emit("e2")
        node_a.sync(node_b.log)
        # node_a's log now contains both events
        ids = {e.event_id for e in node_a.log.events}
        assert any(e.event_type == "e2" for e in node_a.log.events)

    def test_sync_updates_local_clock(self):
        node_a = CausalNodeRuntime("A", peers=["B"])
        node_b = CausalNodeRuntime("B", peers=["A"])
        node_b.emit("from_b")
        before = node_a.clock.snapshot().get("B", 0)
        node_a.sync(node_b.log)
        after = node_a.clock.snapshot().get("B", 0)
        assert after > before

    def test_sync_returns_merged_log(self):
        node_a = CausalNodeRuntime("A", peers=["B"])
        node_b = CausalNodeRuntime("B", peers=["A"])
        node_a.emit("e_a")
        node_b.emit("e_b")
        merged = node_a.sync(node_b.log)
        assert isinstance(merged, DistributedEventLog)
        assert len(merged) >= 2

    def test_repr_contains_node_id(self):
        node = CausalNodeRuntime("myNode")
        assert "myNode" in repr(node)


# ===========================================================================
# End-to-end: three-node distributed scenario
# ===========================================================================

class TestDistributedScenario:
    def test_three_node_causal_consistency(self):
        """
        A → B → C chain: each node receives from its predecessor.
        The merged log must reflect the causal ordering A→B→C.
        """
        a = CausalNodeRuntime("A", peers=["B", "C"])
        b = CausalNodeRuntime("B", peers=["A", "C"])
        c = CausalNodeRuntime("C", peers=["A", "B"])

        ev_a = a.emit("step_a", data={"v": 1})
        b.receive(ev_a)
        ev_b = b.emit("step_b", data={"v": 2})
        c.receive(ev_b)
        ev_c = c.emit("step_c", data={"v": 3})

        # Build full merged log on node A
        a.sync(b.log)
        a.sync(c.log)
        ordered = a.log.causal_order()
        ids = [e.event_id for e in ordered]
        assert ids.index(ev_a.event_id) < ids.index(ev_b.event_id)
        assert ids.index(ev_b.event_id) < ids.index(ev_c.event_id)

    def test_independent_events_are_concurrent(self):
        a = CausalNodeRuntime("A", peers=["B"])
        b = CausalNodeRuntime("B", peers=["A"])
        ev_a = a.emit("independent_a")
        ev_b = b.emit("independent_b")
        assert ev_a.concurrent_with(ev_b)

    def test_deterministic_merge_same_result_both_ways(self):
        a = CausalNodeRuntime("A", peers=["B"])
        b = CausalNodeRuntime("B", peers=["A"])
        a.emit("e1")
        a.emit("e2")
        b.emit("e3")

        merged_ab = a.log.merge(b.log)
        merged_ba = b.log.merge(a.log)

        ids_ab = [e.event_id for e in merged_ab.causal_order()]
        ids_ba = [e.event_id for e in merged_ba.causal_order()]
        assert ids_ab == ids_ba

    def test_conflict_resolution_produces_valid_log(self):
        a = CausalNodeRuntime("A", peers=["B"])
        b = CausalNodeRuntime("B", peers=["A"])

        a.emit("update", state_mutations={"cpu_limit": 80})
        b.emit("update", state_mutations={"cpu_limit": 90})

        merged = a.log.merge(b.log, conflict_policy=ConflictPolicy.LAST_WRITER_WINS)
        # Exactly one event should survive the conflict
        limit_events = [e for e in merged.events if "cpu_limit" in e.state_mutations]
        assert len(limit_events) == 1
