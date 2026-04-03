"""
Graph Monitor — live introspection of causal graph state.

:class:`GraphMonitor` wraps a :class:`~core.causal_engine.CausalGraph`
and provides a structured view of:

* Per-node state summaries
* Topology (edges, roots, leaves)
* Execution statistics
* Serialisable snapshots for external tooling
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.causal_engine import CausalGraph
from core.node_types import BaseNode, NodeState


class GraphMonitor:
    """
    Live introspection wrapper around a :class:`~core.causal_engine.CausalGraph`.

    Usage::

        monitor = GraphMonitor(graph)
        print(monitor.summary())
        snapshot = monitor.snapshot()
    """

    def __init__(self, graph: CausalGraph) -> None:
        self._graph = graph
        self._snapshots: List[Dict[str, Any]] = []
        self._start_time: float = time.time()

    # ------------------------------------------------------------------
    # Node-level inspection
    # ------------------------------------------------------------------

    def node_status(self, node: Optional[BaseNode] = None) -> Dict[str, Any]:
        """
        Return a status dict for *node*, or a dict keyed by node ID for
        all nodes when *node* is ``None``.
        """
        if node is not None:
            return self._node_dict(node)
        return {n.id: self._node_dict(n) for n in self._graph.nodes}

    def _node_dict(self, node: BaseNode) -> Dict[str, Any]:
        return {
            "id": node.id,
            "name": node.name,
            "type": type(node).__name__,
            "state": node.state.name,
            "result": node.result,
            "metadata": node.metadata,
        }

    # ------------------------------------------------------------------
    # Topology
    # ------------------------------------------------------------------

    def root_nodes(self) -> List[Dict[str, Any]]:
        """Return status dicts for nodes with no predecessors."""
        return [self._node_dict(n) for n in self._graph.get_root_nodes()]

    def leaf_nodes(self) -> List[Dict[str, Any]]:
        """Return status dicts for nodes with no successors."""
        return [
            self._node_dict(n)
            for n in self._graph.nodes
            if not self._graph.successors(n)
        ]

    def edges_summary(self) -> List[Dict[str, str]]:
        """Return a list of edge dicts with source/target names and labels."""
        result = []
        for edge in self._graph.edges:
            src = self._graph.get_node(edge.source_id)
            tgt = self._graph.get_node(edge.target_id)
            result.append({
                "source": src.name if src else edge.source_id,
                "target": tgt.name if tgt else edge.target_id,
                "label": edge.label,
            })
        return result

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return aggregate execution statistics."""
        counts: Dict[str, int] = {s.name: 0 for s in NodeState}
        for node in self._graph.nodes:
            counts[node.state.name] += 1
        return {
            "total_nodes": len(self._graph.nodes),
            "total_edges": len(self._graph.edges),
            "state_counts": counts,
            "executions": len(self._graph.execution_history),
            "uptime_seconds": time.time() - self._start_time,
        }

    # ------------------------------------------------------------------
    # Full snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """
        Capture a full point-in-time snapshot of the graph.

        Snapshots are appended to :attr:`snapshots` for later comparison
        or replay.
        """
        snap = {
            "timestamp": time.time(),
            "nodes": [self._node_dict(n) for n in self._graph.nodes],
            "edges": self.edges_summary(),
            "stats": self.stats(),
            "history": list(self._graph.execution_history),
        }
        self._snapshots.append(snap)
        return snap

    @property
    def snapshots(self) -> List[Dict[str, Any]]:
        """All previously captured snapshots."""
        return list(self._snapshots)

    # ------------------------------------------------------------------
    # Human-readable summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a multi-line human-readable summary of graph state."""
        lines = [
            f"{'='*60}",
            f"  Causal Graph Monitor",
            f"{'='*60}",
            f"  Nodes  : {len(self._graph.nodes)}",
            f"  Edges  : {len(self._graph.edges)}",
            f"  History: {len(self._graph.execution_history)} executions",
            f"{'─'*60}",
        ]
        for node in self._graph.nodes:
            state_marker = {
                NodeState.PENDING: "○",
                NodeState.READY: "●",
                NodeState.EXECUTING: "►",
                NodeState.DONE: "✔",
                NodeState.FAILED: "✘",
            }.get(node.state, "?")
            lines.append(f"  {state_marker} [{type(node).__name__:14}] {node.name}")
        lines.append(f"{'='*60}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"GraphMonitor(nodes={len(self._graph.nodes)}, snapshots={len(self._snapshots)})"
