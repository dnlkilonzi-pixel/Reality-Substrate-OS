# RS-CCE Computational Model
## The Locked Formal Definition — Source of Truth

**Daniel Kimeu** — Reality Substrate Project, 2026  
Version: 1.0 (Frozen)

---

> This document is the **single authoritative definition** of the RS-CCE
> computational model. Every implementation, test, paper section, and demo
> script is derived from this specification.  
> Nothing in the codebase may contradict these definitions.

---

## Part I — Primitive Domains

| Symbol | Type | Description |
|--------|------|-------------|
| `K` | `String` | A state key (e.g. `"cpu_usage"`) |
| `V` | `Any` | A state value (number, boolean, string, …) |
| `S` | `K → V` | **System State** — a partial map from keys to values |
| `n` | `Node` | A **causal node** (see §2) |
| `N` | `{Node}` | The set of all nodes in a graph |
| `e_G` | `(id, id, label)` | A directed **graph edge** from source to target |
| `G` | `(N, E_G)` | **Causal Graph** — a directed graph over `N` with edges `E_G` |
| `ev` | `Event` | A **system event** (see §3) |
| `E` | `[Event]` | An ordered sequence of events arriving in one tick |
| `t` | `ℕ` | A discrete **tick** counter |

---

## Part II — System State S

**S** is a finite partial function `S : K → V`.

```
S = { k₁ ↦ v₁, k₂ ↦ v₂, …, kₙ ↦ vₙ }
```

Properties:
- **Finite** — only finitely many keys are defined at any tick.
- **Snapshot** — S represents the state at a single logical time point.
- **Immutable per tick** — the transition function `F` produces a new S'; it
  never mutates the existing S.

The **initial state** S(0) is the user-supplied key/value dict passed at
construction time of the `StateStore`.

---

## Part III — Causal Graph G

**G = (N, E_G)** is a directed graph where:

- Each **vertex** `n ∈ N` is a causal node (§4 below).
- Each **directed edge** `(u, v) ∈ E_G` encodes a single causal dependency:
  > *"v cannot fire until u has reached state DONE."*

### Predecessor and Successor notation

```
pred(n) = { u ∈ N | (u, n) ∈ E_G }
succ(n) = { v ∈ N | (n, v) ∈ E_G }
```

**Root nodes** — nodes with `pred(n) = ∅` — are eligible to fire at t=0
without preconditions.

### Well-formedness

G is **well-formed** iff it is a DAG (directed acyclic graph). Cycles would
create unsatisfiable activation dependencies and halt execution.

---

## Part IV — Node Types N

Every node `n ∈ N` carries:

| Field | Type | Description |
|-------|------|-------------|
| `n.id` | UUID | Globally unique identifier |
| `n.name` | String | Human-readable label |
| `n.type` | NodeType | One of: EVENT, CONDITION, ACTION, TRANSFORM |
| `n.state` | NodeState | One of: PENDING, READY, EXECUTING, DONE, FAILED |
| `n.fn` | `S → V` | Optional payload function |
| `n.result` | V? | Result of `n.fn(S)` after firing |

### Node Semantics

**EventNode**  
Fires when a matching external event `ev` arrives with `ev.event_type = n.event_type`.
Its result is the event payload dict.

**ConditionNode**  
Fires when `pred(n)` are all DONE **and** `n.fn(S) = True`.  
If `n.fn(S) = False`, the node returns to PENDING, blocking all of `succ(n)`.

**ActionNode**  
Fires when `pred(n)` are all DONE.  
Its result (if a dict) is merged into S to produce S(t+1).

**TransformNode**  
Semantically identical to ActionNode, but its result is treated as a derived
value (not a state mutation) by convention.

---

## Part V — Event Space E

A **system event** `ev` is a record:

```
ev = { event_type     : String
     , data           : S          — partial state payload
     , source         : String?    — originating component (optional)
     , timestamp      : ℝ         — wall-clock (diagnostic only; NOT causal)
     }
```

The ordered sequence `E = ⟨ev₁, ev₂, …, evₖ⟩` represents all events that
arrive during one tick.

Events are:
- **External inputs** to EventNodes.
- **Not causal** in themselves — causality lives in G.
- **Totally ordered within a tick** by arrival position.

---

## Part VI — The Three Core Operators

### Operator 1 — Causal Activation Predicate

```
activate(n, G, S) ⟺
    (∀ u ∈ pred(n) : u.state = DONE)
    ∧ (n.type ≠ CONDITION ∨ n.fn(S) = True)
    ∧ (n.type ≠ EVENT     ∨ n.is_triggered = True)
```

**Intuition:** A node fires only when every upstream cause is complete AND
its own guard condition (if any) is satisfied.

**Corollary:** Root nodes (`pred(n) = ∅`) with no conditional guard satisfy
`activate(n, G, S)` for any S.

The **ready set** at tick t:

```
R(G, S) = { n ∈ N | n.state ∈ {PENDING, READY} ∧ activate(n, G, S) }
```

---

### Operator 2 — State Transition Function

```
S(t+1) = F(S(t), G, E(t))
```

Formally, let `exec(n, S)` be the result of executing node n in state S:

```
exec(n, S) = n.fn(S)      if n.type ∈ {ACTION, TRANSFORM, CONDITION}
           = n.payload    if n.type = EVENT
```

The transition:

```
F(S, G, E) = S ∪ { k ↦ v | n ∈ fired(G, S, E), (k,v) ∈ exec(n,S) }
```

where `fired(G, S, E)` is the transitive closure of `R(G, S)` after applying
events `E` to their EventNodes, executed in topological order until quiescence.

**Execution order:** Nodes in `R(G, S)` are fired in topological order (wave
by wave) — all root nodes first, then nodes whose predecessors are now DONE,
and so on.

---

### Operator 3 — Graph Evolution

```
G' = G ⊕ ΔG
```

A **GraphDelta** ΔG is:

```
ΔG = { nodes_added   : [Node]
     , edges_added   : [E_G]
     , nodes_removed : [id]
     , edges_removed : [(id, id)]
     }
```

Application:

```
G'.N = (G.N \ nodes_removed) ∪ nodes_added
G'.E = (G.E \ edges_removed
            \ {(u,v) | u ∈ nodes_removed ∨ v ∈ nodes_removed})
           ∪ edges_added
```

**Non-destructiveness:** `⊕` returns a new graph; G is never modified.

**Self-modifying recurrence:** When nodes emit ΔG at tick t (via `add_rule`),
the graph updates after the tick completes:

```
S(t+1) = F(S(t), G(t), E(t))
G(t+1) = G(t) ⊕ ΔG(t)
```

---

## Part VII — The Four Invariants

These are **non-negotiable guarantees**. Any implementation that violates
them is incorrect.

---

### Invariant I — Causal Consistency

> **Every state mutation in S(t+1) is traceable to a node that fired in G at
> tick t.**

Formally:

```
∀ (k, v) ∈ S(t+1) \ S(t) :
    ∃ n ∈ fired(G, S(t), E(t)) such that (k, v) ∈ exec(n, S(t))
```

No value can appear in the state unless a causal node wrote it. There is no
hidden side-channel, no ambient mutation, no global variable.

**Violation check:** Verify that every key in `S(t+1)` that differs from
`S(t)` has a corresponding `NodeActivationProof` in the lineage.

---

### Invariant II — Deterministic Replay

> **Given the same initial state S(0), the same graph G(0), and the same event
> sequence ⟨E(0), E(1), …, E(T)⟩, the execution always produces the same
> state sequence ⟨S(0), S(1), …, S(T+1)⟩.**

```
∀ S(0), G(0), ⟨E(t)⟩ :
    run₁(S(0), G(0), ⟨E(t)⟩).history = run₂(S(0), G(0), ⟨E(t)⟩).history
```

This follows from the fact that:
1. `activate(n, G, S)` is a pure function of its inputs.
2. `exec(n, S)` is a pure function of n and S.
3. Topological ordering is deterministic (ties broken by insertion order).

**Violation check:** Run the `CausalReplayEngine` on any recorded trace.
If `replay_graph()` produces a different `execution_history`, Invariant II
is violated.

---

### Invariant III — Graph Monotonicity (Additive-Default)

> **The default operational mode is monotone: nodes and edges are only added,
> never removed. The graph's causal memory grows; it does not forget.**

```
∀ t : G(t).N ⊆ G(t+1).N  ∧  G(t).E ⊆ G(t+1).E
    (when only nodes_added / edges_added are used in ΔG)
```

**Non-monotone evolution is explicitly allowed** when `nodes_removed` or
`edges_removed` are set in ΔG — but must be done intentionally.
Non-monotone changes are logged and visible in the `ExecutionLineage`.

**Violation check:** Inspect `GraphDelta` objects. Any delta with non-empty
`nodes_removed` or `edges_removed` is a deliberate non-monotone step and
must be auditable.

---

### Invariant IV — Proof Completeness

> **For every node that fires, a `NodeActivationProof` exists with a complete
> cause chain back to a root node.**

```
∀ n ∈ fired(G, S, E) :
    ∃ proof ∈ Λ.Proofs :
        proof.node_id = n.id
        ∧ proof.cause_chain[0] ∈ root_nodes(G)
        ∧ proof.cause_chain[-1] = n.id
        ∧ ∀ i : (proof.cause_chain[i], proof.cause_chain[i+1]) ∈ G.E
```

No node fires "out of thin air". Every firing is causally justified by a
chain of proofs from an input boundary (root EventNode or root ConditionNode)
down through the graph to the firing node.

**Violation check:** Call `lineage.why_fired(n.id)` for every fired node. If
any proof has `cause_chain = []` on a non-root node, Invariant IV is violated.

---

## Part VIII — Distributed Extension

When multiple `CausalNodeRuntime` instances compose a distributed RS-CCE system,
the model extends as follows:

### Vector Clock Ordering

Each runtime `r_i` maintains a vector clock `VC_i : r_j → ℕ`.

```
tick(VC_i)        : VC_i[i] ← VC_i[i] + 1          (on emit)
update(VC_i, VC') : VC_i[j] ← max(VC_i[j], VC'[j])  (on receive)
```

**Happens-before:**

```
ev_a → ev_b  ⟺  ∀k : VC(ev_a)[k] ≤ VC(ev_b)[k]
                 ∧ ∃k : VC(ev_a)[k] < VC(ev_b)[k]
```

### Distributed Invariant — Causal Convergence

> **Any two distributed nodes that receive the same set of events converge to
> the same causal order, regardless of the order in which events arrive.**

```
merge(L_a, L_b).causal_order() = merge(L_b, L_a).causal_order()
```

This follows from merge commutativity (Theorem 2 in `PAPER.md`).

---

## Part IX — Implementation Mapping

| Formal Symbol | Python Class / Method | File |
|---------------|----------------------|------|
| `S` | `StateStore` / `dict` | `runtime/state_store.py` |
| `G` | `CausalGraph` | `core/causal_engine.py` |
| `E` | `EventBus` event queue | `core/event_bus.py` |
| `F(S, G, E)` | `CausalSemantics.transition()` | `core/formal_semantics.py` |
| `activate(n, G, S)` | `CausalSemantics.activation_satisfied()` | `core/formal_semantics.py` |
| `G ⊕ ΔG` | `CausalSemantics.evolve()` | `core/formal_semantics.py` |
| `ΔG` | `GraphDelta` | `core/formal_semantics.py` |
| `R(G, S)` | `CausalSemantics.ready_set()` | `core/formal_semantics.py` |
| `depth(n, G)` | `CausalSemantics.causal_depth()` | `core/formal_semantics.py` |
| Invariant I | `ExecutionLineage` / `ProofEngine` | `tools/proof_engine.py` |
| Invariant II | `CausalReplayEngine.replay_graph()` | `runtime/causal_replay.py` |
| Invariant III | `GraphDelta` audit log | `core/formal_semantics.py` |
| Invariant IV | `lineage.why_fired()` | `tools/proof_engine.py` |
| `VC_i` | `VectorClock` | `runtime/distributed_runtime.py` |
| `→` (happens-before) | `DistributedCausalEvent.happens_before()` | `runtime/distributed_runtime.py` |
| Causal Convergence | `DistributedEventLog.merge()` | `runtime/distributed_runtime.py` |

---

## Part X — Falsifiability

The RS-CCE model makes **testable predictions**. It is falsified if any of the
following tests fail:

| Test | Falsifies |
|------|-----------|
| `test_formal_semantics.py::test_transition_determinism` | Invariant II |
| `test_formal_semantics.py::test_evolve_non_destructive` | `G ⊕ ΔG` definition |
| `test_proof_engine.py::test_cause_chain_to_root` | Invariant IV |
| `test_distributed.py::test_merge_commutativity` | Causal Convergence |
| `test_distributed.py::test_merge_idempotency` | Merge correctness |
| `test_upgrades.py::test_causal_replay_deterministic` | Invariant II |

Run all 273 tests with `python -m pytest tests/ -v` to verify the model is
intact.

---

*Document owner: Daniel Kimeu — Reality Substrate Project, 2026*  
*This is the source of truth. When in doubt, consult this document first.*
