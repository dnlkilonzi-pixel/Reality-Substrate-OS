"""
Causal Replay Engine — deterministic time-machine for computation.

:class:`CausalReplayEngine` re-executes a past run with byte-identical
results by:

1. Building a **fresh** causal graph from the original DSL rules.
2. Restoring the initial system state from a saved snapshot.
3. Re-publishing the original event sequence through a fresh
   :class:`~core.event_bus.EventBus`.
4. Running the execution loop under a
   :class:`~reality_layers.deterministic_layer.DeterministicLayer`
   (or a user-supplied layer stack) so that time, memory, and I/O are
   fully reproducible.

Because every source of non-determinism is eliminated, the execution
history of the replayed run is identical to the original.

Usage::

    # --- Original run ---
    parser   = RuleParser()
    compiler = DSLCompiler(action_registry=my_registry)
    rules    = parser.parse(my_rules_source)
    graph    = compiler.compile(rules)

    state = StateStore({"cpu_usage": 90})
    bus   = EventBus()
    tracer = EventTracer(bus)
    loop  = ExecutionLoop(graph, state_store=state, event_bus=bus)
    loop.start()

    # Persist artefacts
    tracer.save("/tmp/trace.json")
    original_snapshot = state.snapshot()

    # --- Replay ---
    engine = CausalReplayEngine(
        rules_source=my_rules_source,
        action_registry=my_registry,
    )
    replay_loop = engine.replay(
        initial_state=original_snapshot,
        event_trace=tracer.trace,
    )
    assert replay_loop.graph.execution_history == loop.graph.execution_history
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.causal_engine import CausalGraph
from core.event_bus import Event, EventBus
from reality_layers.base_layer import LayerStack
from reality_layers.deterministic_layer import DeterministicLayer
from runtime.execution_loop import ExecutionLoop
from runtime.state_store import StateStore


class CausalReplayEngine:
    """
    Deterministic replay of a past causal execution.

    Parameters
    ----------
    rules_source : str
        DSL rule text that was used to build the original graph.
    action_registry : dict, optional
        Mapping of action function names to callables, identical to the
        original run's registry.  Side-effect-free stubs are acceptable
        for replay analysis.
    max_ticks : int
        Safety cap on replay iterations (default ``1000``).
    """

    def __init__(
        self,
        rules_source: str,
        action_registry: Optional[Dict[str, Callable[..., Any]]] = None,
        max_ticks: int = 1000,
    ) -> None:
        self._rules_source = rules_source
        self._action_registry: Dict[str, Callable[..., Any]] = action_registry or {}
        self._max_ticks = max_ticks

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def replay(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        event_trace: Optional[List[Dict[str, Any]]] = None,
        layer_stack: Optional[LayerStack] = None,
    ) -> ExecutionLoop:
        """
        Replay the causal run and return the completed :class:`~runtime.execution_loop.ExecutionLoop`.

        Parameters
        ----------
        initial_state : dict, optional
            Key/value snapshot of the system state at the *start* of the
            original run.  Defaults to an empty state.
        event_trace : list of dict, optional
            Ordered list of event records as produced by
            :class:`~tools.event_tracer.EventTracer`.  Each record must
            have at minimum an ``"event_type"`` key.  Defaults to empty.
        layer_stack : LayerStack, optional
            Explicit layer stack to use.  When omitted a fresh
            :class:`~reality_layers.deterministic_layer.DeterministicLayer`
            is created and pushed, guaranteeing full determinism.

        Returns
        -------
        ExecutionLoop
            The completed replay loop.  Inspect
            ``loop.graph.execution_history`` to compare with the
            original run.
        """
        # 1. Build fresh graph
        graph = self._build_graph()

        # 2. Restore initial state
        store = StateStore(dict(initial_state or {}))

        # 3. Replay events through a fresh bus
        bus = EventBus()
        self._publish_trace(bus, event_trace or [])

        # 4. Set up deterministic layer stack
        stack = layer_stack if layer_stack is not None else self._default_layer_stack()

        # 5. Run loop to completion
        loop = ExecutionLoop(
            graph,
            state_store=store,
            event_bus=bus,
            layer_stack=stack,
            max_ticks=self._max_ticks,
        )
        loop.start()
        return loop

    def replay_graph(
        self,
        graph: CausalGraph,
        initial_state: Optional[Dict[str, Any]] = None,
        event_trace: Optional[List[Dict[str, Any]]] = None,
        layer_stack: Optional[LayerStack] = None,
    ) -> ExecutionLoop:
        """
        Replay using an *externally supplied* (pre-built) graph.

        The graph is reset to PENDING before replay begins.  Use this
        overload when the graph was constructed programmatically rather
        than from a DSL string.

        Returns the completed :class:`~runtime.execution_loop.ExecutionLoop`.
        """
        graph.reset()

        store = StateStore(dict(initial_state or {}))
        bus = EventBus()
        self._publish_trace(bus, event_trace or [])
        stack = layer_stack if layer_stack is not None else self._default_layer_stack()

        loop = ExecutionLoop(
            graph,
            state_store=store,
            event_bus=bus,
            layer_stack=stack,
            max_ticks=self._max_ticks,
        )
        loop.start()
        return loop

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_graph(self) -> CausalGraph:
        from dsl.compiler import DSLCompiler
        from dsl.parser import RuleParser

        rules = RuleParser().parse(self._rules_source)
        return DSLCompiler(action_registry=self._action_registry).compile(rules)

    @staticmethod
    def _publish_trace(bus: EventBus, trace: List[Dict[str, Any]]) -> None:
        for entry in trace:
            bus.publish(Event(
                event_type=entry["event_type"],
                data=entry.get("data", {}),
                timestamp=entry.get("timestamp", 0.0),
                source=entry.get("source"),
            ))

    @staticmethod
    def _default_layer_stack() -> LayerStack:
        stack = LayerStack()
        stack.push(DeterministicLayer(start_time=0.0, time_step=1.0))
        return stack

    def __repr__(self) -> str:
        return (
            f"CausalReplayEngine("
            f"rules={len(self._rules_source.splitlines())} lines, "
            f"max_ticks={self._max_ticks})"
        )
