"""
Tests for developer tools: Visualizer and EventTracer.
"""
import json
import os
import tempfile

import pytest

from core.causal_engine import CausalGraph
from core.event_bus import Event, EventBus
from core.node_types import ActionNode, ConditionNode
from tools.visualizer import Visualizer
from tools.event_tracer import EventTracer


class TestVisualizer:
    def _make_graph(self):
        g = CausalGraph()
        cond = ConditionNode("cond", lambda ctx: True)
        act1 = ActionNode("act1", lambda ctx: "a")
        act2 = ActionNode("act2", lambda ctx: "b")
        g.add_node(cond)
        g.add_node(act1)
        g.add_node(act2)
        g.add_edge(cond, act1)
        g.add_edge(act1, act2)
        return g, cond, act1, act2

    def test_ascii_contains_node_names(self):
        g, cond, act1, act2, = self._make_graph()
        viz = Visualizer(g)
        output = viz.ascii()
        assert "cond" in output
        assert "act1" in output
        assert "act2" in output

    def test_ascii_empty_graph(self):
        g = CausalGraph()
        viz = Visualizer(g)
        output = viz.ascii()
        assert "empty" in output

    def test_dot_contains_digraph(self):
        g, *_ = self._make_graph()
        viz = Visualizer(g)
        dot = viz.dot()
        assert "digraph CausalGraph" in dot
        assert "->" in dot

    def test_dot_node_labels(self):
        g, cond, *_ = self._make_graph()
        viz = Visualizer(g)
        dot = viz.dot()
        assert cond.name in dot

    def test_node_table_headers(self):
        g, *_ = self._make_graph()
        viz = Visualizer(g)
        table = viz.node_table()
        assert "Type" in table
        assert "Name" in table
        assert "State" in table

    def test_ascii_after_execution(self):
        g, cond, act1, act2 = self._make_graph()
        g.tick({})
        viz = Visualizer(g)
        output = viz.ascii()
        assert "✔" in output  # DONE marker


class TestEventTracer:
    def test_records_events(self):
        bus = EventBus()
        tracer = EventTracer(bus)
        bus.publish(Event("cpu_usage", {"value": 85}))
        bus.publish(Event("memory", {"value": 70}))
        assert len(tracer.trace) == 2

    def test_filter_by_type(self):
        bus = EventBus()
        tracer = EventTracer(bus)
        bus.publish(Event("cpu_usage", {"value": 85}))
        bus.publish(Event("memory", {"value": 70}))
        cpu_events = tracer.filter("cpu_usage")
        assert len(cpu_events) == 1
        assert cpu_events[0]["event_type"] == "cpu_usage"

    def test_timeline_output(self):
        bus = EventBus()
        tracer = EventTracer(bus, tag="test_trace")
        bus.publish(Event("ping", {}))
        timeline = tracer.timeline()
        assert "test_trace" in timeline
        assert "ping" in timeline

    def test_empty_timeline(self):
        bus = EventBus()
        tracer = EventTracer(bus, tag="empty")
        assert "no events" in tracer.timeline()

    def test_save_and_load(self):
        bus = EventBus()
        tracer = EventTracer(bus, tag="saved")
        bus.publish(Event("test_event", {"key": "val"}))

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracer.save(path)
            loaded = EventTracer.load(path)
            assert loaded.tag == "saved"
            assert len(loaded.trace) == 1
            assert loaded.trace[0]["event_type"] == "test_event"
        finally:
            os.unlink(path)

    def test_replay_republishes_events(self):
        bus = EventBus()
        tracer = EventTracer(bus)
        bus.publish(Event("alpha", {}))

        received = []
        target_bus = EventBus()
        target_bus.subscribe("alpha", lambda e: received.append(e))
        tracer.replay(target_bus)
        assert len(received) == 1

    def test_clear_resets_trace(self):
        bus = EventBus()
        tracer = EventTracer(bus)
        bus.publish(Event("x", {}))
        tracer.clear()
        assert tracer.trace == []
