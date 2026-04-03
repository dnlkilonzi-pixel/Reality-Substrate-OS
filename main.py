"""
RS-CCE: Reality Substrate + Causal Computing Engine
Main example demonstrating the full system.

This script walks through each phase described in the problem statement:

Phase 1 - Causal graph engine + basic rule parser
Phase 2 - Event bus + runtime execution loop + logging
Phase 3 - Reality layers (time scaling + deterministic mode)

Run with:
    python main.py
"""
import sys
from pathlib import Path

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from core.causal_engine import CausalGraph
from core.event_bus import Event, EventBus
from core.node_types import ActionNode, ConditionNode, EventNode, TransformNode
from dsl.compiler import DSLCompiler
from dsl.parser import RuleParser
from reality_layers.base_layer import BaseLayer, LayerStack
from reality_layers.deterministic_layer import DeterministicLayer
from reality_layers.slow_time_layer import SlowTimeLayer
from runtime.execution_loop import ExecutionLoop
from runtime.graph_monitor import GraphMonitor
from runtime.state_store import StateStore
from tools.event_tracer import EventTracer
from tools.visualizer import Visualizer


# ==========================================================================
# Helpers
# ==========================================================================

def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ==========================================================================
# Phase 1 — Causal Graph Engine + Rule DSL
# ==========================================================================

def phase1_demo() -> None:
    section("Phase 1: Causal Graph Engine + Rule DSL")

    # --- Build action registry ---
    log: list = []

    def log_event(ctx, *args):
        msg = args[0].strip('"') if args else "event"
        log.append(f"LOG: {msg}")
        print(f"  [action] log_event({msg})")

    def reduce_process_priority(ctx, *args):
        log.append("REDUCE_PRIORITY")
        print("  [action] reduce_process_priority()")

    registry = {
        "log_event": log_event,
        "reduce_process_priority": reduce_process_priority,
    }

    # --- Parse and compile DSL rules ---
    source = """
        IF cpu_usage > 80%
        THEN log_event("high_cpu")
        CAUSE reduce_process_priority()
    """

    parser = RuleParser()
    compiler = DSLCompiler(action_registry=registry)

    print("\nParsing rule:")
    print(source.strip())

    rules = parser.parse(source)
    graph = compiler.compile(rules)

    print(f"\nCompiled graph: {graph}")

    # --- Visualize (before execution) ---
    viz = Visualizer(graph)
    print("\nASCII graph (before execution):")
    print(viz.ascii())

    # --- Execute with low CPU (condition False) ---
    print("\nTick with cpu_usage=50 (condition FALSE):")
    executed = graph.tick({"cpu_usage": 50})
    print(f"  Executed nodes: {[n.name for n in executed]}")

    # Reset for next run
    graph.reset()

    # --- Execute with high CPU (condition True) ---
    print("\nTick with cpu_usage=90 (condition TRUE):")
    executed = graph.tick({"cpu_usage": 90})
    print(f"  Executed nodes: {[n.name for n in executed]}")

    # --- Visualize (after execution) ---
    print("\nASCII graph (after execution):")
    print(viz.ascii())

    # --- Graph monitor ---
    monitor = GraphMonitor(graph)
    print("\nGraph monitor summary:")
    print(monitor.summary())


# ==========================================================================
# Phase 2 — Event Bus + Runtime Execution Loop + Logging
# ==========================================================================

def phase2_demo() -> None:
    section("Phase 2: Event Bus + Runtime Execution Loop + Logging")

    # --- Multi-rule DSL source ---
    source = """
        IF cpu_usage > 80%
        THEN log_event("high_cpu")
        CAUSE reduce_process_priority()

        IF packet_loss > 5%
        THEN throttle_connection()
        CAUSE log_event("packet_loss")
        CAUSE reroute_traffic()
    """

    results: list = []

    registry = {
        "log_event":               lambda ctx, *a: results.append(("log", a)),
        "reduce_process_priority": lambda ctx, *a: results.append(("reduce_priority",)),
        "throttle_connection":     lambda ctx, *a: results.append(("throttle",)),
        "reroute_traffic":         lambda ctx, *a: results.append(("reroute",)),
    }

    parser = RuleParser()
    compiler = DSLCompiler(action_registry=registry)
    graph = compiler.compile(parser.parse(source))

    # --- Set up state, event bus, and execution loop ---
    state = StateStore({"cpu_usage": 85, "packet_loss": 8})
    bus = EventBus()
    tracer = EventTracer(bus, tag="phase2")

    loop = ExecutionLoop(graph, state_store=state, event_bus=bus, max_ticks=10)

    # Inject some events
    bus.publish(Event("system_start", {"info": "booting"}, source="system"))
    bus.publish(Event("cpu_spike", {"value": 95}, source="monitor"))

    print("\nRunning execution loop...")
    loop.start()

    print(f"\nResults after loop: {results}")
    print(f"\nEvent timeline:\n{tracer.timeline()}")

    # --- Hot-inject a new rule at runtime ---
    print("\nHot-injecting new rule: IF memory_usage > 90%")
    new_results: list = []
    loop.inject_rule(
        "IF memory_usage > 90%\nTHEN alert_admin()",
        action_registry={"alert_admin": lambda ctx, *a: new_results.append("ALERT!")},
    )
    state.set("memory_usage", 95)
    loop.tick_once()
    print(f"Hot-injected rule results: {new_results}")

    # --- Replay ---
    print("\nReplaying trace on fresh bus:")
    replay_bus = EventBus()
    replay_received = []
    replay_bus.subscribe("cpu_spike", lambda e: replay_received.append(e))
    tracer.replay(replay_bus)
    print(f"  Replayed cpu_spike events: {len(replay_received)}")


# ==========================================================================
# Phase 3 — Reality Layers
# ==========================================================================

def phase3_demo() -> None:
    section("Phase 3: Reality Layers")

    # --- DeterministicLayer ---
    print("\n[DeterministicLayer] Removing all non-determinism:")
    det_layer = DeterministicLayer(start_time=0.0, time_step=1.0)
    times = [det_layer.time_now() for _ in range(5)]
    print(f"  Logical time sequence: {times}")
    alloc1 = det_layer.memory_alloc(64)
    alloc2 = det_layer.memory_alloc(32)
    print(f"  Alloc 1: address={alloc1['address']:#x}, size={alloc1['size']}")
    print(f"  Alloc 2: address={alloc2['address']:#x}, size={alloc2['size']}")
    print(f"  process_schedule(42, 99): {det_layer.process_schedule(42, 99)}")

    # --- SlowTimeLayer ---
    import time as _time
    print("\n[SlowTimeLayer] Scaling time by 0.5 (half-speed):")
    epoch = _time.time() - 100.0  # pretend we started 100s ago
    slow_layer = SlowTimeLayer(factor=0.5, epoch=epoch)
    scaled_t = slow_layer.time_now()
    print(f"  Epoch                   : {epoch:.3f}")
    print(f"  Expected scaled time    : ~{epoch + 50.0:.3f}")
    print(f"  Actual scaled time_now(): {scaled_t:.3f}")

    # --- LayerStack composition ---
    print("\n[LayerStack] Composing BaseLayer → DeterministicLayer:")
    stack = LayerStack()
    stack.push(BaseLayer())
    det2 = DeterministicLayer(start_time=1000.0, time_step=5.0)
    stack.push(det2)
    print(f"  Stack: {stack}")
    print(f"  time_now() via stack: {stack.time_now()}")
    print(f"  time_now() via stack: {stack.time_now()}")

    # --- Execute causal graph under DeterministicLayer ---
    print("\nRunning causal graph with DeterministicLayer in ExecutionLoop:")
    graph = CausalGraph()
    time_readings: list = []
    graph.add_node(ActionNode(
        "record_time",
        lambda ctx: time_readings.append(ctx.get("__time__")),
    ))

    det_stack = LayerStack()
    det_stack.push(DeterministicLayer(start_time=500.0, time_step=10.0))

    loop = ExecutionLoop(graph, layer_stack=det_stack, max_ticks=3)
    loop.tick_once()
    loop.tick_once()
    print(f"  Recorded __time__ values: {time_readings}")


# ==========================================================================
# End-to-end demo
# ==========================================================================

def end_to_end_demo() -> None:
    section("End-to-End: CPU Overload Response System")

    # The canonical example from the problem statement:
    #   IF cpu_usage > 80%
    #   THEN log_event("high_cpu")
    #   CAUSE reduce_process_priority()

    actions_taken: list = []

    def _log(ctx, *args):
        msg = args[0].strip('"') if args else "event"
        actions_taken.append(f"logged:{msg}")
        print(f"    >> log_event({msg})")

    def _reduce(ctx, *args):
        actions_taken.append("priority_reduced")
        print("    >> reduce_process_priority()")

    source = """
        IF cpu_usage > 80%
        THEN log_event("high_cpu")
        CAUSE reduce_process_priority()
    """

    parser = RuleParser()
    compiler = DSLCompiler(action_registry={"log_event": _log, "reduce_process_priority": _reduce})
    graph = compiler.compile(parser.parse(source))

    state = StateStore()
    bus = EventBus()
    tracer = EventTracer(bus, tag="e2e")
    stack = LayerStack()
    stack.push(DeterministicLayer(start_time=0.0))

    loop = ExecutionLoop(graph, state_store=state, event_bus=bus, layer_stack=stack, max_ticks=20)
    monitor = GraphMonitor(graph)
    viz = Visualizer(graph)

    print("\n  Step 1: CPU usage below threshold (70%)")
    state.set("cpu_usage", 70)
    loop.tick_once()
    print(f"  Actions taken: {actions_taken}")

    graph.reset()
    actions_taken.clear()

    print("\n  Step 2: CPU usage exceeds threshold (90%)")
    state.set("cpu_usage", 90)
    bus.publish(Event("cpu_high", {"value": 90}, source="monitor"))
    loop.tick_once()
    print(f"  Actions taken: {actions_taken}")

    print("\n  Graph state after execution:")
    print(viz.ascii())

    snap = monitor.snapshot()
    print(f"\n  Snapshot stats: {snap['stats']}")
    print(f"\n  Event timeline:\n{tracer.timeline()}")


# ==========================================================================
# Entry point
# ==========================================================================

if __name__ == "__main__":
    print("\n🧠 Reality Substrate + Causal Computing Engine (RS-CCE)")
    print("=" * 60)

    phase1_demo()
    phase2_demo()
    phase3_demo()
    end_to_end_demo()

    print("\n✅ All demonstrations complete.")
