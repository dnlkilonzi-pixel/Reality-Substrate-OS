"""
Tests for the causal graph engine and node types.
"""
import pytest

from core.node_types import (
    ActionNode,
    ConditionNode,
    EventNode,
    NodeState,
    TransformNode,
)
from core.causal_engine import CausalEdge, CausalGraph


# ---------------------------------------------------------------------------
# NodeState tests
# ---------------------------------------------------------------------------

class TestNodeState:
    def test_all_states_exist(self):
        assert NodeState.PENDING
        assert NodeState.READY
        assert NodeState.EXECUTING
        assert NodeState.DONE
        assert NodeState.FAILED


# ---------------------------------------------------------------------------
# EventNode tests
# ---------------------------------------------------------------------------

class TestEventNode:
    def test_initial_state(self):
        node = EventNode("cpu_signal", "cpu_usage")
        assert node.state == NodeState.PENDING
        assert not node.is_triggered

    def test_trigger_transitions_to_ready(self):
        node = EventNode("cpu_signal", "cpu_usage")
        node.trigger(value=85)
        assert node.state == NodeState.READY
        assert node.is_triggered

    def test_execute_sets_done_and_returns_value(self):
        node = EventNode("cpu_signal", "cpu_usage")
        node.trigger(value={"metric": 90})
        result = node.execute({})
        assert node.state == NodeState.DONE
        assert result == {"metric": 90}
        assert node.result == {"metric": 90}

    def test_reset_clears_trigger(self):
        node = EventNode("cpu_signal", "cpu_usage")
        node.trigger(99)
        node.execute({})
        node.reset()
        assert node.state == NodeState.PENDING
        assert node.result is None


# ---------------------------------------------------------------------------
# ConditionNode tests
# ---------------------------------------------------------------------------

class TestConditionNode:
    def test_condition_true(self):
        node = ConditionNode("high_cpu", lambda ctx: ctx.get("cpu_usage", 0) > 80)
        result = node.execute({"cpu_usage": 90})
        assert result is True
        assert node.state == NodeState.DONE

    def test_condition_false_stays_pending(self):
        node = ConditionNode("high_cpu", lambda ctx: ctx.get("cpu_usage", 0) > 80)
        result = node.execute({"cpu_usage": 50})
        assert result is False
        assert node.state == NodeState.PENDING

    def test_condition_exception_sets_failed(self):
        def bad_pred(ctx):
            raise ValueError("oops")

        node = ConditionNode("bad", bad_pred)
        with pytest.raises(RuntimeError, match="bad"):
            node.execute({})
        assert node.state == NodeState.FAILED

    def test_reset(self):
        node = ConditionNode("cond", lambda ctx: True)
        node.execute({})
        node.reset()
        assert node.state == NodeState.PENDING


# ---------------------------------------------------------------------------
# ActionNode tests
# ---------------------------------------------------------------------------

class TestActionNode:
    def test_action_executes_and_stores_result(self):
        results = []
        node = ActionNode("log", lambda ctx: results.append("logged") or "ok")
        ret = node.execute({})
        assert ret == "ok"
        assert node.state == NodeState.DONE
        assert results == ["logged"]

    def test_action_exception_sets_failed(self):
        node = ActionNode("bad_act", lambda ctx: (_ for _ in ()).throw(RuntimeError("fail")))
        with pytest.raises(RuntimeError):
            node.execute({})
        assert node.state == NodeState.FAILED


# ---------------------------------------------------------------------------
# TransformNode tests
# ---------------------------------------------------------------------------

class TestTransformNode:
    def test_transform_doubles_value(self):
        node = TransformNode("double", lambda ctx: ctx["x"] * 2)
        result = node.execute({"x": 21})
        assert result == 42
        assert node.state == NodeState.DONE

    def test_transform_exception_sets_failed(self):
        node = TransformNode("bad_tf", lambda ctx: 1 / 0)
        with pytest.raises(RuntimeError):
            node.execute({})
        assert node.state == NodeState.FAILED


# ---------------------------------------------------------------------------
# CausalGraph tests
# ---------------------------------------------------------------------------

class TestCausalGraph:
    def _simple_graph(self):
        """Returns (graph, cond_node, action_node) with one edge."""
        g = CausalGraph()
        cond = ConditionNode("cond", lambda ctx: ctx.get("x", 0) > 5)
        act = ActionNode("act", lambda ctx: "done")
        g.add_node(cond)
        g.add_node(act)
        g.add_edge(cond, act)
        return g, cond, act

    def test_add_node_and_edge(self):
        g, cond, act = self._simple_graph()
        assert len(g.nodes) == 2
        assert len(g.edges) == 1

    def test_predecessors_and_successors(self):
        g, cond, act = self._simple_graph()
        assert g.predecessors(act) == [cond]
        assert g.successors(cond) == [act]
        assert g.predecessors(cond) == []

    def test_root_nodes(self):
        g, cond, act = self._simple_graph()
        roots = g.get_root_nodes()
        assert cond in roots
        assert act not in roots

    def test_get_ready_nodes_no_predecessors_satisfied(self):
        g, cond, act = self._simple_graph()
        # cond is a root, act needs cond to be DONE first
        ready = g.get_ready_nodes()
        assert cond in ready
        assert act not in ready

    def test_tick_executes_condition_when_true(self):
        g, cond, act = self._simple_graph()
        executed = g.tick({"x": 10})
        # cond is True → both cond and act should execute
        assert cond in executed
        assert act in executed
        assert cond.state == NodeState.DONE
        assert act.state == NodeState.DONE

    def test_tick_stops_at_false_condition(self):
        g, cond, act = self._simple_graph()
        executed = g.tick({"x": 1})  # condition is False
        # cond executes and returns False; act should NOT execute
        assert cond in executed
        assert act not in executed
        assert act.state == NodeState.PENDING

    def test_multiple_ticks_do_not_re_execute_done_nodes(self):
        g, cond, act = self._simple_graph()
        g.tick({"x": 10})
        first_history_len = len(g.execution_history)
        g.tick({"x": 10})  # both nodes are DONE, nothing re-executes
        assert len(g.execution_history) == first_history_len

    def test_reset_clears_history_and_states(self):
        g, cond, act = self._simple_graph()
        g.tick({"x": 10})
        g.reset()
        assert cond.state == NodeState.PENDING
        assert act.state == NodeState.PENDING
        assert g.execution_history == []

    def test_add_edge_requires_registered_nodes(self):
        g = CausalGraph()
        n1 = ConditionNode("c", lambda ctx: True)
        n2 = ActionNode("a", lambda ctx: None)
        g.add_node(n1)
        with pytest.raises(ValueError, match="not registered"):
            g.add_edge(n1, n2)

    def test_three_node_chain(self):
        """cond → act1 → act2 should all execute in one tick."""
        g = CausalGraph()
        cond = ConditionNode("cond", lambda ctx: True)
        act1 = ActionNode("act1", lambda ctx: "first")
        act2 = ActionNode("act2", lambda ctx: "second")
        g.add_node(cond)
        g.add_node(act1)
        g.add_node(act2)
        g.add_edge(cond, act1)
        g.add_edge(act1, act2)
        executed = g.tick({})
        assert len(executed) == 3
        assert act2.state == NodeState.DONE

    def test_event_node_not_ready_without_trigger(self):
        g = CausalGraph()
        ev = EventNode("ev", "some_event")
        g.add_node(ev)
        ready = g.get_ready_nodes()
        assert ev not in ready

    def test_event_node_ready_after_trigger(self):
        g = CausalGraph()
        ev = EventNode("ev", "some_event")
        g.add_node(ev)
        ev.trigger("payload")
        ready = g.get_ready_nodes()
        assert ev in ready
