"""
DSL Compiler — transforms a :class:`~dsl.parser.RuleAST` into a
populated :class:`~core.causal_engine.CausalGraph`.

For each parsed rule the compiler:

1. Creates a :class:`~core.node_types.ConditionNode` from the IF clause.
2. Creates an :class:`~core.node_types.ActionNode` for the THEN clause.
3. Creates an :class:`~core.node_types.ActionNode` for every CAUSE clause.
4. Wires all nodes causally:
   - ConditionNode → THEN ActionNode
   - THEN ActionNode → CAUSE ActionNode (for each CAUSE)
5. Adds all nodes and edges to the provided (or newly created) graph.

Action callables can be injected via the *action_registry* dict, keyed
by function name.  If a function is not registered, a no-op stub is used
so the graph can still be built and inspected.

Usage::

    from dsl import RuleParser, DSLCompiler

    parser   = RuleParser()
    compiler = DSLCompiler(action_registry={
        "log_event": lambda ctx: print("LOG:", ctx),
        "reduce_process_priority": lambda ctx: ...,
    })

    rules = parser.parse('''
        IF cpu_usage > 80%
        THEN log_event("high_cpu")
        CAUSE reduce_process_priority()
    ''')
    graph = compiler.compile(rules)
"""
from __future__ import annotations

import operator as _op
from typing import Any, Callable, Dict, List, Optional

from core.causal_engine import CausalGraph
from core.node_types import ActionNode, ConditionNode
from dsl.parser import ActionAST, ConditionAST, RuleAST

# ---------------------------------------------------------------------------
# Operator map for condition evaluation
# ---------------------------------------------------------------------------

_OPERATOR_MAP: Dict[str, Callable[[Any, Any], bool]] = {
    ">":  _op.gt,
    ">=": _op.ge,
    "<":  _op.lt,
    "<=": _op.le,
    "==": _op.eq,
    "!=": _op.ne,
}


def _build_predicate(condition: ConditionAST) -> Callable[[Dict[str, Any]], bool]:
    """
    Return a callable predicate that evaluates the parsed condition
    against a live context dict.

    The context is expected to contain ``condition.metric`` as a key
    whose value is a numeric reading (0–100 for percentages, raw number
    otherwise).
    """
    compare = _OPERATOR_MAP[condition.operator]
    threshold = condition.numeric_value
    metric = condition.metric

    def predicate(ctx: Dict[str, Any]) -> bool:
        raw = ctx.get(metric)
        if raw is None:
            return False
        try:
            return compare(float(raw), threshold)
        except (TypeError, ValueError):
            return False

    return predicate


def _build_action_callable(
    action_ast: ActionAST,
    registry: Dict[str, Callable[..., Any]],
) -> Callable[[Dict[str, Any]], Any]:
    """
    Look up *action_ast.function_name* in *registry* and bind its args.

    If the function is not registered a no-op stub is returned so that
    graph construction succeeds even without a full implementation.
    """
    func = registry.get(action_ast.function_name)
    args = action_ast.args

    if func is None:
        def stub(ctx: Dict[str, Any]) -> None:  # noqa: ANN001
            pass  # no-op stub for unregistered action
        return stub

    def bound(ctx: Dict[str, Any]) -> Any:
        return func(ctx, *args)

    return bound


class DSLCompiler:
    """
    Compiles a list of :class:`~dsl.parser.RuleAST` objects into a
    :class:`~core.causal_engine.CausalGraph`.

    Parameters
    ----------
    action_registry : dict, optional
        Mapping from action function name to a Python callable with
        signature ``(context, *args) -> Any``.
    """

    def __init__(
        self,
        action_registry: Optional[Dict[str, Callable[..., Any]]] = None,
    ) -> None:
        self.action_registry: Dict[str, Callable[..., Any]] = action_registry or {}

    def compile(
        self,
        rules: List[RuleAST],
        graph: Optional[CausalGraph] = None,
    ) -> CausalGraph:
        """
        Compile *rules* into a :class:`~core.causal_engine.CausalGraph`.

        If an existing *graph* is supplied, nodes are appended to it;
        otherwise a new graph is created and returned.
        """
        g = graph if graph is not None else CausalGraph()
        for rule in rules:
            self._compile_rule(rule, g)
        return g

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compile_rule(self, rule: RuleAST, graph: CausalGraph) -> None:
        # 1. Condition node
        cond_node = ConditionNode(
            name=f"IF {rule.condition.metric} {rule.condition.operator} {rule.condition.value}",
            predicate=_build_predicate(rule.condition),
            metadata={"metric": rule.condition.metric, "operator": rule.condition.operator, "value": rule.condition.value},
        )
        graph.add_node(cond_node)

        # 2. THEN action node
        then_node = ActionNode(
            name=f"THEN {rule.then_action.function_name}",
            action=_build_action_callable(rule.then_action, self.action_registry),
            metadata={"function": rule.then_action.function_name, "args": rule.then_action.args},
        )
        graph.add_node(then_node)
        graph.add_edge(cond_node, then_node, label="triggers")

        # 3. CAUSE action nodes
        prev = then_node
        for cause_ast in rule.cause_actions:
            cause_node = ActionNode(
                name=f"CAUSE {cause_ast.function_name}",
                action=_build_action_callable(cause_ast, self.action_registry),
                metadata={"function": cause_ast.function_name, "args": cause_ast.args},
            )
            graph.add_node(cause_node)
            graph.add_edge(prev, cause_node, label="causes")
            prev = cause_node
