"""
Tests for Upgrade 5 — Execution Proof System (tools/proof_engine.py).

Covers:
- NodeActivationProof.explain()
- DependencyCertificate.explain()
- ProofEngine.record_tick()
- ProofEngine.attach()
- ExecutionLineage.why_fired()
- ExecutionLineage.certificates_for()
- ExecutionLineage.full_chain()
- ExecutionLineage.lineage_graph()
- ExecutionLineage.format_lineage()
"""
import pytest

from core.causal_engine import CausalGraph
from core.node_types import ActionNode, ConditionNode, EventNode, NodeState
from runtime.execution_loop import ExecutionLoop
from runtime.state_store import StateStore
from tools.proof_engine import (
    DependencyCertificate,
    ExecutionLineage,
    NodeActivationProof,
    ProofEngine,
)


# ===========================================================================
# NodeActivationProof
# ===========================================================================

class TestNodeActivationProof:
    def _make_proof(self, **kwargs) -> NodeActivationProof:
        defaults = dict(
            node_id="abc",
            node_name="test_node",
            node_type="ActionNode",
            tick=1,
            logical_time=0.0,
            predecessor_ids=[],
            triggered_by={},
            result=None,
            cause_chain=["abc"],
        )
        defaults.update(kwargs)
        return NodeActivationProof(**defaults)

    def test_explain_contains_node_name(self):
        proof = self._make_proof(node_name="my_node")
        assert "my_node" in proof.explain()

    def test_explain_contains_tick(self):
        proof = self._make_proof(tick=42)
        assert "42" in proof.explain()

    def test_explain_root_node_shows_no_predecessors(self):
        proof = self._make_proof(predecessor_ids=[])
        assert "root" in proof.explain().lower() or "no predecessors" in proof.explain()

    def test_explain_shows_context(self):
        proof = self._make_proof(triggered_by={"cpu": 90})
        assert "cpu" in proof.explain()

    def test_explain_shows_cause_chain(self):
        proof = self._make_proof(cause_chain=["root_id", "mid_id", "leaf_id"])
        text = proof.explain()
        assert "root_id" in text
        assert "leaf_id" in text

    def test_explain_shows_result(self):
        proof = self._make_proof(result={"throttled": True})
        assert "throttled" in proof.explain()


# ===========================================================================
# DependencyCertificate
# ===========================================================================

class TestDependencyCertificate:
    def _make_cert(self, **kwargs) -> DependencyCertificate:
        defaults = dict(
            cause_node_id="c1",
            cause_node_name="cause",
            effect_node_id="e1",
            effect_node_name="effect",
            edge_label="triggers",
            cause_tick=1,
            effect_tick=2,
        )
        defaults.update(kwargs)
        return DependencyCertificate(**defaults)

    def test_explain_contains_cause_name(self):
        cert = self._make_cert(cause_node_name="upstream")
        assert "upstream" in cert.explain()

    def test_explain_contains_effect_name(self):
        cert = self._make_cert(effect_node_name="downstream")
        assert "downstream" in cert.explain()

    def test_explain_contains_edge_label(self):
        cert = self._make_cert(edge_label="triggers")
        assert "triggers" in cert.explain()

    def test_explain_contains_ticks(self):
        cert = self._make_cert(cause_tick=3, effect_tick=4)
        assert "3" in cert.explain()
        assert "4" in cert.explain()


# ===========================================================================
# ProofEngine — record_tick (manual mode)
# ===========================================================================

class TestProofEngineManual:
    def _build_graph(self):
        g = CausalGraph(record_contexts=True)
        cond = ConditionNode("cond", lambda ctx: ctx.get("x", 0) > 0,
                             metadata={"metric": "x"})
        act = ActionNode("act", lambda ctx: {"y": 1})
        g.add_node(cond).add_node(act)
        g.add_edge(cond, act, label="triggers")
        return g, cond, act

    def test_proof_created_for_executed_nodes(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5, "__time__": 0.0, "__tick__": 1})
        engine.record_tick(tick=1, context={"x": 5, "__time__": 0.0, "__tick__": 1})
        lineage = engine.get_lineage()
        assert lineage.why_fired(cond.id) is not None
        assert lineage.why_fired(act.id) is not None

    def test_proof_not_created_when_condition_false(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 0})
        engine.record_tick(tick=1, context={"x": 0})
        lineage = engine.get_lineage()
        # ConditionNode fired (evaluates to False, still executes), ActionNode did not
        assert lineage.why_fired(act.id) is None

    def test_proof_node_name_matches(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=1, context={"x": 5})
        proof = engine.get_lineage().why_fired(cond.id)
        assert proof.node_name == "cond"

    def test_proof_tick_is_correct(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=7, context={"x": 5})
        proof = engine.get_lineage().why_fired(cond.id)
        assert proof.tick == 7

    def test_proof_type_is_correct(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=1, context={"x": 5})
        lineage = engine.get_lineage()
        assert lineage.why_fired(cond.id).node_type == "ConditionNode"
        assert lineage.why_fired(act.id).node_type == "ActionNode"

    def test_condition_proof_records_metric(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=1, context={"x": 5})
        proof = engine.get_lineage().why_fired(cond.id)
        assert proof.triggered_by.get("x") == 5

    def test_certificate_links_cond_to_act(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=1, context={"x": 5})
        lineage = engine.get_lineage()
        certs = lineage.certificates_for(act.id)
        assert len(certs) == 1
        assert certs[0].cause_node_id == cond.id
        assert certs[0].effect_node_id == act.id

    def test_certificate_edge_label(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=1, context={"x": 5})
        cert = engine.get_lineage().certificates_for(act.id)[0]
        assert cert.edge_label == "triggers"

    def test_cause_chain_includes_all_ancestors(self):
        g = CausalGraph(record_contexts=True)
        n1 = ActionNode("n1", lambda ctx: None)
        n2 = ActionNode("n2", lambda ctx: None)
        n3 = ActionNode("n3", lambda ctx: None)
        g.add_node(n1).add_node(n2).add_node(n3)
        g.add_edge(n1, n2)
        g.add_edge(n2, n3)
        engine = ProofEngine(g)
        g.tick({})
        engine.record_tick(tick=1, context={})
        proof = engine.get_lineage().why_fired(n3.id)
        assert n1.id in proof.cause_chain
        assert n3.id in proof.cause_chain

    def test_root_node_has_empty_predecessor_ids(self):
        g = CausalGraph()
        n = ActionNode("n", lambda ctx: None)
        g.add_node(n)
        engine = ProofEngine(g)
        g.tick({})
        engine.record_tick(tick=1, context={})
        proof = engine.get_lineage().why_fired(n.id)
        assert proof.predecessor_ids == []

    def test_no_proof_for_node_that_never_fired(self):
        g = CausalGraph()
        cond = ConditionNode("c", lambda ctx: ctx.get("x", 0) > 0)
        act = ActionNode("a", lambda ctx: None)
        g.add_node(cond).add_node(act)
        g.add_edge(cond, act)
        engine = ProofEngine(g)
        g.tick({"x": 0})   # act never fires
        engine.record_tick(tick=1, context={"x": 0})
        assert engine.get_lineage().why_fired(act.id) is None

    def test_reset_clears_proofs(self):
        g, cond, _ = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=1, context={"x": 5})
        assert len(engine.get_lineage().all_proofs()) > 0
        engine.reset()
        assert len(engine.get_lineage().all_proofs()) == 0

    def test_record_tick_does_not_double_count(self):
        g, cond, act = self._build_graph()
        engine = ProofEngine(g)
        g.tick({"x": 5})
        engine.record_tick(tick=1, context={"x": 5})
        engine.record_tick(tick=1, context={"x": 5})  # second call on same history
        # Only the entries from the first call are counted
        assert len(engine.get_lineage().all_proofs()) == 2  # cond + act


# ===========================================================================
# ProofEngine — attach (automatic mode)
# ===========================================================================

class TestProofEngineAttach:
    def test_attach_auto_records_on_tick(self):
        g = CausalGraph(record_contexts=True)
        cond = ConditionNode("cond", lambda ctx: ctx.get("x", 0) > 0,
                             metadata={"metric": "x"})
        act = ActionNode("act", lambda ctx: {"out": 1})
        g.add_node(cond).add_node(act)
        g.add_edge(cond, act)

        loop = ExecutionLoop(g, state_store=StateStore({"x": 5}), max_ticks=5)
        engine = ProofEngine(g)
        engine.attach(loop)
        loop.start()

        lineage = engine.get_lineage()
        assert lineage.why_fired(cond.id) is not None
        assert lineage.why_fired(act.id) is not None

    def test_attach_proof_references_correct_tick(self):
        g = CausalGraph(record_contexts=True)
        n = ActionNode("n", lambda ctx: None)
        g.add_node(n)

        loop = ExecutionLoop(g, max_ticks=1)
        engine = ProofEngine(g)
        engine.attach(loop)
        loop.tick_once()

        proof = engine.get_lineage().why_fired(n.id)
        assert proof is not None
        assert proof.tick == 1


# ===========================================================================
# ExecutionLineage
# ===========================================================================

class TestExecutionLineage:
    def _build_lineage(self):
        g = CausalGraph(record_contexts=True)
        n1 = ActionNode("root", lambda ctx: None)
        n2 = ActionNode("mid", lambda ctx: None)
        n3 = ActionNode("leaf", lambda ctx: None)
        g.add_node(n1).add_node(n2).add_node(n3)
        g.add_edge(n1, n2)
        g.add_edge(n2, n3)
        engine = ProofEngine(g)
        g.tick({})
        engine.record_tick(tick=1, context={})
        return engine.get_lineage(), n1, n2, n3

    def test_all_proofs_returns_sorted_list(self):
        lineage, n1, n2, n3 = self._build_lineage()
        proofs = lineage.all_proofs()
        assert len(proofs) == 3
        # Sorted by (tick, node_name) → tick=1 for all, alphabetical by name
        names = [p.node_name for p in proofs]
        assert names == sorted(names)

    def test_lineage_graph_adjacency(self):
        lineage, n1, n2, n3 = self._build_lineage()
        adj = lineage.lineage_graph()
        assert n2.id in adj.get(n1.id, [])
        assert n3.id in adj.get(n2.id, [])

    def test_full_chain_follows_cause(self):
        lineage, n1, n2, n3 = self._build_lineage()
        chain = lineage.full_chain(n3.id)
        names = [p.node_name for p in chain]
        assert names.index("root") < names.index("leaf")

    def test_why_fired_returns_none_for_unknown(self):
        lineage, _, _, _ = self._build_lineage()
        assert lineage.why_fired("does-not-exist") is None

    def test_certificates_for_returns_empty_for_unknown(self):
        lineage, _, _, _ = self._build_lineage()
        assert lineage.certificates_for("does-not-exist") == []

    def test_format_lineage_is_non_empty_string(self):
        lineage, _, _, _ = self._build_lineage()
        text = lineage.format_lineage()
        assert isinstance(text, str)
        assert len(text) > 0
        assert "root" in text

    def test_format_lineage_empty_when_no_proofs(self):
        lineage = ExecutionLineage(proofs={}, certificates={})
        text = lineage.format_lineage()
        assert "no executions" in text.lower()

    def test_repr_shows_counts(self):
        lineage, _, _, _ = self._build_lineage()
        r = repr(lineage)
        assert "ExecutionLineage" in r
        assert "nodes=3" in r

    def test_certificates_for_root_is_empty(self):
        lineage, n1, _, _ = self._build_lineage()
        assert lineage.certificates_for(n1.id) == []

    def test_proof_result_is_recorded(self):
        g = CausalGraph()
        n = ActionNode("n", lambda ctx: {"answer": 42})
        g.add_node(n)
        engine = ProofEngine(g)
        g.tick({})
        engine.record_tick(tick=1, context={})
        proof = engine.get_lineage().why_fired(n.id)
        assert proof.result == {"answer": 42}
