"""
Rule DSL Parser — converts rule text into an Abstract Syntax Tree (AST).

Supported grammar::

    IF   <condition_expression>
    THEN <action_call>
    CAUSE <action_call>
    CAUSE <action_call>
    ...

Where:
  * ``<condition_expression>`` is ``<metric> <op> <value>``
    e.g. ``cpu_usage > 80%``, ``packet_loss >= 5%``, ``queue_depth == 100``
  * ``<action_call>`` is ``<function_name>(<optional_args>)``
    e.g. ``log_event("high_cpu")``, ``reduce_process_priority()``

Multiple rules can appear in the same source string, separated by blank
lines or ``---`` delimiters.

Example source::

    IF cpu_usage > 80%
    THEN log_event("high_cpu")
    CAUSE reduce_process_priority()

    IF packet_loss > 5%
    THEN throttle_connection()
    CAUSE log_event("packet_loss")
    CAUSE reroute_traffic()
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# AST node definitions
# ---------------------------------------------------------------------------

@dataclass
class ConditionAST:
    """
    Represents a parsed condition expression.

    Attributes
    ----------
    metric : str
        The metric or variable name (e.g. ``"cpu_usage"``).
    operator : str
        Comparison operator: ``>``, ``>=``, ``<``, ``<=``, ``==``, ``!=``.
    value : str
        Raw right-hand-side value as a string (may include ``%`` suffix).
    raw : str
        The original un-parsed condition text.
    """

    metric: str
    operator: str
    value: str
    raw: str

    @property
    def numeric_value(self) -> float:
        """Return *value* as a float, stripping a trailing ``%`` if present."""
        return float(self.value.rstrip("%"))

    @property
    def is_percentage(self) -> bool:
        return self.value.endswith("%")


@dataclass
class ActionAST:
    """
    Represents a parsed action call.

    Attributes
    ----------
    function_name : str
        The name of the action function (e.g. ``"log_event"``).
    args : list of str
        Positional arguments as raw strings (quotes preserved).
    raw : str
        The original un-parsed action text.
    role : str
        Either ``"THEN"`` (primary effect) or ``"CAUSE"`` (downstream effect).
    """

    function_name: str
    args: List[str]
    raw: str
    role: str = "THEN"


@dataclass
class RuleAST:
    """
    The complete AST for one IF/THEN/CAUSE rule.

    Attributes
    ----------
    condition : ConditionAST
        The triggering condition.
    then_action : ActionAST
        The primary action (``THEN`` clause).
    cause_actions : list of ActionAST
        Zero or more downstream causal actions (``CAUSE`` clauses).
    raw : str
        Full original rule text.
    """

    condition: ConditionAST
    then_action: ActionAST
    cause_actions: List[ActionAST] = field(default_factory=list)
    raw: str = ""


# ---------------------------------------------------------------------------
# Parser implementation
# ---------------------------------------------------------------------------

# Patterns
_CONDITION_RE = re.compile(
    r"^IF\s+(?P<metric>\w+)\s*(?P<op>[><!]=?|==)\s*(?P<value>[\d.]+%?)\s*$",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"^(?P<role>THEN|CAUSE)\s+(?P<func>\w+)\s*\((?P<args>.*)\)\s*$",
    re.IGNORECASE,
)


def _parse_args(raw_args: str) -> List[str]:
    """Split a raw argument string into individual argument tokens."""
    if not raw_args.strip():
        return []
    return [a.strip() for a in raw_args.split(",") if a.strip()]


def _split_rule_blocks(source: str) -> List[str]:
    """Split source text into individual rule blocks."""
    # Blocks are separated by blank lines or "---"
    blocks: List[str] = []
    current: List[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped == "---" or (stripped == "" and current):
            if current:
                blocks.append("\n".join(current))
                current = []
        elif stripped:
            current.append(stripped)
    if current:
        blocks.append("\n".join(current))
    return blocks


class ParseError(ValueError):
    """Raised when a rule cannot be parsed."""


# Normalise a single-line rule "IF cond THEN action() CAUSE action()" into
# the canonical multi-line representation so that the rest of the parser
# does not need to change.
_SINGLE_LINE_SPLIT_RE = re.compile(
    r"(?<!\w)(THEN|CAUSE)\s+",
    re.IGNORECASE,
)


def _normalize_block(block: str) -> str:
    """
    If *block* is a single-line rule (all clauses on one line), split it
    at ``THEN`` / ``CAUSE`` keywords so each clause occupies its own line.

    Multi-line blocks pass through unchanged.
    """
    stripped = block.strip()
    # Only normalise single-line blocks that start with IF
    if "\n" in stripped or not re.match(r"^IF\s+", stripped, re.IGNORECASE):
        return block
    # Don't split if there's no THEN keyword (will fail later with a clear error)
    if not re.search(r"\bTHEN\b", stripped, re.IGNORECASE):
        return block
    # Replace THEN/CAUSE keywords (preceded by word-boundary) with newline + keyword
    normalised = re.sub(
        r"\s+(THEN|CAUSE)\s+",
        lambda m: f"\n{m.group(1).upper()} ",
        stripped,
        flags=re.IGNORECASE,
    )
    return normalised


class RuleParser:
    """
    Parses RS-CCE rule DSL source into a list of :class:`RuleAST` objects.

    Usage::

        parser = RuleParser()
        rules = parser.parse('''
            IF cpu_usage > 80%
            THEN log_event("high_cpu")
            CAUSE reduce_process_priority()
        ''')
    """

    def parse(self, source: str) -> List[RuleAST]:
        """
        Parse *source* and return a list of :class:`RuleAST` nodes.

        Raises :class:`ParseError` on malformed input.
        """
        rules: List[RuleAST] = []
        for block in _split_rule_blocks(source):
            rules.append(self._parse_block(block))
        return rules

    def parse_one(self, source: str) -> RuleAST:
        """Parse a single rule block and return its :class:`RuleAST`."""
        rules = self.parse(source.strip())
        if not rules:
            raise ParseError("Empty rule source")
        return rules[0]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_block(self, block: str) -> RuleAST:
        block = _normalize_block(block)
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            raise ParseError("Empty rule block")

        # --- IF line ---
        condition = self._parse_condition(lines[0], block)

        # --- THEN / CAUSE lines ---
        then_action: Optional[ActionAST] = None
        cause_actions: List[ActionAST] = []

        for line in lines[1:]:
            action = self._parse_action(line, block)
            if action.role.upper() == "THEN":
                if then_action is not None:
                    raise ParseError(
                        f"Multiple THEN clauses in rule:\n{block}"
                    )
                then_action = action
            else:
                cause_actions.append(action)

        if then_action is None:
            raise ParseError(f"Rule has no THEN clause:\n{block}")

        return RuleAST(
            condition=condition,
            then_action=then_action,
            cause_actions=cause_actions,
            raw=block,
        )

    def _parse_condition(self, line: str, block: str) -> ConditionAST:
        match = _CONDITION_RE.match(line)
        if not match:
            raise ParseError(
                f"Invalid IF condition on line {line!r}\n"
                f"Expected: IF <metric> <op> <value>[%]\n"
                f"In rule:\n{block}"
            )
        return ConditionAST(
            metric=match.group("metric"),
            operator=match.group("op"),
            value=match.group("value"),
            raw=line,
        )

    def _parse_action(self, line: str, block: str) -> ActionAST:
        match = _ACTION_RE.match(line)
        if not match:
            raise ParseError(
                f"Invalid action on line {line!r}\n"
                f"Expected: THEN|CAUSE <function>(<args>)\n"
                f"In rule:\n{block}"
            )
        return ActionAST(
            function_name=match.group("func"),
            args=_parse_args(match.group("args")),
            raw=line,
            role=match.group("role").upper(),
        )
