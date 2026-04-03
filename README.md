<div align="center">

```
██████╗ ███████╗      ██████╗ ██████╗███████╗
██╔══██╗██╔════╝     ██╔════╝██╔════╝██╔════╝
██████╔╝███████╗     ██║     ██║     █████╗
██╔══██╗╚════██║     ██║     ██║     ██╔══╝
██║  ██║███████║     ╚██████╗╚██████╗███████╗
╚═╝  ╚═╝╚══════╝      ╚═════╝ ╚═════╝╚══════╝
Reality Substrate + Causal Computing Engine
```

**Computation driven by causality, not time.**

[![Tests](https://img.shields.io/badge/tests-273%20passing-brightgreen)](#running-tests)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue)](#quick-start)
[![Research](https://img.shields.io/badge/paper-PAPER.md-purple)](PAPER.md)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](#)

*Built by [Daniel Kimeu](https://github.com/dnlkilonzi-pixel)*

</div>

---

## The Big Idea

> **What if the operating system asked "what caused this?" instead of "what's next?"**

Every OS you've ever used schedules computation by *time*: instruction 1,
then 2, then 3. Concurrency is a patch bolted on after the fact — threads,
locks, semaphores. Hard to reason about. Impossible to prove. Non-deterministic
by default.

**RS-CCE flips this upside down.**

Execution is a directed acyclic graph of cause-and-effect relationships.
A node doesn't wait for its turn. It waits for its *causes*.
When every upstream cause is resolved, the node fires. Automatically.
Deterministically. Provably.

```
Traditional OS:            RS-CCE:

  t=0 → instruction 1        cpu_high ──triggers──► throttle_cpu
  t=1 → instruction 2                                     │
  t=2 → instruction 3                               causes │
  t=3 → ...                                               ▼
                                                    log_alert("critical")
  Why did X happen? ¯\_(ツ)_/¯    Why did log fire? PROOF: cpu_high→throttle→log
```

---

## What Makes This Different

| Conventional Runtime | RS-CCE |
|----------------------|--------|
| Time-ordered execution | Causality-ordered execution |
| Non-deterministic concurrency | Structurally deterministic |
| "What ran?" | "Why did it run?" |
| Graphs are data | **Graphs are the program** |
| Static code | Self-modifying causal rules |
| Single machine | Distributed causal consistency |
| No formal model | **Formally specified** ([PAPER.md](PAPER.md)) |

---

## Quick Start

```bash
git clone https://github.com/dnlkilonzi-pixel/Reality-Substrate-OS
cd Reality-Substrate-OS
pip install pytest
python main.py             # full demonstration of all 9 capabilities
python -m pytest tests/ -v # 273 tests, all passing
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         RS-CCE Runtime                          │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────────┐   │
│  │   DSL Layer  │    │  Core Engine │    │  Reality Layers │   │
│  │              │    │              │    │                 │   │
│  │ IF cpu > 80% │───►│ CausalGraph  │◄───│ DeterministicL  │   │
│  │ THEN throttle│    │ ┌──────────┐ │    │ SlowTimeLayer   │   │
│  │ CAUSE log()  │    │ │  nodes   │ │    │ BaseLayer       │   │
│  │              │    │ │  edges   │ │    └─────────────────┘   │
│  └──────────────┘    │ │  history │ │                          │
│                      │ └──────────┘ │    ┌─────────────────┐   │
│  ┌──────────────┐    │              │    │  Formal Layer   │   │
│  │  Event Bus   │───►│ ExecutionLoop│◄───│ CausalSemantics │   │
│  │  pub / sub   │    │  tick engine │    │ S(t+1)=F(S,G,E) │   │
│  └──────────────┘    └──────┬───────┘    │ G' = G ⊕ ΔG     │   │
│                             │            └─────────────────┘   │
│  ┌──────────────┐           │                                  │
│  │  StateStore  │◄──────────┘    ┌─────────────────────────┐   │
│  │  changelog   │                │  Proof + Distributed    │   │
│  │  replay      │                │  ProofEngine → Lineage  │   │
│  └──────────────┘                │  VectorClock → Merge    │   │
│                                  └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

```
core/
├── node_types.py          EventNode, ConditionNode, ActionNode, TransformNode
├── causal_engine.py       CausalGraph — graph runtime + wave scheduler
├── event_bus.py           System-wide pub/sub
├── graph_composer.py      Cross-graph composition (A ∘ B meta-graphs)
└── formal_semantics.py    S(t+1)=F(S,G,E)  activate(n)  G'=G⊕ΔG

dsl/
├── parser.py              Rule text → AST
└── compiler.py            AST → live CausalGraph

runtime/
├── execution_loop.py      Main tick driver + hot rule injection
├── state_store.py         Key/value store with changelog + replay
├── graph_monitor.py       Live introspection + snapshots
├── causal_replay.py       Deterministic replay engine
└── distributed_runtime.py VectorClock, DistributedEventLog, CausalNodeRuntime

tools/
├── visualizer.py          ASCII + DOT graph rendering
├── event_tracer.py        Records, saves, replays event streams
└── proof_engine.py        NodeActivationProof, ExecutionLineage

reality_layers/
├── base_layer.py          Real OS semantics
├── deterministic_layer.py Logical clock, no I/O
└── slow_time_layer.py     Time scaling (slow motion or fast forward)
```

---

## The Causal DSL

Instead of writing code, write **causal rules**. The compiler turns them into
a live graph.

```
IF cpu_usage > 80%
THEN log_event("high_cpu")
CAUSE reduce_process_priority()

IF packet_loss > 5%
THEN throttle_connection()
CAUSE log_event("packet_loss")
CAUSE reroute_traffic()
```

This compiles into:

```
ConditionNode [cpu_usage > 80%]
    └──[triggers]──► ActionNode [log_event]
                          └──[causes]──► ActionNode [reduce_process_priority]

ConditionNode [packet_loss > 5%]
    └──[triggers]──► ActionNode [throttle_connection]
    └──[triggers]──► ActionNode [log_event]
    └──[triggers]──► ActionNode [reroute_traffic]
```

**Self-modifying rules** — inject new logic at runtime:

```
IF cpu_usage > 85%
THEN log_alert("cpu_critical")
CAUSE add_rule("IF cpu_usage > 90% THEN spawn_optimizer()")
```

After this rule fires, the graph *grows*. The system adapts itself.

---

## How Execution Works

```
Tick N begins
│
├─ 1. Drain events from Reality Layer → EventBus
│
├─ 2. Trigger EventNodes whose event_type matches
│
├─ 3. Build context snapshot from StateStore
│
├─ 4. Compute Ready Set: R(G,S) = { n | activate(n,G,S) = True }
│        activate(n) ⟺ all predecessors DONE
│                      ∧ (if ConditionNode) predicate(S) = True
│                      ∧ (if EventNode) is_triggered = True
│
├─ 5. Fire nodes in topological order (wave by wave until quiescent)
│
├─ 6. Merge action results back into StateStore → S(t+1) = F(S(t), G, E)
│
├─ 7. Apply any ΔG emitted by self-modifying rules → G(t+1) = G(t) ⊕ ΔG(t)
│
└─ Tick N complete
```

---

## Feature Walkthrough

### 1 — Basic Causal Graph

```python
from core.causal_engine import CausalGraph
from core.node_types import ConditionNode, ActionNode

graph = CausalGraph()
cond  = ConditionNode("cpu_high", lambda ctx: ctx.get("cpu_usage", 0) > 80)
act   = ActionNode("throttle",    lambda ctx: {"throttled": True})

graph.add_node(cond).add_node(act)
graph.add_edge(cond, act, label="triggers")

result = graph.tick({"cpu_usage": 90})
# throttle fires because cpu_high fired first
```

### 2 — DSL Compilation

```python
from dsl.parser import RuleParser
from dsl.compiler import DSLCompiler

graph = DSLCompiler(action_registry={
    "log_event":               lambda ctx, *a: print(f"LOG: {a}"),
    "reduce_process_priority": lambda ctx, *a: None,
}).compile(RuleParser().parse("""
    IF cpu_usage > 80%
    THEN log_event("high_cpu")
    CAUSE reduce_process_priority()
"""))

graph.tick({"cpu_usage": 90})   # LOG: ('high_cpu',)
```

### 3 — Deterministic Replay

```python
from runtime.causal_replay import CausalReplayEngine

engine = CausalReplayEngine(rules_source=my_rules, action_registry=my_registry)

loop1 = engine.replay(initial_state={"cpu_usage": 90})
loop2 = engine.replay(initial_state={"cpu_usage": 90})

assert loop1.graph.execution_history == loop2.graph.execution_history
# Same inputs → identical execution history. Every time.
```

### 4 — Reality Layers

```python
from reality_layers.deterministic_layer import DeterministicLayer
from reality_layers.base_layer import LayerStack
from runtime.execution_loop import ExecutionLoop

stack = LayerStack()
stack.push(DeterministicLayer(start_time=0.0, time_step=1.0))
# time is now logical (0, 1, 2, …), not wall-clock
# memory addresses are sequential
# no real I/O

loop = ExecutionLoop(graph, layer_stack=stack)
loop.start()
```

### 5 — Cross-Graph Composition (A ∘ B)

```python
from core.graph_composer import GraphComposer, GraphBridge

# Explicit bridge: output of graph_a triggers input of graph_b
bridge = GraphBridge(source_node_id=act_a.id, target_node_id=cond_b.id)
meta   = GraphComposer.compose(graph_a, graph_b, bridges=[bridge])

# Automatic sequential composition: all leaves of A → all roots of B
meta   = GraphComposer.compose_sequential(graph_a, graph_b)

meta.tick(context)   # graph_b executes only after graph_a completes
```

### 6 — Self-Modifying Rules

```python
# The initial rule emits a new rule when CPU is critical
loop.inject_rule("""
    IF cpu_usage > 85%
    THEN log_alert("cpu_critical")
    CAUSE add_rule("IF cpu_usage > 90% THEN spawn_optimizer()")
""")

loop.state.set("cpu_usage", 87)
loop.tick_once()
# graph now contains a new branch: IF cpu > 90% → spawn_optimizer

loop.state.set("cpu_usage", 95)
loop.tick_once()
# spawn_optimizer fires
```

### 7 — Formal Semantics

```python
from core.formal_semantics import CausalSemantics, GraphDelta
from core.causal_engine import CausalEdge

# ① S(t+1) = F(S(t), G, E)
s_next = CausalSemantics.transition({"cpu": 90}, graph)
# original state is NEVER modified — pure function

# ② activate(n) ⟺ dependency_satisfied(n, G, S)
ok = CausalSemantics.activation_satisfied(node, graph, state)

# ③ G' = G ⊕ ΔG
new_node = ActionNode("extended", lambda ctx: None)
delta    = GraphDelta(
    nodes_added=[new_node],
    edges_added=[CausalEdge(source_id=leaf.id, target_id=new_node.id)],
)
g_prime  = CausalSemantics.evolve(graph, delta)  # original graph unchanged

# causal depth — how many causes deep is this node?
depth = CausalSemantics.causal_depth(node, graph)
```

### 8 — Execution Proof System

> *"Git blame, but for computation causality."*

```python
from tools.proof_engine import ProofEngine

graph  = CausalGraph(record_contexts=True)
loop   = ExecutionLoop(graph, state_store=StateStore({"cpu": 90}))
engine = ProofEngine(graph)
engine.attach(loop)      # auto-records on every tick
loop.start()

lineage = engine.get_lineage()
print(lineage.format_lineage())
```

```
Execution Lineage Report
============================================================
Node 'IF cpu > 80%' (ConditionNode) fired at tick 1
  Caused by  : <root — no predecessors>
  Context    : {'cpu': 90}
  Result     : True

Node 'THEN throttle_cpu' (ActionNode) fired at tick 1
  Caused by  : ['IF cpu > 80%']
  Context    : {<cond_id>: True}
  Causal chain: IF cpu > 80% → THEN throttle_cpu
  ← 'IF cpu > 80%' (tick 1) --[triggers]--> 'THEN throttle_cpu' (tick 1)

Node 'CAUSE log_alert' (ActionNode) fired at tick 1
  Caused by  : ['THEN throttle_cpu']
  Causal chain: IF cpu > 80% → THEN throttle_cpu → CAUSE log_alert
  ← 'THEN throttle_cpu' (tick 1) --[causes]--> 'CAUSE log_alert' (tick 1)
```

Every firing is machine-verifiable. Every cause chain is traceable to a root.

### 9 — Distributed Causal Consistency

> *"Distributed reality engine."*

```
  ┌─────────────────┐                  ┌─────────────────┐
  │   Edge Server   │                  │   Cloud Node    │
  │                 │                  │                 │
  │  VectorClock A  │                  │  VectorClock B  │
  │  {A:1, B:0}     │──── emit ──────► │                 │
  │                 │   cpu_spike      │  receives ev_a  │
  │                 │   VC={A:1,B:0}   │  updates clock  │
  │                 │                  │  {A:1, B:0}     │
  │                 │                  │       │         │
  │                 │                  │   emit alert    │
  │                 │                  │  VC={A:1, B:1}  │
  │                 │                  │                 │
  │  ev_a → ev_b    │  happens-before  │  ev_a → ev_b    │
  └─────────────────┘  guaranteed ✓    └─────────────────┘
```

```python
from runtime.distributed_runtime import CausalNodeRuntime, ConflictPolicy

edge  = CausalNodeRuntime("edge",  peers=["cloud"])
cloud = CausalNodeRuntime("cloud", peers=["edge"])

ev1 = edge.emit("cpu_spike", data={"value": 95}, state_mutations={"limit": 80})
cloud.receive(ev1)
ev2 = cloud.emit("alert_ops")

assert ev1.happens_before(ev2)   # formally guaranteed by vector clocks

# Deterministic merge: same result regardless of argument order
merged = edge.sync(cloud.log)
assert (
    [e.event_id for e in edge.log.merge(cloud.log).causal_order()] ==
    [e.event_id for e in cloud.log.merge(edge.log).causal_order()]
)

# Conflict detection + resolution
for ev_a, ev_b in merged.conflicts():
    print(f"Conflict: {ev_a.source_node} vs {ev_b.source_node}")

resolved = edge.log.merge(cloud.log, conflict_policy=ConflictPolicy.LAST_WRITER_WINS)
```

---

## Formal Mathematical Model

RS-CCE is **formally specified**. Every operator has a mathematical definition
and a corresponding Python implementation.

| Operator | Formula | Implemented in |
|----------|---------|----------------|
| State Transition | `S(t+1) = F(S(t), G, E)` | `CausalSemantics.transition()` |
| Causal Activation | `activate(n) ⟺ ∀p∈pred(n): state(p)=DONE` | `CausalSemantics.activation_satisfied()` |
| Graph Evolution | `G' = G ⊕ ΔG` | `CausalSemantics.evolve()` |
| Graph Tick | `G(t+1) = G(t) ⊕ ΔG(t)` | `ExecutionLoop._do_tick()` |
| Causal Ordering | `A → B ⟺ VC(A) < VC(B)` | `VectorClock.happens_before()` |
| Merge Commutativity | `merge(L_a, L_b) = merge(L_b, L_a)` | `DistributedEventLog.merge()` |

Read the full formal treatment in **[PAPER.md](PAPER.md)** — including proofs
of Determinism, Merge Commutativity, and Merge Idempotency.

---

## Development Phases

```
Phase 1  ✅  Causal graph engine + rule parser
Phase 2  ✅  Event bus + runtime loop + logging
Phase 3  ✅  Reality layers (deterministic + time scaling)
Phase 4  ✅  Causal Replay Engine — deterministic time machine
Phase 5  ✅  Cross-Graph Composition — A ∘ B meta-graphs
Phase 6  ✅  Self-Modifying Rules — adaptive kernel via add_rule
Phase 7  ✅  Formal Semantics — S(t+1)=F(S,G,E), G'=G⊕ΔG
Phase 8  ✅  Execution Proof System — git blame for causality
Phase 9  ✅  Distributed Causal Consistency — vector clocks + merge
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

```
tests/test_causal_engine.py      — graph engine, node types, scheduling
tests/test_dsl.py                — rule parser and compiler
tests/test_reality_layers.py     — all reality layers
tests/test_runtime.py            — state store, monitor, execution loop, event bus
tests/test_tools.py              — visualizer and event tracer
tests/test_upgrades.py           — replay, composition, self-modifying rules
tests/test_formal_semantics.py   — S(t+1)=F(S,G,E), activation, G'=G⊕ΔG
tests/test_proof_engine.py       — proofs, certificates, lineage
tests/test_distributed.py        — vector clocks, merge, conflict resolution

273 passed in 0.xx s ✅
```

---

## The Paper

This project is accompanied by a formal academic paper:

> **[RS-CCE: A Formal Model for Causal, Self-Evolving Distributed Computation](PAPER.md)**
>
> *Daniel Kimeu — Reality Substrate Project, 2026*
>
> Sections: Abstract · System Model · Transition Semantics ·
> Distributed Consistency · Proof System · Evaluation · Related Work

---

<div align="center">

*Conceived, designed, and built by [Daniel Kimeu](https://github.com/dnlkilonzi-pixel)*

*"Without formal semantics it stays engineering. With them it becomes research."*

</div>

