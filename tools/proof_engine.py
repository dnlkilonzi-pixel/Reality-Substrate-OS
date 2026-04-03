"""
Execution Proof System — "Git blame for computation causality."

For every node that fires, :class:`ProofEngine` records a
:class:`NodeActivationProof` that answers the question:

    "Why did this node fire?"

A :class:`NodeActivationProof` contains:

* The node's identity and type.
* The tick and logical time at which it fired.
* The IDs of the immediate predecessor nodes whose DONE state triggered it.
* The relevant context values (metric readings, upstream results).
* The full causal chain back to the graph's root nodes.

A :class:`DependencyCertificate` is a single-edge causal proof:
"Node B fired because Node A fired."

:class:`ExecutionLineage` is the complete proof graph for an execution: a
queryable DAG of cause-and-effect relationships across all nodes.

:class:`ProofEngine` attaches to an
:class:`~runtime.execution_loop.ExecutionLoop` and continuously builds the
lineage as ticks execute.

Usage::

    from tools.proof_engine import ProofEngine

    graph = CausalGraph(record_contexts=True)
    # ... build graph ...

    loop = ExecutionLoop(graph, state_store=StateStore({"cpu": 90}))
    engine = ProofEngine(graph)
    engine.attach(loop)

    loop.start()

    lineage = engine.get_lineage()
    print(lineage.format_lineage())
    print(lineage.why_fired(some_node.id).explain())
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.causal_engine import CausalGraph
from core.node_types import ConditionNode


# ===========================================================================
# Data classes
# ===========================================================================

@dataclass
class NodeActivationProof:
    """
    A formal proof that a specific node fired during a specific tick.

    Attributes
    ----------
    node_id : str
        Unique ID of the node that fired.
    node_name : str
        Human-readable name.
    node_type : str
        Class name of the node (``ConditionNode``, ``ActionNode``, …).
    tick : int
        Tick number during which the node fired.
    logical_time : float
        Logical time value (``__time__``) from the execution context.
    predecessor_ids : list of str
        Direct causal predecessors whose DONE state unlocked this node.
    triggered_by : dict
        For ConditionNodes: the ``metric → value`` pair(s) the predicate
        evaluated.  For other nodes: upstream node ID → result pairs.
    result : Any
        The value produced by the node.
    cause_chain : list of str
        Ordered node IDs on the longest causal path from a root node to
        this node.
    """

    node_id: str
    node_name: str
    node_type: str
    tick: int
    logical_time: float
    predecessor_ids: List[str]
    triggered_by: Dict[str, Any]
    result: Any
    cause_chain: List[str]

    def explain(self) -> str:
        """Return a human-readable explanation of this activation."""
        lines = [
            f"Node '{self.node_name}' ({self.node_type}) fired at tick {self.tick}",
            f"  Logical time  : {self.logical_time}",
        ]
        if self.predecessor_ids:
            lines.append(f"  Caused by     : {self.predecessor_ids}")
        else:
            lines.append("  Caused by     : <root — no predecessors>")
        if self.triggered_by:
            lines.append(f"  Context       : {self.triggered_by}")
        chain_str = " → ".join(self.cause_chain) if self.cause_chain else "(self)"
        lines.append(f"  Causal chain  : {chain_str}")
        lines.append(f"  Result        : {self.result!r}")
        return "\n".join(lines)


@dataclass
class DependencyCertificate:
    """
    A single-edge causal proof: *cause_node* caused *effect_node* to fire.

    Attributes
    ----------
    cause_node_id : str
        The upstream (cause) node.
    cause_node_name : str
        Human-readable name of the cause node.
    effect_node_id : str
        The downstream (effect) node.
    effect_node_name : str
        Human-readable name of the effect node.
    edge_label : str
        Label of the causal edge (e.g. ``"triggers"``, ``"causes"``).
    cause_tick : int
        Tick at which the cause node fired.
    effect_tick : int
        Tick at which the effect node fired.
    """

    cause_node_id: str
    cause_node_name: str
    effect_node_id: str
    effect_node_name: str
    edge_label: str
    cause_tick: int
    effect_tick: int

    def explain(self) -> str:
        return (
            f"'{self.cause_node_name}' (tick {self.cause_tick})"
            f"  --[{self.edge_label}]-->"
            f"  '{self.effect_node_name}' (tick {self.effect_tick})"
        )


# ===========================================================================
# ExecutionLineage
# ===========================================================================

class ExecutionLineage:
    """
    The complete causal proof graph for an execution.

    Provides a queryable mapping from every fired node to its
    :class:`NodeActivationProof` and the :class:`DependencyCertificate` edges
    that explain why it fired.

    Think of it as ``git blame``, but for computation causality.
    """

    def __init__(
        self,
        proofs: Dict[str, NodeActivationProof],
        certificates: Dict[str, List[DependencyCertificate]],
    ) -> None:
        self._proofs = proofs           # node_id → proof
        self._certs = certificates      # effect_node_id → [certs]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def why_fired(self, node_id: str) -> Optional[NodeActivationProof]:
        """Return the activation proof for *node_id*, or ``None`` if not found."""
        return self._proofs.get(node_id)

    def certificates_for(self, node_id: str) -> List[DependencyCertificate]:
        """Return all dependency certificates that explain *node_id*'s activation."""
        return list(self._certs.get(node_id, []))

    def full_chain(self, node_id: str) -> List[NodeActivationProof]:
        """
        Return the ordered list of proofs on the longest causal path
        ending at *node_id* (inclusive).
        """
        proof = self._proofs.get(node_id)
        if proof is None:
            return []
        return [self._proofs[nid] for nid in proof.cause_chain if nid in self._proofs]

    def all_proofs(self) -> List[NodeActivationProof]:
        """Return all activation proofs sorted by (tick, node_name)."""
        return sorted(self._proofs.values(), key=lambda p: (p.tick, p.node_name))

    def lineage_graph(self) -> Dict[str, List[str]]:
        """
        Return the causal lineage as an adjacency dict.

        Keys are **cause** node IDs; values are lists of **effect** node IDs.
        The structure mirrors the original causal graph, but is indexed by
        execution rather than by structure.
        """
        adj: Dict[str, List[str]] = {}
        for effect_id, certs in self._certs.items():
            for cert in certs:
                adj.setdefault(cert.cause_node_id, []).append(effect_id)
        return adj

    def format_lineage(self) -> str:
        """Return a human-readable lineage report."""
        if not self._proofs:
            return "ExecutionLineage: (no executions recorded)"
        lines = ["Execution Lineage Report", "=" * 60]
        for proof in self.all_proofs():
            lines.append(proof.explain())
            for cert in self._certs.get(proof.node_id, []):
                lines.append(f"  ← {cert.explain()}")
            lines.append("")
        return "\n".join(lines)

    def __repr__(self) -> str:
        cert_count = sum(len(v) for v in self._certs.values())
        return f"ExecutionLineage(nodes={len(self._proofs)}, edges={cert_count})"


# ===========================================================================
# ProofEngine
# ===========================================================================

class ProofEngine:
    """
    Observes a causal graph execution and builds an :class:`ExecutionLineage`.

    **Automatic mode** (recommended) — attach to a loop::

        graph = CausalGraph(record_contexts=True)
        # ... build graph ...
        loop  = ExecutionLoop(graph, ...)
        proof = ProofEngine(graph)
        proof.attach(loop)
        loop.start()
        lineage = proof.get_lineage()

    **Manual mode** — call after each tick::

        loop.tick_once()
        proof.record_tick(tick=loop.tick_count, context=ctx)
        lineage = proof.get_lineage()

    When ``record_contexts=True`` is passed to :class:`~core.causal_engine.CausalGraph`,
    the proof engine uses the exact context snapshot captured at the moment each
    node fired, providing the most accurate proofs.  When ``record_contexts=False``
    (default), the post-tick state snapshot is used as an approximation.
    """

    def __init__(self, graph: CausalGraph) -> None:
        self._graph = graph
        self._proofs: Dict[str, NodeActivationProof] = {}
        self._certs: Dict[str, List[DependencyCertificate]] = {}
        self._last_history_len: int = 0

    def attach(self, loop: Any) -> None:
        """
        Register an ``on_tick`` callback on *loop* so proofs are built
        automatically after each tick completes.

        Parameters
        ----------
        loop : ExecutionLoop
            The execution loop to observe.
        """
        def _on_tick(lp: Any) -> None:
            ctx = lp.state.snapshot()
            ctx["__tick__"] = lp.tick_count
            ctx["__time__"] = lp.layers.time_now()
            self.record_tick(tick=lp.tick_count, context=ctx)

        loop.on_tick(_on_tick)

    def record_tick(
        self,
        tick: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Process any new entries in the graph's ``execution_history`` and
        generate proofs for them.

        Call this manually after
        :meth:`~core.causal_engine.CausalGraph.tick` when not using
        :meth:`attach`.
        """
        fallback_ctx = context or {}
        history = self._graph.execution_history
        new_entries = history[self._last_history_len:]
        self._last_history_len = len(history)

        for entry in new_entries:
            node_id = entry["node_id"]
            node = self._graph.get_node(node_id)
            if node is None:
                continue
            # Prefer the context captured inside tick(); fall back to caller's
            ctx = entry.get("context", fallback_ctx)
            self._build_proof(node, tick, ctx, entry)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_proof(
        self,
        node: Any,
        tick: int,
        context: Dict[str, Any],
        history_entry: Dict[str, Any],
    ) -> None:
        preds = self._graph.predecessors(node)
        predecessor_ids = [p.id for p in preds]

        # Build triggered_by: context values relevant to this activation
        triggered_by: Dict[str, Any] = {}
        if isinstance(node, ConditionNode):
            metric = node.metadata.get("metric")
            if metric and metric in context:
                triggered_by[metric] = context[metric]
        else:
            for pred in preds:
                if pred.id in context:
                    triggered_by[pred.id] = context[pred.id]

        # Longest causal chain from any root to this node
        cause_chain = self._compute_cause_chain(node)

        # Dependency certificates (one per predecessor)
        edge_labels = {
            (e.source_id, e.target_id): e.label
            for e in self._graph.edges
        }
        certs: List[DependencyCertificate] = []
        for pred in preds:
            pred_proof = self._proofs.get(pred.id)
            cause_tick = pred_proof.tick if pred_proof else max(tick - 1, 0)
            certs.append(DependencyCertificate(
                cause_node_id=pred.id,
                cause_node_name=pred.name,
                effect_node_id=node.id,
                effect_node_name=node.name,
                edge_label=edge_labels.get((pred.id, node.id), "causes"),
                cause_tick=cause_tick,
                effect_tick=tick,
            ))

        proof = NodeActivationProof(
            node_id=node.id,
            node_name=node.name,
            node_type=type(node).__name__,
            tick=tick,
            logical_time=float(context.get("__time__", 0.0)),
            predecessor_ids=predecessor_ids,
            triggered_by=triggered_by,
            result=history_entry.get("result"),
            cause_chain=cause_chain,
        )
        self._proofs[node.id] = proof
        if certs:
            self._certs[node.id] = certs

    def _compute_cause_chain(self, node: Any) -> List[str]:
        """Return the longest causal path from a root to *node* as node IDs."""
        def _longest(nid: str) -> List[str]:
            preds = list(self._graph._predecessors.get(nid, set()))
            if not preds:
                return [nid]
            best = max((_longest(pid) for pid in preds), key=len)
            return best + [nid]

        return _longest(node.id)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def get_lineage(self) -> ExecutionLineage:
        """Return the current :class:`ExecutionLineage`."""
        return ExecutionLineage(
            proofs=dict(self._proofs),
            certificates=dict(self._certs),
        )

    def reset(self) -> None:
        """Clear all recorded proofs."""
        self._proofs.clear()
        self._certs.clear()
        self._last_history_len = 0

    def __repr__(self) -> str:
        return f"ProofEngine(proofs={len(self._proofs)}, graph_nodes={len(self._graph.nodes)})"
