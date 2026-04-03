"""
Formal Semantics for RS-CCE.

Provides a rigorous mathematical specification of the causal computing model,
bridging the gap between engineering implementation and formal theory.

Mathematical Model
------------------
Let:
  S ∈ State  — a key/value mapping representing the system state
  G ∈ Graph  — the directed causal dependency graph
  E ∈ Events — the set of input events arriving in one tick

Three fundamental operators formalise the system's behaviour:

**1. State Transition Function**::

    S(t+1) = F(S(t), G, E)

The next state is a deterministic function of the current state, the causal
graph structure, and the arriving events.  There is no hidden state: given the
same inputs the function always returns the same output.

**2. Causal Activation Predicate**::

    activate(n) ⟺ dependency_satisfied(n, G, S)

A node *n* is eligible to fire iff all of its direct causal predecessors in *G*
have reached state DONE, and (for ConditionNodes) its predicate evaluates to
True in state *S*.

**3. Graph Evolution Operator**::

    G' = G ⊕ ΔG

The graph structure can evolve incrementally.  A :class:`GraphDelta` (ΔG)
specifies additions and removals of nodes and edges; applying it to *G* yields
the evolved graph *G'* without modifying the original.

Without formal semantics the system stays "engineering".
With them it becomes "research".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from core.causal_engine import CausalEdge, CausalGraph
from core.node_types import ActionNode, BaseNode, ConditionNode, EventNode, NodeState


# ===========================================================================
# ΔG — Graph Delta
# ===========================================================================

@dataclass
class GraphDelta:
    """
    ΔG — an incremental change to a causal graph.

    A :class:`GraphDelta` describes the difference between two graph states.
    Applying it with :meth:`CausalSemantics.evolve` yields a new graph without
    modifying the original.

    Attributes
    ----------
    nodes_added : list of BaseNode
        New nodes to insert into the evolved graph.
    edges_added : list of CausalEdge
        New causal edges to add (both endpoints must exist in G or
        in *nodes_added*).
    nodes_removed : list of str
        IDs of nodes to remove.  Any edges that reference a removed node
        are also removed automatically.
    edges_removed : list of (source_id, target_id)
        Specific edges to remove.
    """

    nodes_added: List[BaseNode] = field(default_factory=list)
    edges_added: List[CausalEdge] = field(default_factory=list)
    nodes_removed: List[str] = field(default_factory=list)
    edges_removed: List[Tuple[str, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return ``True`` iff this delta carries no changes."""
        return not (
            self.nodes_added
            or self.edges_added
            or self.nodes_removed
            or self.edges_removed
        )

    def __repr__(self) -> str:
        return (
            f"GraphDelta("
            f"+{len(self.nodes_added)} nodes, "
            f"+{len(self.edges_added)} edges, "
            f"-{len(self.nodes_removed)} nodes, "
            f"-{len(self.edges_removed)} edges)"
        )


# ===========================================================================
# Formal Semantics Operators
# ===========================================================================

class CausalSemantics:
    """
    Formal semantics of the RS-CCE causal computing model.

    All methods are **pure functions** over their logical inputs: they return
    new objects or values without modifying the caller's graph or state.

    .. note::
        :meth:`transition` resets and executes the graph nodes as a necessary
        implementation side-effect (Python nodes carry mutable state).  Pass a
        freshly-constructed or reset graph to avoid surprises.
    """

    # ------------------------------------------------------------------
    # 1. State Transition: S(t+1) = F(S(t), G, E)
    # ------------------------------------------------------------------

    @staticmethod
    def transition(
        state: Dict[str, Any],
        graph: CausalGraph,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Compute the next state **S(t+1) = F(S(t), G, E)**.

        The graph is reset, all events are applied, one tick is executed, and
        the resulting state is returned.  The input *state* dict is never
        modified.

        Parameters
        ----------
        state : dict
            Current system state S(t).
        graph : CausalGraph
            The causal graph G that defines the transition rules.
        events : list of event dicts, optional
            Input events E.  Each dict requires ``"event_type"`` and
            optionally ``"data"`` and ``"source"`` keys.

        Returns
        -------
        dict
            The next state S(t+1).

        Example
        -------
        ::

            cond = ConditionNode("high_cpu", lambda ctx: ctx.get("cpu") > 80)
            act  = ActionNode("throttle", lambda ctx: {"throttled": True})
            graph.add_node(cond).add_node(act)
            graph.add_edge(cond, act)

            s_next = CausalSemantics.transition({"cpu": 90}, graph)
            assert s_next["throttled"] is True
        """
        from core.event_bus import Event, EventBus

        # Reset graph nodes so we start from a clean slate
        graph.reset()

        # Trigger EventNodes from the supplied events
        bus = EventBus()
        for ev in (events or []):
            bus.publish(Event(
                event_type=ev.get("event_type", ""),
                data=ev.get("data", {}),
                source=ev.get("source"),
            ))
        for node in graph.nodes:
            if isinstance(node, EventNode):
                matching = bus.get_events(node.event_type)
                if matching:
                    node.trigger(matching[-1].data)

        # Execute one tick
        ctx = dict(state)
        executed = graph.tick(ctx)

        # Collect mutations from action results
        next_state = dict(state)
        for node in executed:
            if node.result is not None and isinstance(node.result, dict):
                next_state.update(node.result)

        return next_state

    # ------------------------------------------------------------------
    # 2. Causal Activation: activate(n) ⟺ dependency_satisfied(n, G, S)
    # ------------------------------------------------------------------

    @staticmethod
    def activation_satisfied(
        node: BaseNode,
        graph: CausalGraph,
        state: Dict[str, Any],
    ) -> bool:
        """
        Evaluate the causal activation predicate for *node*.

        Returns ``True`` iff:

        1. All direct predecessors of *node* in *graph* have state DONE.
        2. For :class:`~core.node_types.ConditionNode`: the predicate also
           evaluates to ``True`` against *state*.
        3. For :class:`~core.node_types.EventNode`: ``is_triggered == True``.

        This is a **read-only** check; no node state is mutated.
        """
        # Structural dependency: all predecessors must be DONE
        preds = graph.predecessors(node)
        if not all(p.state == NodeState.DONE for p in preds):
            return False

        # Semantic condition per node type
        if isinstance(node, EventNode):
            return node.is_triggered

        if isinstance(node, ConditionNode):
            try:
                return bool(node.predicate(state))
            except Exception:
                return False

        # ActionNode, TransformNode — structural dependency is sufficient
        return True

    # ------------------------------------------------------------------
    # 3. Graph Evolution: G' = G ⊕ ΔG
    # ------------------------------------------------------------------

    @staticmethod
    def evolve(graph: CausalGraph, delta: GraphDelta) -> CausalGraph:
        """
        Apply *delta* to *graph* and return the evolved graph **G' = G ⊕ ΔG**.

        The original *graph* is **not modified**.  A new :class:`~core.causal_engine.CausalGraph`
        is constructed containing:

        * All nodes from *graph* not listed in ``delta.nodes_removed``.
        * All edges from *graph* not listed in ``delta.edges_removed`` and not
          incident to removed nodes.
        * All nodes in ``delta.nodes_added``.
        * All edges in ``delta.edges_added`` (both endpoints must already be
          in the evolved graph or in ``delta.nodes_added``).

        Parameters
        ----------
        graph : CausalGraph
            The original graph G.
        delta : GraphDelta
            The evolution delta ΔG.

        Returns
        -------
        CausalGraph
            The new graph G' = G ⊕ ΔG.

        Raises
        ------
        ValueError
            If an edge in ``delta.edges_added`` references a node that does
            not exist in the evolved graph.
        """
        evolved = CausalGraph(record_contexts=graph.record_contexts)

        removed_node_ids: Set[str] = set(delta.nodes_removed)
        removed_edge_pairs: Set[Tuple[str, str]] = set(delta.edges_removed)

        # Copy surviving nodes
        for node in graph.nodes:
            if node.id not in removed_node_ids:
                evolved._nodes[node.id] = node
                evolved._predecessors.setdefault(node.id, set())
                evolved._successors.setdefault(node.id, set())

        # Copy surviving edges
        for edge in graph.edges:
            if (edge.source_id, edge.target_id) in removed_edge_pairs:
                continue
            if edge.source_id in removed_node_ids or edge.target_id in removed_node_ids:
                continue
            evolved._edges.append(edge)
            evolved._successors.setdefault(edge.source_id, set()).add(edge.target_id)
            evolved._predecessors.setdefault(edge.target_id, set()).add(edge.source_id)

        # Apply added nodes
        for node in delta.nodes_added:
            evolved._nodes[node.id] = node
            evolved._predecessors.setdefault(node.id, set())
            evolved._successors.setdefault(node.id, set())

        # Apply added edges
        existing_pairs: Set[Tuple[str, str]] = {(e.source_id, e.target_id) for e in evolved._edges}
        for edge in delta.edges_added:
            if edge.source_id not in evolved._nodes:
                raise ValueError(
                    f"Edge source '{edge.source_id}' not present in evolved graph"
                )
            if edge.target_id not in evolved._nodes:
                raise ValueError(
                    f"Edge target '{edge.target_id}' not present in evolved graph"
                )
            if (edge.source_id, edge.target_id) not in existing_pairs:
                evolved._edges.append(edge)
                evolved._successors[edge.source_id].add(edge.target_id)
                evolved._predecessors[edge.target_id].add(edge.source_id)
                existing_pairs.add((edge.source_id, edge.target_id))

        return evolved

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @staticmethod
    def ready_set(graph: CausalGraph, state: Dict[str, Any]) -> List[BaseNode]:
        """
        Return all nodes whose activation condition is currently satisfied.

        This is the set **R(G, S) = { n ∈ G | activation_satisfied(n, G, S) }**.
        """
        return [
            n
            for n in graph.nodes
            if n.state in (NodeState.PENDING, NodeState.READY)
            and CausalSemantics.activation_satisfied(n, graph, state)
        ]

    @staticmethod
    def causal_depth(node: BaseNode, graph: CausalGraph) -> int:
        """
        Return the maximum causal depth of *node* in *graph*.

        Defined as the length of the longest causal path from any root node
        to *node*.  Root nodes (no predecessors) have depth 0.
        """
        memo: Dict[str, int] = {}

        def _depth(nid: str) -> int:
            if nid in memo:
                return memo[nid]
            preds = graph._predecessors.get(nid, set())
            memo[nid] = 0 if not preds else 1 + max(_depth(pid) for pid in preds)
            return memo[nid]

        return _depth(node.id)

    @staticmethod
    def reachable(source: BaseNode, graph: CausalGraph) -> List[BaseNode]:
        """
        Return all nodes causally reachable from *source* (i.e. all descendants
        in the directed graph).
        """
        visited: Set[str] = set()
        result: List[BaseNode] = []

        def _dfs(nid: str) -> None:
            for succ_id in graph._successors.get(nid, set()):
                if succ_id not in visited:
                    visited.add(succ_id)
                    result.append(graph._nodes[succ_id])
                    _dfs(succ_id)

        _dfs(source.id)
        return result
