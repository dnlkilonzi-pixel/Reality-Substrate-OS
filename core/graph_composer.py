"""
Cross-Graph Composition for RS-CCE.

Two causal graphs can be composed into a **meta-graph**::

    meta = GraphComposer.compose(graph_a, graph_b, bridges=[
        GraphBridge(source_node_id=a_leaf.id, target_node_id=b_root.id),
    ])

The resulting meta-graph contains every node and edge from both
sub-graphs, plus the explicit *bridge* edges that wire an output node
in Graph A to an input node in Graph B.

This enables:

* Distributed causal systems built from modular sub-graphs.
* Causal microservices: each graph encapsulates an independent concern;
  bridge edges propagate causality across service boundaries.
* Plug-and-play system behaviour: swap Graph B for Graph C without
  touching Graph A.

``GraphComposer.compose_sequential(a, b)`` is a convenience helper
that automatically bridges every *leaf* node of Graph A to every *root*
node of Graph B — the functional-composition idiom ``A ∘ B``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.causal_engine import CausalGraph


@dataclass
class GraphBridge:
    """
    A directed causal edge that crosses graph boundaries.

    Attributes
    ----------
    source_node_id : str
        ID of the output (source) node in Graph A.
    target_node_id : str
        ID of the input (target) node in Graph B.
    label : str
        Edge label (default ``"bridges"``).
    """

    source_node_id: str
    target_node_id: str
    label: str = "bridges"


class GraphComposer:
    """
    Composes two :class:`~core.causal_engine.CausalGraph` instances into
    a single meta-graph.

    Usage
    -----
    Explicit bridges::

        bridge = GraphBridge(
            source_node_id=leaf_of_a.id,
            target_node_id=root_of_b.id,
        )
        meta = GraphComposer.compose(graph_a, graph_b, bridges=[bridge])

    Automatic sequential composition (A ∘ B)::

        meta = GraphComposer.compose_sequential(graph_a, graph_b)
    """

    @staticmethod
    def compose(
        graph_a: CausalGraph,
        graph_b: CausalGraph,
        bridges: Optional[List[GraphBridge]] = None,
        reset_nodes: bool = True,
    ) -> CausalGraph:
        """
        Merge *graph_a* and *graph_b* into a new meta-graph.

        Parameters
        ----------
        graph_a : CausalGraph
            First (upstream) sub-graph.
        graph_b : CausalGraph
            Second (downstream) sub-graph.
        bridges : list of GraphBridge, optional
            Explicit causal edges to add from nodes in *graph_a* to
            nodes in *graph_b*.  If omitted, no cross-graph edges are
            created (the sub-graphs execute independently inside the
            meta-graph).
        reset_nodes : bool
            Reset all node states to PENDING before composing
            (default ``True``).

        Returns
        -------
        CausalGraph
            The new meta-graph containing all nodes and edges from both
            sub-graphs plus the bridge edges.
        """
        meta = CausalGraph()
        meta.absorb(graph_a, reset_nodes=reset_nodes)
        meta.absorb(graph_b, reset_nodes=reset_nodes)

        for bridge in (bridges or []):
            source = meta.get_node(bridge.source_node_id)
            target = meta.get_node(bridge.target_node_id)
            if source is None:
                raise ValueError(
                    f"Bridge source node '{bridge.source_node_id}' not found in either graph"
                )
            if target is None:
                raise ValueError(
                    f"Bridge target node '{bridge.target_node_id}' not found in either graph"
                )
            meta.add_edge(source, target, label=bridge.label)

        return meta

    @staticmethod
    def compose_sequential(
        graph_a: CausalGraph,
        graph_b: CausalGraph,
        bridge_label: str = "bridges",
        reset_nodes: bool = True,
    ) -> CausalGraph:
        """
        Compose *graph_a* and *graph_b* sequentially (A ∘ B).

        Every *leaf* node of Graph A (nodes with no successors) is
        connected to every *root* node of Graph B (nodes with no
        predecessors) via a bridge edge.

        This is the functional-composition shorthand: Graph B executes
        only after Graph A has fully completed.
        """
        leaves_a = [
            n for n in graph_a.nodes if not graph_a.successors(n)
        ]
        roots_b = graph_b.get_root_nodes()

        if not leaves_a:
            raise ValueError("Graph A has no leaf nodes to bridge from")
        if not roots_b:
            raise ValueError("Graph B has no root nodes to bridge to")

        bridges = [
            GraphBridge(
                source_node_id=leaf.id,
                target_node_id=root.id,
                label=bridge_label,
            )
            for leaf in leaves_a
            for root in roots_b
        ]
        return GraphComposer.compose(graph_a, graph_b, bridges=bridges, reset_nodes=reset_nodes)
