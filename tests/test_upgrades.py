"""
Tests for the three RS-CCE upgrades:

1. CausalReplayEngine   — deterministic causal replay
2. GraphComposer        — cross-graph composition
3. Self-modifying rules — add_rule / __inject_rules__
"""
import pytest

from core.causal_engine import CausalGraph
from core.event_bus import Event, EventBus
from core.graph_composer import GraphBridge, GraphComposer
from core.node_types import ActionNode, ConditionNode, EventNode, NodeState
from reality_layers.deterministic_layer import DeterministicLayer
from reality_layers.base_layer import LayerStack
from runtime.causal_replay import CausalReplayEngine
from runtime.execution_loop import ExecutionLoop
from runtime.state_store import StateStore
from tools.event_tracer import EventTracer


# ===========================================================================
# Upgrade 1 — Causal Replay Engine
# ===========================================================================

class TestCausalReplayEngine:
    # Shared DSL source and registry used by several tests
    RULES = """
        IF cpu_usage > 80%
        THEN log_event("high_cpu")
        CAUSE reduce_process_priority()
    """

    def _make_registry(self, log: list) -> dict:
        return {
            "log_event": lambda ctx, *a: log.append(("log", a)),
            "reduce_process_priority": lambda ctx, *a: log.append(("reduce",)),
        }

    def test_replay_produces_same_execution_history(self):
        """Replaying with the same state + events yields identical history."""
        log1, log2 = [], []

        # --- Original run ---
        engine1 = CausalReplayEngine(self.RULES, action_registry=self._make_registry(log1))
        loop1 = engine1.replay(initial_state={"cpu_usage": 90})
        history1 = [(e["name"], e["result"]) for e in loop1.graph.execution_history]

        # --- Replay run ---
        engine2 = CausalReplayEngine(self.RULES, action_registry=self._make_registry(log2))
        loop2 = engine2.replay(initial_state={"cpu_usage": 90})
        history2 = [(e["name"], e["result"]) for e in loop2.graph.execution_history]

        assert history1 == history2

    def test_replay_with_event_trace(self):
        """Events recorded in the original run are replayed correctly."""
        bus = EventBus()
        tracer = EventTracer(bus)
        bus.publish(Event("cpu_spike", {"value": 95}))

        log = []
        engine = CausalReplayEngine(self.RULES, action_registry=self._make_registry(log))
        loop = engine.replay(
            initial_state={"cpu_usage": 90},
            event_trace=tracer.trace,
        )
        # Execution completed with all nodes DONE
        done_count = sum(1 for n in loop.graph.nodes if n.state == NodeState.DONE)
        assert done_count == 3  # condition + 2 actions

    def test_condition_false_no_actions_executed(self):
        """Replay with a below-threshold state fires no actions."""
        log = []
        engine = CausalReplayEngine(self.RULES, action_registry=self._make_registry(log))
        loop = engine.replay(initial_state={"cpu_usage": 50})
        assert log == []

    def test_replay_graph_resets_state(self):
        """replay_graph() resets nodes before replaying."""
        g = CausalGraph()
        results = []
        cond = ConditionNode("cond", lambda ctx: ctx.get("x", 0) > 0)
        act = ActionNode("act", lambda ctx: results.append("ran") or "done")
        g.add_node(cond).add_node(act)
        g.add_edge(cond, act)

        # Run once — nodes now in DONE state
        g.tick({"x": 1})
        assert cond.state == NodeState.DONE

        # Replay resets and re-executes
        engine = CausalReplayEngine("", action_registry={})
        loop = engine.replay_graph(g, initial_state={"x": 1})

        assert cond.state == NodeState.DONE
        assert len(results) == 2  # once from tick(), once from replay

    def test_replay_is_deterministic_across_multiple_runs(self):
        """Three independent replays must produce the same execution history."""
        histories = []
        for _ in range(3):
            log = []
            engine = CausalReplayEngine(self.RULES, action_registry=self._make_registry(log))
            loop = engine.replay(initial_state={"cpu_usage": 85})
            histories.append([(e["name"],) for e in loop.graph.execution_history])

        assert histories[0] == histories[1] == histories[2]

    def test_replay_uses_deterministic_layer_by_default(self):
        """The default layer stack uses DeterministicLayer (time starts at 0)."""
        times = []
        rules = "IF x > 0\nTHEN capture_time()"
        registry = {"capture_time": lambda ctx, *a: times.append(ctx.get("__time__"))}

        engine = CausalReplayEngine(rules, action_registry=registry)
        engine.replay(initial_state={"x": 1})

        assert len(times) == 1
        assert times[0] == 0.0  # DeterministicLayer starts at 0.0

    def test_replay_with_custom_layer_stack(self):
        """A custom layer stack overrides the default DeterministicLayer."""
        times = []
        rules = "IF x > 0\nTHEN capture_time()"
        registry = {"capture_time": lambda ctx, *a: times.append(ctx.get("__time__"))}

        custom_stack = LayerStack()
        custom_stack.push(DeterministicLayer(start_time=999.0, time_step=1.0))

        engine = CausalReplayEngine(rules, action_registry=registry)
        engine.replay(initial_state={"x": 1}, layer_stack=custom_stack)

        assert times[0] == 999.0

    def test_repr(self):
        engine = CausalReplayEngine("IF x > 0\nTHEN f()")
        assert "CausalReplayEngine" in repr(engine)


# ===========================================================================
# Upgrade 2 — Cross-Graph Composition
# ===========================================================================

class TestGraphComposer:
    def _make_graph(self, condition_key: str, threshold: float, label: str) -> tuple:
        """Return (graph, cond_node, action_node) with given condition."""
        g = CausalGraph()
        results = []
        cond = ConditionNode(f"cond_{label}", lambda ctx, k=condition_key, t=threshold: ctx.get(k, 0) > t)
        act = ActionNode(f"act_{label}", lambda ctx, l=label: results.append(l) or {"fired": l})
        g.add_node(cond)
        g.add_node(act)
        g.add_edge(cond, act)
        return g, cond, act, results

    # --- absorb() tests ---

    def test_absorb_merges_nodes(self):
        g1 = CausalGraph()
        g2 = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        g1.add_node(n1)
        g2.add_node(n2)
        g1.absorb(g2)
        ids = [n.id for n in g1.nodes]
        assert n1.id in ids
        assert n2.id in ids

    def test_absorb_merges_edges(self):
        g1 = CausalGraph()
        g2 = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        g2.add_node(n1)
        g2.add_node(n2)
        g2.add_edge(n1, n2)
        g1.absorb(g2)
        assert len(g1.edges) == 1

    def test_absorb_no_duplicate_edges(self):
        """Absorbing twice does not create duplicate edges."""
        g1 = CausalGraph()
        g2 = CausalGraph()
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        g2.add_node(n1)
        g2.add_node(n2)
        g2.add_edge(n1, n2)
        g1.absorb(g2)
        g1.absorb(g2)
        assert len(g1.edges) == 1

    def test_absorb_reset_nodes(self):
        g1 = CausalGraph()
        g2 = CausalGraph()
        n = ActionNode("n", lambda ctx: "done")
        g2.add_node(n)
        g2.tick({})  # n is now DONE
        assert n.state == NodeState.DONE
        g1.absorb(g2, reset_nodes=True)
        assert n.state == NodeState.PENDING

    # --- compose() tests ---

    def test_compose_contains_all_nodes(self):
        ga, _, _, _ = self._make_graph("x", 5, "a")
        gb, _, _, _ = self._make_graph("y", 5, "b")
        meta = GraphComposer.compose(ga, gb)
        assert len(meta.nodes) == 4  # 2 from each

    def test_compose_with_bridge_connects_graphs(self):
        ga, _, act_a, _ = self._make_graph("x", 5, "a")
        gb, cond_b, _, _ = self._make_graph("y", 5, "b")
        bridge = GraphBridge(source_node_id=act_a.id, target_node_id=cond_b.id)
        meta = GraphComposer.compose(ga, gb, bridges=[bridge])
        # act_a should now be a predecessor of cond_b
        pred_ids = [n.id for n in meta.predecessors(cond_b)]
        assert act_a.id in pred_ids

    def test_compose_bridge_invalid_source_raises(self):
        ga, _, _, _ = self._make_graph("x", 5, "a")
        gb, cond_b, _, _ = self._make_graph("y", 5, "b")
        bad_bridge = GraphBridge(source_node_id="nonexistent-id", target_node_id=cond_b.id)
        with pytest.raises(ValueError, match="not found"):
            GraphComposer.compose(ga, gb, bridges=[bad_bridge])

    def test_compose_bridge_invalid_target_raises(self):
        ga, _, act_a, _ = self._make_graph("x", 5, "a")
        gb, _, _, _ = self._make_graph("y", 5, "b")
        bad_bridge = GraphBridge(source_node_id=act_a.id, target_node_id="nonexistent-id")
        with pytest.raises(ValueError, match="not found"):
            GraphComposer.compose(ga, gb, bridges=[bad_bridge])

    def test_compose_execution_bridge_propagates_causality(self):
        """Graph A condition → action; bridge makes Graph B root depend on A's action."""
        results = []

        ga = CausalGraph()
        cond_a = ConditionNode("cond_a", lambda ctx: ctx.get("x", 0) > 5)
        act_a = ActionNode("act_a", lambda ctx: results.append("A"))
        ga.add_node(cond_a).add_node(act_a)
        ga.add_edge(cond_a, act_a)

        gb = CausalGraph()
        act_b = ActionNode("act_b", lambda ctx: results.append("B"))
        gb.add_node(act_b)

        # Bridge: act_a → act_b
        bridge = GraphBridge(source_node_id=act_a.id, target_node_id=act_b.id)
        meta = GraphComposer.compose(ga, gb, bridges=[bridge])

        meta.tick({"x": 10})
        assert results == ["A", "B"]  # B fires after A

    def test_compose_no_bridge_graphs_execute_independently(self):
        """Without a bridge both sub-graph conditions evaluate independently."""
        results = []

        ga = CausalGraph()
        cond_a = ConditionNode("c_a", lambda ctx: ctx.get("a", 0) > 0)
        act_a = ActionNode("a_a", lambda ctx: results.append("A"))
        ga.add_node(cond_a).add_node(act_a)
        ga.add_edge(cond_a, act_a)

        gb = CausalGraph()
        cond_b = ConditionNode("c_b", lambda ctx: ctx.get("b", 0) > 0)
        act_b = ActionNode("a_b", lambda ctx: results.append("B"))
        gb.add_node(cond_b).add_node(act_b)
        gb.add_edge(cond_b, act_b)

        meta = GraphComposer.compose(ga, gb)
        meta.tick({"a": 1, "b": 1})
        assert "A" in results
        assert "B" in results

    # --- compose_sequential() tests ---

    def test_compose_sequential_bridges_leaves_to_roots(self):
        """Leaf nodes of A are connected to root nodes of B."""
        ga, _, act_a, _ = self._make_graph("x", 0, "a")
        gb, cond_b, _, _ = self._make_graph("y", 0, "b")

        # Make act_a a leaf (no successors in ga) and cond_b a root in gb
        meta = GraphComposer.compose_sequential(ga, gb)

        pred_ids = [n.id for n in meta.predecessors(cond_b)]
        assert act_a.id in pred_ids

    def test_compose_sequential_b_waits_for_a(self):
        """Graph B actions do not fire until Graph A has completed."""
        order = []

        ga = CausalGraph()
        cond_a = ConditionNode("ca", lambda ctx: ctx.get("go", False))
        act_a = ActionNode("aa", lambda ctx: order.append("A"))
        ga.add_node(cond_a).add_node(act_a)
        ga.add_edge(cond_a, act_a)

        gb = CausalGraph()
        act_b = ActionNode("ab", lambda ctx: order.append("B"))
        gb.add_node(act_b)

        meta = GraphComposer.compose_sequential(ga, gb)
        meta.tick({"go": True})

        assert order.index("A") < order.index("B")

    def test_compose_sequential_no_leaves_raises(self):
        ga = CausalGraph()
        gb = CausalGraph()
        n = ActionNode("n", lambda ctx: None)
        gb.add_node(n)
        with pytest.raises(ValueError, match="no leaf nodes"):
            GraphComposer.compose_sequential(ga, gb)

    def test_compose_sequential_no_roots_raises(self):
        ga = CausalGraph()
        gb = CausalGraph()
        n = ActionNode("n", lambda ctx: None)
        ga.add_node(n)
        with pytest.raises(ValueError, match="no root nodes"):
            GraphComposer.compose_sequential(ga, gb)

    def test_multiple_bridges(self):
        """Multiple bridges can be specified in one compose call."""
        ga = CausalGraph()
        leaf1 = ActionNode("leaf1", lambda ctx: None)
        leaf2 = ActionNode("leaf2", lambda ctx: None)
        ga.add_node(leaf1)
        ga.add_node(leaf2)

        gb = CausalGraph()
        root = ActionNode("root", lambda ctx: None)
        gb.add_node(root)

        bridges = [
            GraphBridge(leaf1.id, root.id, "b1"),
            GraphBridge(leaf2.id, root.id, "b2"),
        ]
        meta = GraphComposer.compose(ga, gb, bridges=bridges)
        pred_ids = [n.id for n in meta.predecessors(root)]
        assert leaf1.id in pred_ids
        assert leaf2.id in pred_ids


# ===========================================================================
# Upgrade 3 — Self-Modifying Rules
# ===========================================================================

class TestSelfModifyingRules:
    def test_add_rule_builtin_returns_sentinel(self):
        """The built-in add_rule action returns __inject_rules__ sentinel."""
        from runtime.execution_loop import _make_add_rule_action
        fn = _make_add_rule_action()
        result = fn({}, '"IF x > 1 THEN noop()"')
        assert "__inject_rules__" in result
        assert result["__inject_rules__"] == ["IF x > 1 THEN noop()"]

    def test_add_rule_strips_quotes(self):
        from runtime.execution_loop import _make_add_rule_action
        fn = _make_add_rule_action()
        result = fn({}, "'IF x > 1 THEN noop()'")
        assert result["__inject_rules__"] == ["IF x > 1 THEN noop()"]

    def test_add_rule_no_args_empty_string(self):
        from runtime.execution_loop import _make_add_rule_action
        fn = _make_add_rule_action()
        result = fn({})
        assert result["__inject_rules__"] == [""]

    def test_loop_processes_inject_rules_sentinel(self):
        """A node returning __inject_rules__ causes the loop to add a new rule."""
        graph = CausalGraph()

        # Action that emits a new rule
        inject_act = ActionNode(
            "injector",
            lambda ctx: {"__inject_rules__": ["IF flag > 0\nTHEN capture()"]},
        )
        graph.add_node(inject_act)

        loop = ExecutionLoop(graph, max_ticks=10)
        captured = []
        loop._builtin_registry["capture"] = lambda ctx, *a: captured.append("captured")

        loop.state.set("flag", 5)
        loop.tick_once()  # injector fires, new rule "IF flag > 0 THEN capture()" added

        # After injection, new condition should fire on next tick
        graph.reset()
        # Re-trigger the newly injected rule
        loop.tick_once()
        assert "captured" in captured

    def test_inject_rules_includes_builtin_registry(self):
        """inject_rule() merges built-in registry so add_rule is available."""
        graph = CausalGraph()
        loop = ExecutionLoop(graph, max_ticks=10)
        # Should not raise — add_rule is available without explicit registry
        loop.inject_rule("IF x > 0\nTHEN add_rule()")

    def test_self_modifying_rule_via_cause_add_rule(self):
        """
        A CAUSE add_rule(...) clause causes the loop to inject a new rule
        that fires on the next tick.
        """
        results = []

        initial_source = """
            IF trigger > 0
            THEN log_initial()
            CAUSE add_rule("IF second_trigger > 0 THEN log_second()")
        """
        registry = {
            "log_initial": lambda ctx, *a: results.append("initial"),
            "log_second": lambda ctx, *a: results.append("second"),
        }

        from dsl.parser import RuleParser
        from dsl.compiler import DSLCompiler

        # Build initial graph with add_rule available
        loop = ExecutionLoop(CausalGraph(), max_ticks=20)
        # Register user actions in the loop's builtin registry so they are
        # available to any dynamically injected rules too.
        loop._builtin_registry.update(registry)
        merged = {**loop._builtin_registry}
        rules = RuleParser().parse(initial_source)
        DSLCompiler(action_registry=merged).compile(rules, graph=loop.graph)

        loop.state.set("trigger", 1)
        loop.tick_once()  # fires initial rule; add_rule injects the second rule

        assert "initial" in results

        # The injected rule should now exist in the graph
        node_names = [n.name for n in loop.graph.nodes]
        assert any("second_trigger" in n for n in node_names)

        # Activate the second rule
        loop.state.set("second_trigger", 1)
        loop.graph.reset()
        loop.tick_once()

        assert "second" in results

    def test_self_modifying_rule_does_not_state_update(self):
        """
        A node that returns __inject_rules__ must NOT update the state store
        (the sentinel dict is consumed, not merged into state).
        """
        graph = CausalGraph()
        inject_act = ActionNode(
            "injector",
            lambda ctx: {"__inject_rules__": ["IF x > 0\nTHEN noop()"]},
        )
        graph.add_node(inject_act)

        loop = ExecutionLoop(graph, max_ticks=5)
        loop.tick_once()

        # __inject_rules__ key must NOT be in state store
        assert loop.state.get("__inject_rules__") is None

    def test_loop_builtin_registry_contains_add_rule(self):
        graph = CausalGraph()
        loop = ExecutionLoop(graph)
        assert "add_rule" in loop._builtin_registry

    def test_graph_grows_after_self_modification(self):
        """The graph node count increases after a self-modifying rule fires."""
        graph = CausalGraph()
        results = []

        # Manually build: condition triggers add_rule emission
        inject_act = ActionNode(
            "inject_rule",
            lambda ctx: {
                "__inject_rules__": ["IF grow_flag > 0\nTHEN grow_action()"]
            },
        )
        graph.add_node(inject_act)

        loop = ExecutionLoop(graph, max_ticks=10)
        loop._builtin_registry["grow_action"] = lambda ctx, *a: results.append("grew")
        initial_count = len(loop.graph.nodes)
        loop.tick_once()  # inject_rule fires; new rule added (2 new nodes)

        assert len(loop.graph.nodes) > initial_count
