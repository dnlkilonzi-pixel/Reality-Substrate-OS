"""
Core module for the Reality Substrate + Causal Computing Engine (RS-CCE).

Contains the causal graph engine, event bus, node type definitions,
cross-graph composition utilities, and formal semantics.
"""
from .node_types import (
    NodeState,
    BaseNode,
    EventNode,
    ConditionNode,
    ActionNode,
    TransformNode,
)
from .causal_engine import CausalGraph, CausalEdge
from .event_bus import EventBus, Event
from .graph_composer import GraphBridge, GraphComposer
from .formal_semantics import CausalSemantics, GraphDelta

__all__ = [
    "NodeState",
    "BaseNode",
    "EventNode",
    "ConditionNode",
    "ActionNode",
    "TransformNode",
    "CausalGraph",
    "CausalEdge",
    "EventBus",
    "Event",
    "GraphBridge",
    "GraphComposer",
    "CausalSemantics",
    "GraphDelta",
]
