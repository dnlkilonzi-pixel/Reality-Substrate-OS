# Reality Substrate OS — RS-CCE

> 🧠 **Reality Substrate + Causal Computing Engine**
>
> A next-generation experimental operating system prototype where execution
> is driven by **causal graphs**, not instruction order.

---

## Overview

RS-CCE is a modular meta-runtime built around three core ideas:

1. **Causal Graphs replace linear execution** — system behaviour emerges from
   EVENT → CAUSE → EFFECT chains.
2. **Reality Layers override OS semantics** — time, memory, I/O, and
   scheduling are pluggable abstractions that stack at runtime.
3. **Rule DSL compiles to graphs** — human-readable causal rules are parsed
   and compiled into live graph structures.

---

## Quick Start

```bash
pip install pytest
python main.py          # run the full demonstration
python -m pytest tests/ # run the test suite (155 tests)
```

---

## Architecture

```
/
├── core/
│   ├── node_types.py      # EventNode, ConditionNode, ActionNode, TransformNode
│   ├── causal_engine.py   # CausalGraph — graph runtime + scheduler
│   └── event_bus.py       # EventBus — system-wide pub/sub
│
├── dsl/
│   ├── parser.py          # Rule text → AST
│   └── compiler.py        # AST → CausalGraph
│
├── reality_layers/
│   ├── base_layer.py          # Default OS semantics + LayerStack
│   ├── deterministic_layer.py # Removes all non-determinism
│   └── slow_time_layer.py     # Scales the perceived passage of time
│
├── runtime/
│   ├── execution_loop.py      # Main driver: ticks the graph continuously
│   ├── state_store.py         # Key/value store with change log + replay
│   ├── graph_monitor.py       # Live graph introspection + snapshots
│   ├── causal_replay.py       # Deterministic causal replay engine
│   └── distributed_runtime.py # VectorClock, DistributedEventLog, CausalNodeRuntime
│
├── tools/
│   ├── visualizer.py          # ASCII + DOT graph rendering
│   ├── event_tracer.py        # Records, saves, and replays event streams
│   └── proof_engine.py        # Execution proof system (NodeActivationProof, ExecutionLineage)
│
├── tests/                     # pytest test suite (273 tests)
├── main.py                    # End-to-end demonstration
└── requirements.txt
```

---

## Rule DSL

Write causal rules instead of procedural code:

```
IF cpu_usage > 80%
THEN log_event("high_cpu")
CAUSE reduce_process_priority()

IF packet_loss > 5%
THEN throttle_connection()
CAUSE log_event("packet_loss")
CAUSE reroute_traffic()
```

Self-modifying rules — inject new logic at runtime:

```
IF cpu_usage > 85%
THEN log_alert("cpu_critical")
CAUSE add_rule("IF cpu_usage > 90% THEN spawn_optimizer()")
```

Rules compile into a directed causal graph:

```
ConditionNode (cpu_usage > 80%)
    └─[triggers]→ ActionNode (log_event)
                    └─[causes]→ ActionNode (reduce_process_priority)
```

---

## Key Concepts

### Node Types

| Type | Role |
|------|------|
| `EventNode` | Input signal or metric — triggers when an event fires |
| `ConditionNode` | Logical gate — evaluates a predicate over system state |
| `ActionNode` | System effect — executes when dependencies are met |
| `TransformNode` | Data mutation — derives or aggregates upstream values |

### Execution Model

1. Build the causal graph from rules + system events.
2. Continuously evaluate graph state via `ExecutionLoop`.
3. Fire nodes when their causal dependencies are satisfied.
4. Propagate results back into the `StateStore` and the graph.

Execution is **not linear** — it is reactive and wave-based.

### Reality Layers

| Layer | Effect |
|-------|--------|
| `BaseLayer` | Real OS semantics (wall clock, actual I/O) |
| `DeterministicLayer` | Logical clock, sequential addresses, no I/O |
| `SlowTimeLayer` | Scaled time (`factor` < 1 = slower, > 1 = faster) |

Layers stack in priority order via `LayerStack`.

---

## Usage Examples

### Programmatic graph

```python
from core.causal_engine import CausalGraph
from core.node_types import ConditionNode, ActionNode

graph = CausalGraph()
cond = ConditionNode("high_cpu", lambda ctx: ctx.get("cpu_usage", 0) > 80)
act  = ActionNode("log", lambda ctx: print("CPU is high!"))
graph.add_node(cond).add_node(act)
graph.add_edge(cond, act)
graph.tick({"cpu_usage": 90})   # prints "CPU is high!"
```

### DSL compilation

```python
from dsl.parser import RuleParser
from dsl.compiler import DSLCompiler

parser   = RuleParser()
compiler = DSLCompiler(action_registry={
    "log_event": lambda ctx, *a: print(f"LOG: {a}"),
    "reduce_process_priority": lambda ctx, *a: ...,
})

rules = parser.parse("""
    IF cpu_usage > 80%
    THEN log_event("high_cpu")
    CAUSE reduce_process_priority()
""")
graph = compiler.compile(rules)
graph.tick({"cpu_usage": 90})
```

### Deterministic execution

```python
from reality_layers.base_layer import LayerStack
from reality_layers.deterministic_layer import DeterministicLayer
from runtime.execution_loop import ExecutionLoop

stack = LayerStack()
stack.push(DeterministicLayer(start_time=0.0, time_step=1.0))

loop = ExecutionLoop(graph, layer_stack=stack)
loop.start()
```

### Hot rule injection

```python
loop.inject_rule(
    "IF memory_usage > 90%\nTHEN alert_admin()",
    action_registry={"alert_admin": lambda ctx, *a: print("ALERT!")},
)
```

### Causal Replay Engine

```python
from runtime.causal_replay import CausalReplayEngine

engine = CausalReplayEngine(rules_source=my_rules, action_registry=my_registry)
replay_loop = engine.replay(
    initial_state={"cpu_usage": 90},
    event_trace=tracer.trace,  # from EventTracer
)
# replay_loop.graph.execution_history == original_loop.graph.execution_history
```

### Cross-Graph Composition

```python
from core.graph_composer import GraphBridge, GraphComposer

# Explicit bridge: output node of A triggers input node of B
bridge = GraphBridge(source_node_id=act_a.id, target_node_id=cond_b.id)
meta = GraphComposer.compose(graph_a, graph_b, bridges=[bridge])

# Sequential shorthand: all leaves of A → all roots of B
meta = GraphComposer.compose_sequential(graph_a, graph_b)
```

### Self-Modifying Rules

```python
# Add add_rule to the loop's built-in registry so injected rules can use it too
loop._builtin_registry.update(my_registry)

# The rule below emits a new rule when cpu_usage > 85%
source = """
    IF cpu_usage > 85%
    THEN log_alert("cpu_critical")
    CAUSE add_rule("IF cpu_usage > 90% THEN spawn_optimizer()")
"""
# After this rule fires, the graph grows to include spawn_optimizer
```

### Formal Semantics

```python
from core.formal_semantics import CausalSemantics, GraphDelta
from core.causal_engine import CausalEdge

# 1. State Transition: S(t+1) = F(S(t), G, E)
s_next = CausalSemantics.transition({"cpu": 90}, graph)
assert s_next["throttled"] is True

# 2. Causal Activation Predicate
satisfied = CausalSemantics.activation_satisfied(node, graph, state)

# 3. Graph Evolution: G' = G ⊕ ΔG
delta = GraphDelta(
    nodes_added=[new_node],
    edges_added=[CausalEdge(source_id=leaf.id, target_id=new_node.id)],
)
g_prime = CausalSemantics.evolve(graph, delta)  # original graph unchanged

# Helper: causal depth of a node
depth = CausalSemantics.causal_depth(node, graph)
```

### Execution Proof System

```python
from tools.proof_engine import ProofEngine

graph = CausalGraph(record_contexts=True)
# ... build graph ...
loop   = ExecutionLoop(graph, state_store=StateStore({"cpu": 90}))
engine = ProofEngine(graph)
engine.attach(loop)
loop.start()

lineage = engine.get_lineage()
print(lineage.format_lineage())          # full report
proof = lineage.why_fired(some_node.id)  # why did this node fire?
print(proof.explain())
chain = lineage.full_chain(some_node.id) # complete causal chain
adj   = lineage.lineage_graph()          # cause → [effects] adjacency dict
```

### Distributed Causal Consistency

```python
from runtime.distributed_runtime import (
    CausalNodeRuntime, ConflictPolicy, VectorClock
)

node_a = CausalNodeRuntime("A", peers=["B"])
node_b = CausalNodeRuntime("B", peers=["A"])

# A emits, B receives (causal ordering established)
ev_a = node_a.emit("cpu_spike", data={"v": 95}, state_mutations={"limit": 80})
node_b.receive(ev_a)
ev_b = node_b.emit("alert_ops")
assert ev_a.happens_before(ev_b)

# Sync + deterministic merge
merged = node_a.sync(node_b.log)
for ev in merged.causal_order():    # topologically sorted
    print(ev.source_node, ev.event_type, ev.vector_clock)

# Conflict detection + resolution
conflicts = merged.conflicts()       # concurrent writes to same state key
resolved  = node_a.log.merge(node_b.log,
    conflict_policy=ConflictPolicy.LAST_WRITER_WINS)
```

---

## Formal Mathematical Model

| Operator | Formula | Description |
|----------|---------|-------------|
| State Transition | S(t+1) = F(S(t), G, E) | Next state is deterministic given current state, graph, and events |
| Causal Activation | activate(n) ⟺ ∀p ∈ pred(n): state(p)=DONE | Node fires only when all predecessors complete |
| Graph Evolution | G' = G ⊕ ΔG | Graph grows at runtime via `add_rule` or explicit delta |
| Causal Ordering | A → B ⟺ VC(A) < VC(B) | Vector clock ordering across distributed nodes |

---

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ | Causal graph engine + rule parser |
| 2 | ✅ | Event bus + runtime loop + logging + replay |
| 3 | ✅ | Reality layers (deterministic + time scaling) |
| 4 | ✅ | **Causal Replay Engine** — deterministic time machine |
| 5 | ✅ | **Cross-Graph Composition** — modular causal microservices |
| 6 | ✅ | **Self-Modifying Rules** — adaptive kernel via `add_rule` |
| 7 | ✅ | **Formal Semantics** — S(t+1)=F(S(t),G,E), G'=G⊕ΔG |
| 8 | ✅ | **Execution Proof System** — git blame for computation causality |
| 9 | ✅ | **Distributed Causal Consistency** — vector clocks, deterministic merge |

---

## Running Tests

```bash
python -m pytest tests/ -v
```

All 273 tests cover:
- `tests/test_causal_engine.py` — graph engine and node types
- `tests/test_dsl.py` — rule parser and compiler
- `tests/test_reality_layers.py` — all reality layers
- `tests/test_runtime.py` — state store, graph monitor, execution loop, event bus
- `tests/test_tools.py` — visualizer and event tracer
- `tests/test_upgrades.py` — causal replay, cross-graph composition, self-modifying rules
- `tests/test_formal_semantics.py` — state transition, activation predicate, graph evolution
- `tests/test_proof_engine.py` — activation proofs, dependency certificates, execution lineage
- `tests/test_distributed.py` — vector clocks, event merge, conflict resolution, distributed scenarios
