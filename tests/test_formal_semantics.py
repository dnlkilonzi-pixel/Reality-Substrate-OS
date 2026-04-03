"""
Tests for Upgrade 4 — Formal Semantics (core/formal_semantics.py).

Covers:
- GraphDelta dataclass
- CausalSemantics.transition()
- CausalSemantics.activation_satisfied()
- CausalSemantics.evolve()
- CausalSemantics.ready_set()
- CausalSemantics.causal_depth()
- CausalSemantics.reachable()
"""
import pytest

from core.causal_engine import CausalEdge, CausalGraph
from core.formal_semantics import CausalSemantics, GraphDelta
from core.node_types import ActionNode, ConditionNode, EventNode, NodeState, TransformNode


# ===========================================================================
# GraphDelta
# ===========================================================================

class TestGraphDelta:
    def test_is_empty_when_no_changes(self):
        assert GraphDelta().is_empty() is True

    def test_not_empty_with_added_node(self):
        n = ActionNode("n", lambda ctx: None)
        assert GraphDelta(nodes_added=[n]).is_empty() is False

    def test_not_empty_with_removed_node(self):
        assert GraphDelta(nodes_removed=["abc"]).is_empty() is False

    def test_not_empty_with_added_edge(self):
        edge = CausalEdge(source_id="a", target_id="b")
        assert GraphDelta(edges_added=[edge]).is_empty() is False

    def test_not_empty_with_removed_edge(self):
        assert GraphDelta(edges_removed=[("a", "b")]).is_empty() is False

    def test_repr_shows_counts(self):
        n = ActionNode("n", lambda ctx: None)
        delta = GraphDelta(nodes_added=[n], nodes_removed=["x"])
        r = repr(delta)
        assert "+1 nodes" in r
        assert "-1 nodes" in r


# ===========================================================================
# CausalSemantics.transition()
# ===========================================================================

class TestTransition:
    def _simple_graph(self) -> tuple:
        """Build: ConditionNode(cpu > 80) → ActionNode(throttle → {throttled: True})"""
        g = CausalGraph()
        results = []
        cond = ConditionNode("high_cpu", lambda ctx: ctx.get("cpu", 0) > 80,
                             metadata={"metric": "cpu"})
        act = ActionNode("throttle", lambda ctx: (results.append("fired"), {"throttled": True})[1])
        g.add_node(cond).add_node(act)
        g.add_edge(cond, act)
        return g, cond, act, results

    def test_transition_returns_next_state(self):
        g, _, _, _ = self._simple_graph()
        s_next = CausalSemantics.transition({"cpu": 90}, g)
        assert s_next.get("throttled") is True

    def test_transition_no_activation_when_condition_false(self):
        g, _, _, results = self._simple_graph()
        s_next = CausalSemantics.transition({"cpu": 50}, g)
        assert s_next.get("throttled") is None
        assert results == []

    def test_transition_does_not_modify_input_state(self):
        g, _, _, _ = self._simple_graph()
        original = {"cpu": 90}
        CausalSemantics.transition(original, g)
        assert original == {"cpu": 90}

    def test_transition_with_events(self):
        g = CausalGraph()
        results = []
        ev_node = EventNode("sig", "my_signal")
        act = ActionNode("handle", lambda ctx: (results.append("handled"), {"handled": True})[1])
        g.add_node(ev_node).add_node(act)
        g.add_edge(ev_node, act)

        s_next = CausalSemantics.transition(
            {},
            g,
            events=[{"event_type": "my_signal", "data": {"val": 1}}],
        )
        assert s_next.get("handled") is True

    def test_transition_propagates_through_chain(self):
        g = CausalGraph()
        cond = ConditionNode("c", lambda ctx: ctx.get("x", 0) > 0)
        act1 = ActionNode("a1", lambda ctx: {"step1": True})
        act2 = ActionNode("a2", lambda ctx: {"step2": True})
        g.add_node(cond).add_node(act1).add_node(act2)
        g.add_edge(cond, act1)
        g.add_edge(act1, act2)

        s_next = CausalSemantics.transition({"x": 1}, g)
        assert s_next.get("step1") is True
        assert s_next.get("step2") is True


# ===========================================================================
# CausalSemantics.activation_satisfied()
# ===========================================================================

class TestActivationSatisfied:
    def test_condition_node_true(self):
        g = CausalGraph()
        cond = ConditionNode("c", lambda ctx: ctx.get("x", 0) > 0)
        g.add_node(cond)
        assert CausalSemantics.activation_satisfied(cond, g, {"x": 1}) is True

    def test_condition_node_false(self):
        g = CausalGraph()
        cond = ConditionNode("c", lambda ctx: ctx.get("x", 0) > 0)
        g.add_node(cond)
        assert CausalSemantics.activation_satisfied(cond, g, {"x": 0}) is False

    def test_action_node_requires_predecessor_done(self):
        g = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        g.add_node(n1).add_node(n2)
        g.add_edge(n1, n2)

        # n1 is PENDING — n2 not satisfied
        assert CausalSemantics.activation_satisfied(n2, g, {}) is False

        # Mark n1 DONE — n2 now satisfied
        n1.state = NodeState.DONE
        assert CausalSemantics.activation_satisfied(n2, g, {}) is True

    def test_root_action_node_always_satisfied(self):
        g = CausalGraph()
        n = ActionNode("n", lambda ctx: None)
        g.add_node(n)
        assert CausalSemantics.activation_satisfied(n, g, {}) is True

    def test_event_node_requires_trigger(self):
        g = CausalGraph()
        ev = EventNode("ev", "sig")
        g.add_node(ev)
        assert CausalSemantics.activation_satisfied(ev, g, {}) is False
        ev.trigger({"val": 1})
        assert CausalSemantics.activation_satisfied(ev, g, {}) is True

    def test_condition_node_predecessor_not_done(self):
        g = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        cond = ConditionNode("c", lambda ctx: ctx.get("x", 0) > 0)
        g.add_node(n1).add_node(cond)
        g.add_edge(n1, cond)
        # n1 is PENDING, so cond is not satisfied even if predicate would be true
        assert CausalSemantics.activation_satisfied(cond, g, {"x": 5}) is False

    def test_faulty_predicate_returns_false(self):
        g = CausalGraph()
        cond = ConditionNode("c", lambda ctx: 1 / 0)  # always raises
        g.add_node(cond)
        assert CausalSemantics.activation_satisfied(cond, g, {}) is False


# ===========================================================================
# CausalSemantics.evolve()
# ===========================================================================

class TestEvolve:
    def _base_graph(self):
        g = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        g.add_node(n1).add_node(n2)
        g.add_edge(n1, n2)
        return g, n1, n2

    def test_evolve_adds_node(self):
        g, n1, _ = self._base_graph()
        n3 = ActionNode("n3", lambda ctx: None)
        delta = GraphDelta(nodes_added=[n3])
        g_prime = CausalSemantics.evolve(g, delta)
        ids = [n.id for n in g_prime.nodes]
        assert n3.id in ids
        assert len(g_prime.nodes) == 3

    def test_evolve_adds_edge(self):
        g, n1, n2 = self._base_graph()
        n3 = ActionNode("n3", lambda ctx: None)
        delta = GraphDelta(
            nodes_added=[n3],
            edges_added=[CausalEdge(source_id=n2.id, target_id=n3.id)],
        )
        g_prime = CausalSemantics.evolve(g, delta)
        assert len(g_prime.edges) == 2

    def test_evolve_removes_node(self):
        g, n1, n2 = self._base_graph()
        delta = GraphDelta(nodes_removed=[n1.id])
        g_prime = CausalSemantics.evolve(g, delta)
        ids = [n.id for n in g_prime.nodes]
        assert n1.id not in ids
        # Edge incident to n1 is also gone
        assert len(g_prime.edges) == 0

    def test_evolve_removes_edge_only(self):
        g, n1, n2 = self._base_graph()
        delta = GraphDelta(edges_removed=[(n1.id, n2.id)])
        g_prime = CausalSemantics.evolve(g, delta)
        assert len(g_prime.edges) == 0
        assert len(g_prime.nodes) == 2  # nodes preserved

    def test_evolve_is_non_destructive(self):
        g, n1, n2 = self._base_graph()
        original_node_count = len(g.nodes)
        original_edge_count = len(g.edges)
        n3 = ActionNode("n3", lambda ctx: None)
        delta = GraphDelta(nodes_added=[n3], nodes_removed=[n1.id])
        CausalSemantics.evolve(g, delta)
        assert len(g.nodes) == original_node_count
        assert len(g.edges) == original_edge_count

    def test_evolve_empty_delta_returns_equivalent_graph(self):
        g, n1, n2 = self._base_graph()
        g_prime = CausalSemantics.evolve(g, GraphDelta())
        assert len(g_prime.nodes) == len(g.nodes)
        assert len(g_prime.edges) == len(g.edges)

    def test_evolve_raises_on_edge_with_missing_source(self):
        g, n1, n2 = self._base_graph()
        n3 = ActionNode("n3", lambda ctx: None)
        bad_edge = CausalEdge(source_id="nonexistent", target_id=n3.id)
        delta = GraphDelta(nodes_added=[n3], edges_added=[bad_edge])
        with pytest.raises(ValueError, match="not present"):
            CausalSemantics.evolve(g, delta)

    def test_evolve_raises_on_edge_with_missing_target(self):
        g, n1, n2 = self._base_graph()
        bad_edge = CausalEdge(source_id=n1.id, target_id="nonexistent")
        delta = GraphDelta(edges_added=[bad_edge])
        with pytest.raises(ValueError, match="not present"):
            CausalSemantics.evolve(g, delta)

    def test_evolve_no_duplicate_edges(self):
        g, n1, n2 = self._base_graph()
        # Adding the same edge that already exists
        dup_edge = CausalEdge(source_id=n1.id, target_id=n2.id)
        delta = GraphDelta(edges_added=[dup_edge])
        g_prime = CausalSemantics.evolve(g, delta)
        assert len(g_prime.edges) == 1


# ===========================================================================
# CausalSemantics.ready_set()
# ===========================================================================

class TestReadySet:
    def test_root_nodes_with_satisfied_conditions_are_ready(self):
        g = CausalGraph()
        cond = ConditionNode("c", lambda ctx: ctx.get("x", 0) > 0)
        g.add_node(cond)
        ready = CausalSemantics.ready_set(g, {"x": 1})
        assert cond in ready

    def test_downstream_node_not_ready_until_upstream_done(self):
        g = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        g.add_node(n1).add_node(n2)
        g.add_edge(n1, n2)
        # n1 is root and PENDING — should be ready; n2 should not
        ready_ids = {n.id for n in CausalSemantics.ready_set(g, {})}
        assert n1.id in ready_ids
        assert n2.id not in ready_ids

    def test_already_done_nodes_excluded(self):
        g = CausalGraph()
        n = ActionNode("n", lambda ctx: None)
        g.add_node(n)
        n.state = NodeState.DONE
        assert CausalSemantics.ready_set(g, {}) == []


# ===========================================================================
# CausalSemantics.causal_depth()
# ===========================================================================

class TestCausalDepth:
    def test_root_node_has_depth_zero(self):
        g = CausalGraph()
        n = ActionNode("n", lambda ctx: None)
        g.add_node(n)
        assert CausalSemantics.causal_depth(n, g) == 0

    def test_one_level_deep(self):
        g = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        g.add_node(n1).add_node(n2)
        g.add_edge(n1, n2)
        assert CausalSemantics.causal_depth(n2, g) == 1

    def test_deep_chain(self):
        g = CausalGraph()
        nodes = [ActionNode(f"n{i}", lambda ctx: None) for i in range(5)]
        for n in nodes:
            g.add_node(n)
        for i in range(4):
            g.add_edge(nodes[i], nodes[i + 1])
        assert CausalSemantics.causal_depth(nodes[4], g) == 4

    def test_diamond_uses_longest_path(self):
        # n0 → n1 → n3
        # n0 → n2 → n2b → n3
        g = CausalGraph()
        n0 = ActionNode("n0", lambda ctx: None)
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        n2b = ActionNode("n2b", lambda ctx: None)
        n3 = ActionNode("n3", lambda ctx: None)
        for n in [n0, n1, n2, n2b, n3]:
            g.add_node(n)
        g.add_edge(n0, n1)
        g.add_edge(n0, n2)
        g.add_edge(n1, n3)
        g.add_edge(n2, n2b)
        g.add_edge(n2b, n3)
        assert CausalSemantics.causal_depth(n3, g) == 3  # longest: n0→n2→n2b→n3


# ===========================================================================
# CausalSemantics.reachable()
# ===========================================================================

class TestReachable:
    def test_reachable_from_root(self):
        g = CausalGraph()
        n0 = ActionNode("n0", lambda ctx: None)
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        for n in [n0, n1, n2]:
            g.add_node(n)
        g.add_edge(n0, n1)
        g.add_edge(n1, n2)
        reachable = CausalSemantics.reachable(n0, g)
        ids = [n.id for n in reachable]
        assert n1.id in ids
        assert n2.id in ids
        assert n0.id not in ids

    def test_reachable_from_leaf_is_empty(self):
        g = CausalGraph()
        n0 = ActionNode("n0", lambda ctx: None)
        n1 = ActionNode("n1", lambda ctx: None)
        g.add_node(n0).add_node(n1)
        g.add_edge(n0, n1)
        assert CausalSemantics.reachable(n1, g) == []

    def test_reachable_isolated_node(self):
        g = CausalGraph()
        n = ActionNode("n", lambda ctx: None)
        g.add_node(n)
        assert CausalSemantics.reachable(n, g) == []
