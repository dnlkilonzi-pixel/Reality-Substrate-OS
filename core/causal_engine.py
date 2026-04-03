"""
Causal Graph Engine — the heart of RS-CCE.

``CausalGraph`` maintains a directed graph of nodes and edges.
Edges represent *causality*: a target node can only execute after all
its causal predecessors have completed successfully.

The scheduler traverses the graph in dependency order and fires every
node whose prerequisites are satisfied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from .node_types import BaseNode, ConditionNode, NodeState


@dataclass
class CausalEdge:
    """
    A directed causal relationship from *source* to *target*.

    Optional *label* describes the semantic of the dependency
    (e.g. "triggers", "causes", "requires").
    """

    source_id: str
    target_id: str
    label: str = "causes"


class CausalGraph:
    """
    Directed causal graph runtime and scheduler.

    Nodes are added via :meth:`add_node` and connected via
    :meth:`add_edge`.  Execution is driven by :meth:`tick`, which
    evaluates the graph state and fires every *ready* node once per
    call.

    The graph preserves full execution history so that a run can be
    replayed from an event log.
    """

    def __init__(self, record_contexts: bool = False) -> None:
        self._nodes: Dict[str, BaseNode] = {}
        self._edges: List[CausalEdge] = []
        # Adjacency: predecessor sets keyed by target node ID
        self._predecessors: Dict[str, Set[str]] = {}
        # Adjacency: successor sets keyed by source node ID
        self._successors: Dict[str, Set[str]] = {}
        # Execution history: list of (node_id, result) pairs
        self.execution_history: List[Dict[str, Any]] = []
        # When True, each history entry also stores the context snapshot
        # at the time the node executed (used by the proof engine)
        self.record_contexts: bool = record_contexts

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(self, node: BaseNode) -> "CausalGraph":
        """Register a node in the graph and return *self* for chaining."""
        self._nodes[node.id] = node
        self._predecessors.setdefault(node.id, set())
        self._successors.setdefault(node.id, set())
        return self

    def add_edge(self, source: BaseNode, target: BaseNode, label: str = "causes") -> "CausalGraph":
        """
        Add a directed causal edge from *source* to *target*.

        Both nodes must already be registered via :meth:`add_node`.
        """
        if source.id not in self._nodes:
            raise ValueError(f"Source node '{source.name}' is not registered in this graph")
        if target.id not in self._nodes:
            raise ValueError(f"Target node '{target.name}' is not registered in this graph")
        edge = CausalEdge(source_id=source.id, target_id=target.id, label=label)
        self._edges.append(edge)
        self._successors[source.id].add(target.id)
        self._predecessors[target.id].add(source.id)
        return self

    # ------------------------------------------------------------------
    # Graph inspection
    # ------------------------------------------------------------------

    @property
    def nodes(self) -> List[BaseNode]:
        """All nodes in insertion order."""
        return list(self._nodes.values())

    @property
    def edges(self) -> List[CausalEdge]:
        return list(self._edges)

    def get_node(self, node_id: str) -> Optional[BaseNode]:
        return self._nodes.get(node_id)

    def predecessors(self, node: BaseNode) -> List[BaseNode]:
        """Return all direct causal predecessors of *node*."""
        return [self._nodes[nid] for nid in self._predecessors.get(node.id, set())]

    def successors(self, node: BaseNode) -> List[BaseNode]:
        """Return all direct causal successors of *node*."""
        return [self._nodes[nid] for nid in self._successors.get(node.id, set())]

    # ------------------------------------------------------------------
    # Scheduling helpers
    # ------------------------------------------------------------------

    def get_ready_nodes(self) -> List[BaseNode]:
        """
        Return all nodes that are ready to execute.

        A node is *ready* when:
        1. Its current state is PENDING or READY.
        2. Every predecessor node is in state DONE.

        For :class:`~core.node_types.EventNode` specifically, the node
        must also have been triggered.
        """
        ready: List[BaseNode] = []
        for node in self._nodes.values():
            if node.state not in (NodeState.PENDING, NodeState.READY):
                continue
            preds = self._predecessors.get(node.id, set())
            if all(self._nodes[pid].state == NodeState.DONE for pid in preds):
                # EventNodes require an explicit trigger
                from .node_types import EventNode  # local import to avoid circular
                if isinstance(node, EventNode) and not node.is_triggered:
                    continue
                ready.append(node)
        return ready

    def get_root_nodes(self) -> List[BaseNode]:
        """Return nodes with no predecessors (graph entry points)."""
        return [n for n in self._nodes.values() if not self._predecessors.get(n.id)]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def tick(self, context: Optional[Dict[str, Any]] = None) -> List[BaseNode]:
        """
        Execute one scheduling cycle.

        Nodes are fired in waves: after each wave, newly-ready downstream
        nodes are discovered and fired as well, until no more nodes can
        execute in this cycle.  This ensures that a complete causal chain
        (condition → action → downstream action) fires atomically within
        a single ``tick()`` call.

        The *context* dict is shared across all node executions in this
        tick; node results are injected under their IDs so downstream
        nodes can consume them.

        Returns the list of nodes that were executed this cycle.
        """
        ctx: Dict[str, Any] = dict(context or {})

        # Inject existing node results into context
        for node in self._nodes.values():
            if node.state == NodeState.DONE and node.result is not None:
                ctx[node.id] = node.result

        all_executed: List[BaseNode] = []

        # Keep firing waves until the graph is quiescent
        attempted_this_tick: set = set()
        while True:
            wave = [n for n in self._topological_ready_nodes() if n.id not in attempted_this_tick]
            if not wave:
                break
            for node in wave:
                attempted_this_tick.add(node.id)
                try:
                    result = node.execute(ctx)
                    ctx[node.id] = result
                    entry: Dict[str, Any] = {"node_id": node.id, "name": node.name, "result": result}
                    if self.record_contexts:
                        entry["context"] = dict(ctx)
                    self.execution_history.append(entry)
                    all_executed.append(node)
                except RuntimeError:
                    # Node failed — record but keep going so independent branches run
                    entry = {"node_id": node.id, "name": node.name, "result": None, "error": True}
                    if self.record_contexts:
                        entry["context"] = dict(ctx)
                    self.execution_history.append(entry)

        return all_executed

    def absorb(self, other: "CausalGraph", reset_nodes: bool = False) -> "CausalGraph":
        """
        Merge all nodes and edges from *other* into this graph.

        After the merge every node that was in *other* is registered in
        *self* with its existing ID, and all causal edges from *other*
        are wired into *self*.  Node objects are *shared* (not copied),
        so mutations to a node in the original graph are visible here and
        vice-versa.

        Parameters
        ----------
        other : CausalGraph
            The graph whose nodes and edges to absorb.
        reset_nodes : bool
            When ``True``, reset every absorbed node to PENDING state
            before merging.  Useful when composing graphs that have
            already been executed.

        Returns *self* for chaining.
        """
        for node in other.nodes:
            if reset_nodes:
                node.reset()
            self._nodes[node.id] = node
            self._predecessors.setdefault(node.id, set())
            self._successors.setdefault(node.id, set())
        for edge in other.edges:
            # Avoid duplicate edges
            existing = {(e.source_id, e.target_id) for e in self._edges}
            if (edge.source_id, edge.target_id) not in existing:
                self._edges.append(edge)
                self._successors.setdefault(edge.source_id, set()).add(edge.target_id)
                self._predecessors.setdefault(edge.target_id, set()).add(edge.source_id)
        return self

    def reset(self) -> None:
        """Reset all nodes and clear execution history (for replay)."""
        for node in self._nodes.values():
            node.reset()
        self.execution_history.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _topological_ready_nodes(self) -> Iterable[BaseNode]:
        """
        Yield ready nodes in a topological order so that a node is
        always yielded after any of its predecessors that are also ready
        in this same cycle.
        """
        ready_ids: Set[str] = {n.id for n in self.get_ready_nodes()}
        visited: Set[str] = set()
        result: List[BaseNode] = []

        def _visit(nid: str) -> None:
            if nid in visited or nid not in ready_ids:
                return
            visited.add(nid)
            for pred_id in self._predecessors.get(nid, set()):
                _visit(pred_id)
            result.append(self._nodes[nid])

        for nid in list(ready_ids):
            _visit(nid)
        return result

    def __repr__(self) -> str:
        return (
            f"CausalGraph("
            f"nodes={len(self._nodes)}, "
            f"edges={len(self._edges)}, "
            f"history={len(self.execution_history)})"
        )
