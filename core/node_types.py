"""
Node type definitions for the Causal Computing Engine.

Defines the building blocks of causal graphs:
- EventNode   : input signals, metrics, syscalls
- ConditionNode: logical evaluation gates
- ActionNode  : system effects and outputs
- TransformNode: data mutation and processing
"""
from __future__ import annotations

import uuid
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional


class NodeState(Enum):
    """Lifecycle state of a causal node."""

    PENDING = auto()     # Not yet eligible to execute
    READY = auto()       # All causal dependencies satisfied
    EXECUTING = auto()   # Currently running
    DONE = auto()        # Completed successfully
    FAILED = auto()      # Encountered an error


class BaseNode:
    """
    Abstract base for all causal-graph nodes.

    Every node has a unique ID, a human-readable name, a current state,
    and an optional metadata dictionary for arbitrary annotations.
    """

    def __init__(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.id: str = str(uuid.uuid4())
        self.name: str = name
        self.state: NodeState = NodeState.PENDING
        self.metadata: Dict[str, Any] = metadata or {}
        self._result: Any = None

    @property
    def result(self) -> Any:
        """Return the value produced by the last execution."""
        return self._result

    def reset(self) -> None:
        """Reset the node to its initial PENDING state."""
        self.state = NodeState.PENDING
        self._result = None

    def execute(self, context: Dict[str, Any]) -> Any:
        """
        Execute the node logic.

        Sub-classes override this method.  The *context* dict carries
        the current system-state snapshot as well as the results of
        upstream nodes (keyed by their IDs).

        Returns the produced value, which is also stored as ``self._result``.
        """
        raise NotImplementedError(f"{type(self).__name__}.execute() not implemented")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id={self.id[:8]}, name={self.name!r}, state={self.state.name})"


class EventNode(BaseNode):
    """
    Represents an input signal, metric reading, or syscall observation.

    An EventNode is *satisfied* (transitions to DONE) as soon as its
    associated event has been fired into the graph.  The value of that
    event is stored as the node result.
    """

    def __init__(self, name: str, event_type: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, metadata)
        self.event_type: str = event_type
        self._triggered: bool = False
        self._event_value: Any = None

    def trigger(self, value: Any = None) -> None:
        """Mark this node as triggered with an optional payload."""
        self._triggered = True
        self._event_value = value
        self.state = NodeState.READY

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    def execute(self, context: Dict[str, Any]) -> Any:
        self.state = NodeState.EXECUTING
        self._result = self._event_value
        self.state = NodeState.DONE
        return self._result


class ConditionNode(BaseNode):
    """
    A logical gate that evaluates a predicate over system/graph state.

    The predicate is a callable that receives the current *context* dict
    and returns ``True`` (condition met) or ``False`` (condition not met).

    When the predicate returns ``False`` the node transitions to PENDING,
    making downstream nodes ineligible to execute.
    """

    def __init__(
        self,
        name: str,
        predicate: Callable[[Dict[str, Any]], bool],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, metadata)
        self.predicate: Callable[[Dict[str, Any]], bool] = predicate

    def execute(self, context: Dict[str, Any]) -> bool:
        self.state = NodeState.EXECUTING
        try:
            result: bool = bool(self.predicate(context))
        except Exception as exc:  # noqa: BLE001
            self.state = NodeState.FAILED
            self._result = False
            raise RuntimeError(f"ConditionNode '{self.name}' predicate raised: {exc}") from exc
        self._result = result
        self.state = NodeState.DONE if result else NodeState.PENDING
        return result


class ActionNode(BaseNode):
    """
    Executes a system-level effect when its causal dependencies are met.

    The *action* callable receives the current *context* and may produce
    an optional return value.  Side-effects (logging, scheduling changes,
    IO writes) belong here.
    """

    def __init__(
        self,
        name: str,
        action: Callable[[Dict[str, Any]], Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, metadata)
        self.action: Callable[[Dict[str, Any]], Any] = action

    def execute(self, context: Dict[str, Any]) -> Any:
        self.state = NodeState.EXECUTING
        try:
            self._result = self.action(context)
        except Exception as exc:  # noqa: BLE001
            self.state = NodeState.FAILED
            raise RuntimeError(f"ActionNode '{self.name}' action raised: {exc}") from exc
        self.state = NodeState.DONE
        return self._result


class TransformNode(BaseNode):
    """
    Mutates or derives data from upstream node outputs.

    The *transform* callable receives the *context* dict and should
    return the transformed value.  This is useful for metric conversion,
    aggregation, or any pure data-processing step in the causal chain.
    """

    def __init__(
        self,
        name: str,
        transform: Callable[[Dict[str, Any]], Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, metadata)
        self.transform: Callable[[Dict[str, Any]], Any] = transform

    def execute(self, context: Dict[str, Any]) -> Any:
        self.state = NodeState.EXECUTING
        try:
            self._result = self.transform(context)
        except Exception as exc:  # noqa: BLE001
            self.state = NodeState.FAILED
            raise RuntimeError(f"TransformNode '{self.name}' transform raised: {exc}") from exc
        self.state = NodeState.DONE
        return self._result
