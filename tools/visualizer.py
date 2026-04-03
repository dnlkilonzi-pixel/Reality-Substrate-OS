"""
Debug Visualizer — renders a causal graph as ASCII art or DOT notation.

:class:`Visualizer` works with any :class:`~core.causal_engine.CausalGraph`
and produces human-readable output without any third-party dependencies.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Set

if TYPE_CHECKING:
    from core.causal_engine import CausalGraph
    from core.node_types import BaseNode

from core.node_types import NodeState


# State → symbol mapping for ASCII render
_STATE_SYMBOLS = {
    NodeState.PENDING:   "○",
    NodeState.READY:     "●",
    NodeState.EXECUTING: "►",
    NodeState.DONE:      "✔",
    NodeState.FAILED:    "✘",
}

# Node type → short tag
_TYPE_TAGS = {
    "EventNode":     "EVT",
    "ConditionNode": "CND",
    "ActionNode":    "ACT",
    "TransformNode": "TRF",
}


class Visualizer:
    """
    Produces human-readable representations of a causal graph.

    Usage::

        viz = Visualizer(graph)
        print(viz.ascii())
        print(viz.dot())
    """

    def __init__(self, graph: "CausalGraph") -> None:
        self._graph = graph

    # ------------------------------------------------------------------
    # ASCII tree view
    # ------------------------------------------------------------------

    def ascii(self) -> str:
        """
        Render the graph as a tree starting from root nodes.

        Each node line shows:
        * State symbol
        * Short type tag
        * Node name
        * Result (if available)
        """
        lines: List[str] = ["Causal Graph — ASCII View", "=" * 50]
        roots = self._graph.get_root_nodes()
        if not roots:
            roots = self._graph.nodes[:1]  # fallback: show first node
        visited: Set[str] = set()
        for root in roots:
            self._ascii_subtree(root, "", True, lines, visited)
        if not lines[2:]:
            lines.append("  (empty graph)")
        return "\n".join(lines)

    def _ascii_subtree(
        self,
        node: "BaseNode",
        prefix: str,
        is_last: bool,
        lines: List[str],
        visited: Set[str],
    ) -> None:
        connector = "└── " if is_last else "├── "
        sym = _STATE_SYMBOLS.get(node.state, "?")
        tag = _TYPE_TAGS.get(type(node).__name__, "???")
        result_str = f"  → {node.result!r}" if node.result is not None else ""
        cycle_marker = " (↻)" if node.id in visited else ""
        lines.append(f"{prefix}{connector}{sym} [{tag}] {node.name}{result_str}{cycle_marker}")
        if node.id in visited:
            return
        visited.add(node.id)
        children = self._graph.successors(node)
        for i, child in enumerate(children):
            child_prefix = prefix + ("    " if is_last else "│   ")
            self._ascii_subtree(child, child_prefix, i == len(children) - 1, lines, visited)

    # ------------------------------------------------------------------
    # DOT (Graphviz) notation
    # ------------------------------------------------------------------

    def dot(self) -> str:
        """
        Render the graph in Graphviz DOT notation.

        The output can be saved to a ``.dot`` file and rendered with
        ``dot -Tpng graph.dot -o graph.png``.
        """
        lines = ["digraph CausalGraph {", "    rankdir=LR;", "    node [shape=box, style=filled];"]
        color_map = {
            "EventNode":     "lightblue",
            "ConditionNode": "lightyellow",
            "ActionNode":    "lightgreen",
            "TransformNode": "lightsalmon",
        }
        for node in self._graph.nodes:
            color = color_map.get(type(node).__name__, "white")
            label = node.name.replace('"', '\\"')
            state = node.state.name
            lines.append(f'    "{node.id}" [label="{label}\\n[{state}]", fillcolor="{color}"];')
        for edge in self._graph.edges:
            lines.append(f'    "{edge.source_id}" -> "{edge.target_id}" [label="{edge.label}"];')
        lines.append("}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Flat node list
    # ------------------------------------------------------------------

    def node_table(self) -> str:
        """
        Return a tabular summary of all nodes with their current state.
        """
        col_widths = (8, 14, 34, 10, 20)
        header = (
            f"{'ID':8}  {'Type':14}  {'Name':34}  {'State':10}  {'Result':20}"
        )
        sep = "-" * (sum(col_widths) + 8)
        lines = [header, sep]
        for node in self._graph.nodes:
            nid = node.id[:8]
            ntype = type(node).__name__
            nname = node.name[:34]
            nstate = node.state.name
            nresult = str(node.result)[:20] if node.result is not None else ""
            lines.append(f"{nid}  {ntype:14}  {nname:34}  {nstate:10}  {nresult:20}")
        return "\n".join(lines)
