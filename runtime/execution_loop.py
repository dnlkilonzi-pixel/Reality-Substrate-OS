"""
Execution Loop — the RS-CCE main runtime loop.

:class:`ExecutionLoop` ties together all components:

* :class:`~core.causal_engine.CausalGraph`  — the live causal graph
* :class:`~core.event_bus.EventBus`          — event pub/sub
* :class:`~runtime.state_store.StateStore`   — shared system state
* :class:`~reality_layers.base_layer.LayerStack` — pluggable OS semantics
* :class:`~runtime.graph_monitor.GraphMonitor`   — introspection

Each *tick* of the loop:

1. Drains queued events from the layer stack and event bus.
2. Updates ``EventNode`` triggers from matching bus events.
3. Builds a context snapshot from the state store.
4. Calls :meth:`~core.causal_engine.CausalGraph.tick` to fire ready nodes.
5. Applies node results back to the state store.
6. Repeats until the graph is quiescent (no more ready nodes) or the
   maximum tick count is reached.

New rules can be injected at runtime via :meth:`inject_rule`.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from core.causal_engine import CausalGraph
from core.event_bus import Event, EventBus
from core.node_types import EventNode, NodeState
from reality_layers.base_layer import BaseLayer, LayerStack
from runtime.graph_monitor import GraphMonitor
from runtime.state_store import StateStore


class ExecutionLoop:
    """
    Drives continuous causal graph evaluation.

    Parameters
    ----------
    graph : CausalGraph
        The causal graph to execute.
    state_store : StateStore, optional
        Shared state snapshot.  Created automatically if not supplied.
    event_bus : EventBus, optional
        System-wide event bus.  Created automatically if not supplied.
    layer_stack : LayerStack, optional
        Reality layer stack.  A bare :class:`~reality_layers.base_layer.BaseLayer`
        is pushed automatically if not supplied.
    max_ticks : int
        Maximum number of tick cycles before the loop stops (safety
        guard against infinite loops).  Default is ``1000``.
    tick_delay : float
        Seconds to sleep between ticks when running in *continuous*
        mode.  Default is ``0.0`` (no sleep).
    """

    def __init__(
        self,
        graph: CausalGraph,
        state_store: Optional[StateStore] = None,
        event_bus: Optional[EventBus] = None,
        layer_stack: Optional[LayerStack] = None,
        max_ticks: int = 1000,
        tick_delay: float = 0.0,
    ) -> None:
        self.graph = graph
        self.state = state_store if state_store is not None else StateStore()
        self.bus = event_bus if event_bus is not None else EventBus()
        self.layers = layer_stack if layer_stack is not None else LayerStack()
        if not self.layers.layers:
            self.layers.push(BaseLayer())
        self.monitor = GraphMonitor(graph)
        self.max_ticks = max_ticks
        self.tick_delay = tick_delay
        self._tick_count: int = 0
        self._running: bool = False
        self._on_tick_callbacks: List[Callable[["ExecutionLoop"], None]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Run the loop until quiescent or *max_ticks* is reached."""
        self._running = True
        while self._running and self._tick_count < self.max_ticks:
            executed = self._do_tick()
            if not executed:
                break  # graph is quiescent
            if self.tick_delay > 0:
                time.sleep(self.tick_delay)
        self._running = False

    def stop(self) -> None:
        """Signal the loop to stop after the current tick."""
        self._running = False

    def tick_once(self) -> List[Any]:
        """Execute exactly one tick and return the list of executed nodes."""
        return self._do_tick()

    # ------------------------------------------------------------------
    # Runtime rule injection
    # ------------------------------------------------------------------

    def inject_rule(self, source: str, action_registry: Optional[Dict[str, Callable[..., Any]]] = None) -> None:
        """
        Parse and compile a DSL rule string and add it to the live graph.

        This supports hot-loading new behaviour without stopping the loop.
        """
        from dsl.parser import RuleParser
        from dsl.compiler import DSLCompiler

        parser = RuleParser()
        compiler = DSLCompiler(action_registry=action_registry or {})
        rules = parser.parse(source)
        compiler.compile(rules, graph=self.graph)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_tick(self, callback: Callable[["ExecutionLoop"], None]) -> None:
        """Register a callback invoked after each tick."""
        self._on_tick_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Internal tick implementation
    # ------------------------------------------------------------------

    def _do_tick(self) -> List[Any]:
        self._tick_count += 1

        # 1. Drain layer events and publish them onto the bus
        for ev in self.layers.drain_all_events():
            self.bus.publish(Event(ev["event_type"], ev["data"], source="layer"))

        # 2. Trigger EventNodes that match pending bus events
        self._sync_event_nodes()

        # 3. Build execution context from current state
        ctx = self.state.snapshot()
        ctx["__time__"] = self.layers.time_now()
        ctx["__tick__"] = self._tick_count

        # 4. Execute one graph tick
        executed = self.graph.tick(ctx)

        # 5. Write action results back to state store
        for node in executed:
            if node.result is not None and isinstance(node.result, dict):
                self.state.update(node.result)

        # 6. Invoke tick callbacks
        for cb in self._on_tick_callbacks:
            cb(self)

        return executed

    def _sync_event_nodes(self) -> None:
        """
        Check the event bus history and trigger any matching EventNodes
        that have not yet been triggered.
        """
        for node in self.graph.nodes:
            if isinstance(node, EventNode) and not node.is_triggered:
                matching = self.bus.get_events(node.event_type)
                if matching:
                    node.trigger(matching[-1].data)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def is_running(self) -> bool:
        return self._running

    def __repr__(self) -> str:
        return (
            f"ExecutionLoop("
            f"ticks={self._tick_count}, "
            f"running={self._running}, "
            f"nodes={len(self.graph.nodes)})"
        )
