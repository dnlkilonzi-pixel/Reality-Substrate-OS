"""
Tests for the Rule DSL parser and compiler.
"""
import pytest

from dsl.parser import (
    ActionAST,
    ConditionAST,
    ParseError,
    RuleAST,
    RuleParser,
)
from dsl.compiler import DSLCompiler
from core.causal_engine import CausalGraph
from core.node_types import ActionNode, ConditionNode, NodeState


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestRuleParser:
    def setup_method(self):
        self.parser = RuleParser()

    # --- Basic parsing ---

    def test_parse_simple_rule(self):
        rules = self.parser.parse("""
            IF cpu_usage > 80%
            THEN log_event("high_cpu")
        """)
        assert len(rules) == 1
        rule = rules[0]
        assert isinstance(rule, RuleAST)
        assert rule.condition.metric == "cpu_usage"
        assert rule.condition.operator == ">"
        assert rule.condition.value == "80%"
        assert rule.condition.numeric_value == 80.0
        assert rule.condition.is_percentage is True
        assert rule.then_action.function_name == "log_event"
        assert rule.then_action.role == "THEN"
        assert rule.cause_actions == []

    def test_parse_rule_with_causes(self):
        rules = self.parser.parse("""
            IF packet_loss > 5%
            THEN throttle_connection()
            CAUSE log_event("packet_loss")
            CAUSE reroute_traffic()
        """)
        assert len(rules) == 1
        rule = rules[0]
        assert len(rule.cause_actions) == 2
        assert rule.cause_actions[0].function_name == "log_event"
        assert rule.cause_actions[1].function_name == "reroute_traffic"

    def test_parse_multiple_rules(self):
        source = """
            IF cpu_usage > 80%
            THEN log_event("high_cpu")
            CAUSE reduce_process_priority()

            IF memory_usage >= 90%
            THEN alert_admin()
        """
        rules = self.parser.parse(source)
        assert len(rules) == 2

    def test_parse_operators(self):
        ops = [">", ">=", "<", "<=", "==", "!="]
        for op in ops:
            rule = self.parser.parse_one(f"IF cpu_usage {op} 50\nTHEN act()")
            assert rule.condition.operator == op

    def test_parse_no_percentage(self):
        rule = self.parser.parse_one("IF queue_depth == 100\nTHEN drain_queue()")
        assert rule.condition.numeric_value == 100.0
        assert not rule.condition.is_percentage

    def test_parse_action_args(self):
        rule = self.parser.parse_one(
            'IF cpu_usage > 80%\nTHEN log_event("high_cpu", "urgent")'
        )
        assert rule.then_action.args == ['"high_cpu"', '"urgent"']

    def test_parse_action_no_args(self):
        rule = self.parser.parse_one("IF cpu_usage > 80%\nTHEN noop()")
        assert rule.then_action.args == []

    # --- Separator support ---

    def test_rule_block_separator_dash(self):
        source = "IF a > 1\nTHEN f()\n---\nIF b > 2\nTHEN g()"
        rules = self.parser.parse(source)
        assert len(rules) == 2

    # --- Error cases ---

    def test_missing_if_raises(self):
        with pytest.raises(ParseError):
            self.parser.parse("THEN log_event()")

    def test_missing_then_raises(self):
        with pytest.raises(ParseError, match="no THEN"):
            self.parser.parse("IF cpu_usage > 80%")

    def test_bad_condition_raises(self):
        with pytest.raises(ParseError):
            self.parser.parse("IF cpu_usage what?\nTHEN f()")

    def test_bad_action_raises(self):
        with pytest.raises(ParseError):
            self.parser.parse("IF cpu > 80%\nTHEN not-valid-action")

    def test_multiple_then_raises(self):
        with pytest.raises(ParseError, match="Multiple THEN"):
            self.parser.parse(
                "IF cpu_usage > 80%\nTHEN log_event()\nTHEN another()"
            )

    def test_empty_source_returns_empty_list(self):
        rules = self.parser.parse("   \n\n  ")
        assert rules == []


# ---------------------------------------------------------------------------
# ConditionAST tests
# ---------------------------------------------------------------------------

class TestConditionAST:
    def test_numeric_value_no_percent(self):
        cond = ConditionAST(metric="x", operator=">", value="42", raw="IF x > 42")
        assert cond.numeric_value == 42.0
        assert not cond.is_percentage

    def test_numeric_value_with_percent(self):
        cond = ConditionAST(metric="x", operator=">", value="75.5%", raw="IF x > 75.5%")
        assert cond.numeric_value == 75.5
        assert cond.is_percentage


# ---------------------------------------------------------------------------
# Compiler tests
# ---------------------------------------------------------------------------

class TestDSLCompiler:
    def setup_method(self):
        self.parser = RuleParser()
        self.results = []
        self.registry = {
            "log_event": lambda ctx, *a: self.results.append(("log", a)),
            "reduce_process_priority": lambda ctx, *a: self.results.append(("reduce", a)),
            "throttle_connection": lambda ctx, *a: self.results.append(("throttle", a)),
            "reroute_traffic": lambda ctx, *a: self.results.append(("reroute", a)),
        }
        self.compiler = DSLCompiler(action_registry=self.registry)

    def _compile(self, source: str) -> CausalGraph:
        rules = self.parser.parse(source)
        return self.compiler.compile(rules)

    def test_simple_rule_creates_correct_nodes(self):
        g = self._compile(
            'IF cpu_usage > 80%\nTHEN log_event("high_cpu")\nCAUSE reduce_process_priority()'
        )
        assert len(g.nodes) == 3
        node_types = [type(n).__name__ for n in g.nodes]
        assert "ConditionNode" in node_types
        assert node_types.count("ActionNode") == 2

    def test_edges_wired_correctly(self):
        g = self._compile(
            'IF cpu_usage > 80%\nTHEN log_event("high_cpu")\nCAUSE reduce_process_priority()'
        )
        edges = g.edges
        assert len(edges) == 2
        labels = {e.label for e in edges}
        assert "triggers" in labels
        assert "causes" in labels

    def test_condition_true_executes_actions(self):
        g = self._compile(
            'IF cpu_usage > 80%\nTHEN log_event("high_cpu")\nCAUSE reduce_process_priority()'
        )
        g.tick({"cpu_usage": 90})
        assert any(r[0] == "log" for r in self.results)
        assert any(r[0] == "reduce" for r in self.results)

    def test_condition_false_does_not_execute_actions(self):
        g = self._compile(
            'IF cpu_usage > 80%\nTHEN log_event("high_cpu")\nCAUSE reduce_process_priority()'
        )
        g.tick({"cpu_usage": 50})
        assert self.results == []

    def test_unregistered_action_is_stub_no_error(self):
        g = self._compile("IF x > 1\nTHEN unknown_action()")
        # Should not raise; stub is used
        g.tick({"x": 10})

    def test_compile_multiple_rules(self):
        source = """
            IF cpu_usage > 80%
            THEN log_event()

            IF packet_loss > 5%
            THEN throttle_connection()
            CAUSE reroute_traffic()
        """
        g = self._compile(source)
        # Rule 1: 2 nodes; Rule 2: 3 nodes
        assert len(g.nodes) == 5

    def test_compile_into_existing_graph(self):
        g = CausalGraph()
        rules = self.parser.parse("IF x > 1\nTHEN log_event()")
        self.compiler.compile(rules, graph=g)
        assert len(g.nodes) == 2

    def test_all_operators(self):
        ops_and_truths = [
            (">",  50, 40),
            (">=", 50, 50),
            ("<",  40, 50),
            ("<=", 50, 50),
            ("==", 50, 50),
            ("!=", 50, 40),
        ]
        for op, ctx_val, threshold in ops_and_truths:
            g = self._compile(f"IF metric {op} {threshold}\nTHEN log_event()")
            self.results.clear()
            g.tick({"metric": ctx_val})
            assert len(self.results) == 1, f"Operator {op} failed with value {ctx_val}"
            g.reset()
