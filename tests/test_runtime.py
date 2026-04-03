"""
Tests for the runtime components: StateStore, GraphMonitor, ExecutionLoop.
"""
import pytest

from core.causal_engine import CausalGraph
from core.event_bus import Event, EventBus
from core.node_types import ActionNode, ConditionNode, EventNode, NodeState
from reality_layers.base_layer import LayerStack
from reality_layers.deterministic_layer import DeterministicLayer
from runtime.state_store import StateStore
from runtime.graph_monitor import GraphMonitor
from runtime.execution_loop import ExecutionLoop


# ---------------------------------------------------------------------------
# StateStore tests
# ---------------------------------------------------------------------------

class TestStateStore:
    def test_set_and_get(self):
        store = StateStore()
        store.set("cpu_usage", 90)
        assert store.get("cpu_usage") == 90

    def test_get_default(self):
        store = StateStore()
        assert store.get("missing", 0) == 0

    def test_initial_values(self):
        store = StateStore({"a": 1, "b": 2})
        assert store.get("a") == 1
        assert store.get("b") == 2

    def test_update_bulk(self):
        store = StateStore()
        store.update({"x": 10, "y": 20})
        assert store.get("x") == 10
        assert store.get("y") == 20

    def test_delete(self):
        store = StateStore({"key": "val"})
        store.delete("key")
        assert store.get("key") is None
        assert "key" not in store

    def test_changelog_records_changes(self):
        store = StateStore()
        store.set("a", 1)
        store.set("a", 2)
        assert len(store.changelog) == 2
        assert store.changelog[0][3] == 1  # new value
        assert store.changelog[1][3] == 2

    def test_snapshot_returns_copy(self):
        store = StateStore({"a": 1})
        snap = store.snapshot()
        snap["a"] = 999
        assert store.get("a") == 1  # original unchanged

    def test_restore(self):
        store = StateStore({"a": 1, "b": 2})
        store.restore({"c": 3})
        assert store.get("a") is None
        assert store.get("c") == 3

    def test_replay_to(self):
        store = StateStore()
        store.set("a", 1)
        ts_mid = store.changelog[-1][0]
        store.set("a", 2)
        # Replay up to mid-point
        state = store.replay_to(ts_mid)
        assert state["a"] == 1

    def test_len_and_iter(self):
        store = StateStore({"x": 1, "y": 2})
        assert len(store) == 2
        assert set(store) == {"x", "y"}

    def test_clear_changelog(self):
        store = StateStore()
        store.set("a", 1)
        store.clear_changelog()
        assert store.changelog == []


# ---------------------------------------------------------------------------
# GraphMonitor tests
# ---------------------------------------------------------------------------

class TestGraphMonitor:
    def _make_graph_and_monitor(self):
        g = CausalGraph()
        cond = ConditionNode("cond", lambda ctx: True)
        act = ActionNode("act", lambda ctx: "result")
        g.add_node(cond)
        g.add_node(act)
        g.add_edge(cond, act)
        monitor = GraphMonitor(g)
        return g, cond, act, monitor

    def test_node_status_before_execution(self):
        _, cond, act, monitor = self._make_graph_and_monitor()
        status = monitor.node_status()
        assert status[cond.id]["state"] == "PENDING"
        assert status[act.id]["state"] == "PENDING"

    def test_node_status_after_execution(self):
        g, cond, act, monitor = self._make_graph_and_monitor()
        g.tick({})
        status = monitor.node_status()
        assert status[cond.id]["state"] == "DONE"
        assert status[act.id]["state"] == "DONE"

    def test_root_nodes(self):
        _, cond, act, monitor = self._make_graph_and_monitor()
        roots = monitor.root_nodes()
        assert any(r["id"] == cond.id for r in roots)
        assert not any(r["id"] == act.id for r in roots)

    def test_leaf_nodes(self):
        _, cond, act, monitor = self._make_graph_and_monitor()
        leaves = monitor.leaf_nodes()
        assert any(l["id"] == act.id for l in leaves)
        assert not any(l["id"] == cond.id for l in leaves)

    def test_edges_summary(self):
        _, cond, act, monitor = self._make_graph_and_monitor()
        edges = monitor.edges_summary()
        assert len(edges) == 1
        assert edges[0]["source"] == cond.name
        assert edges[0]["target"] == act.name

    def test_stats(self):
        g, _, _, monitor = self._make_graph_and_monitor()
        g.tick({})
        stats = monitor.stats()
        assert stats["total_nodes"] == 2
        assert stats["total_edges"] == 1
        assert stats["state_counts"]["DONE"] == 2
        assert stats["executions"] == 2

    def test_snapshot(self):
        g, _, _, monitor = self._make_graph_and_monitor()
        snap = monitor.snapshot()
        assert "nodes" in snap
        assert "edges" in snap
        assert "stats" in snap
        assert "history" in snap
        assert len(monitor.snapshots) == 1

    def test_summary_contains_node_names(self):
        _, cond, act, monitor = self._make_graph_and_monitor()
        summary = monitor.summary()
        assert cond.name in summary
        assert act.name in summary


# ---------------------------------------------------------------------------
# EventBus tests
# ---------------------------------------------------------------------------

class TestEventBus:
    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []
        bus.subscribe("cpu_usage", lambda e: received.append(e))
        bus.publish(Event("cpu_usage", {"value": 85}))
        assert len(received) == 1
        assert received[0].data["value"] == 85

    def test_wildcard_subscription(self):
        bus = EventBus()
        received = []
        bus.subscribe("*", lambda e: received.append(e.event_type))
        bus.publish(Event("a", {}))
        bus.publish(Event("b", {}))
        assert received == ["a", "b"]

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        cb = lambda e: received.append(e)
        bus.subscribe("x", cb)
        bus.unsubscribe("x", cb)
        bus.publish(Event("x", {}))
        assert received == []

    def test_history_and_get_events(self):
        bus = EventBus()
        bus.publish(Event("a", {}))
        bus.publish(Event("b", {}))
        bus.publish(Event("a", {}))
        assert len(bus.get_events()) == 3
        assert len(bus.get_events("a")) == 2

    def test_replay(self):
        bus = EventBus()
        received = []
        bus.subscribe("ping", lambda e: received.append("ping"))
        bus.publish(Event("ping", {}))
        count_before = len(received)
        bus.replay()
        assert len(received) == count_before * 2

    def test_clear_history(self):
        bus = EventBus()
        bus.publish(Event("x", {}))
        bus.clear_history()
        assert bus.get_events() == []


# ---------------------------------------------------------------------------
# ExecutionLoop tests
# ---------------------------------------------------------------------------

class TestExecutionLoop:
    def _make_loop(self):
        graph = CausalGraph()
        cond = ConditionNode("cond", lambda ctx: ctx.get("trigger", False))
        act = ActionNode("act", lambda ctx: {"acted": True})
        graph.add_node(cond)
        graph.add_node(act)
        graph.add_edge(cond, act)
        store = StateStore({"trigger": False})
        loop = ExecutionLoop(graph, state_store=store, max_ticks=50)
        return loop, graph, cond, act, store

    def test_tick_once_no_execution_when_condition_false(self):
        loop, graph, cond, act, store = self._make_loop()
        executed = loop.tick_once()
        assert cond in executed  # cond evaluated
        assert act not in executed  # act not triggered
        assert act.state == NodeState.PENDING

    def test_tick_once_executes_when_condition_true(self):
        loop, graph, cond, act, store = self._make_loop()
        store.set("trigger", True)
        executed = loop.tick_once()
        assert cond in executed
        assert act in executed
        assert act.state == NodeState.DONE

    def test_start_runs_until_quiescent(self):
        loop, graph, cond, act, store = self._make_loop()
        store.set("trigger", True)
        loop.start()
        assert act.state == NodeState.DONE

    def test_action_result_written_to_state(self):
        loop, graph, cond, act, store = self._make_loop()
        store.set("trigger", True)
        loop.tick_once()
        # act returns {"acted": True} — should be in state
        assert store.get("acted") is True

    def test_on_tick_callback(self):
        loop, _, _, _, store = self._make_loop()
        ticks_seen = []
        loop.on_tick(lambda l: ticks_seen.append(l.tick_count))
        loop.tick_once()
        assert 1 in ticks_seen

    def test_inject_rule_hot(self):
        """New rules can be injected into the running graph."""
        loop, graph, _, _, store = self._make_loop()
        results = []
        loop.inject_rule(
            "IF hotload > 1\nTHEN alert()",
            action_registry={"alert": lambda ctx, *a: results.append("alert")},
        )
        assert len(graph.nodes) == 4  # original 2 + new 2
        store.set("hotload", 5)
        loop.tick_once()
        assert "alert" in results

    def test_event_node_triggered_by_bus(self):
        graph = CausalGraph()
        ev = EventNode("cpu_event", "cpu_spike")
        results = []
        act = ActionNode("respond", lambda ctx: results.append("responded"))
        graph.add_node(ev)
        graph.add_node(act)
        graph.add_edge(ev, act)

        bus = EventBus()
        loop = ExecutionLoop(graph, event_bus=bus, max_ticks=10)
        bus.publish(Event("cpu_spike", {"value": 95}))
        loop.tick_once()
        assert "responded" in results

    def test_deterministic_layer_in_loop(self):
        graph = CausalGraph()
        times = []
        act = ActionNode("record_time", lambda ctx: times.append(ctx.get("__time__")))
        graph.add_node(act)

        stack = LayerStack()
        det = DeterministicLayer(start_time=1000.0, time_step=1.0)
        stack.push(det)

        loop = ExecutionLoop(graph, layer_stack=stack, max_ticks=5)
        loop.tick_once()
        assert times[0] == 1000.0
