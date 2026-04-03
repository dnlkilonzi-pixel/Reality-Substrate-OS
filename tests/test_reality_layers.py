"""
Tests for reality layers (BaseLayer, DeterministicLayer, SlowTimeLayer)
and the LayerStack.
"""
import time
import pytest

from reality_layers.base_layer import BaseLayer, LayerStack
from reality_layers.deterministic_layer import DeterministicLayer
from reality_layers.slow_time_layer import SlowTimeLayer


class TestBaseLayer:
    def test_time_now_returns_float(self):
        layer = BaseLayer()
        t = layer.time_now()
        assert isinstance(t, float)

    def test_memory_alloc_returns_dict(self):
        layer = BaseLayer()
        alloc = layer.memory_alloc(128)
        assert alloc["size"] == 128
        assert "address" in alloc

    def test_process_schedule_returns_dict(self):
        layer = BaseLayer()
        result = layer.process_schedule(42, priority=5)
        assert result["pid"] == 42
        assert result["priority"] == 5
        assert result["scheduled"] is True

    def test_io_read_returns_bytes(self):
        layer = BaseLayer()
        assert layer.io_read("/dev/null") == b""

    def test_io_write_returns_length(self):
        layer = BaseLayer()
        assert layer.io_write("/dev/null", b"hello") == 5

    def test_inject_and_drain_events(self):
        layer = BaseLayer()
        layer.inject_event("cpu_spike", {"value": 95})
        layer.inject_event("mem_low", {"free_mb": 10})
        events = layer.drain_events()
        assert len(events) == 2
        assert events[0]["event_type"] == "cpu_spike"
        # After drain, queue is empty
        assert layer.drain_events() == []

    def test_enabled_flag(self):
        layer = BaseLayer()
        assert layer.enabled is True
        layer.enabled = False
        assert layer.enabled is False


class TestDeterministicLayer:
    def test_time_is_logical_not_wall_clock(self):
        layer = DeterministicLayer(start_time=0.0, time_step=1.0)
        t1 = layer.time_now()
        t2 = layer.time_now()
        t3 = layer.time_now()
        assert t1 == 0.0
        assert t2 == 1.0
        assert t3 == 2.0

    def test_custom_time_step(self):
        layer = DeterministicLayer(start_time=100.0, time_step=10.0)
        assert layer.time_now() == 100.0
        assert layer.time_now() == 110.0

    def test_memory_alloc_is_sequential(self):
        layer = DeterministicLayer()
        a1 = layer.memory_alloc(64)
        a2 = layer.memory_alloc(32)
        assert a2["address"] == a1["address"] + 64

    def test_process_schedule_always_priority_zero(self):
        layer = DeterministicLayer()
        result = layer.process_schedule(7, priority=99)
        assert result["priority"] == 0

    def test_io_read_returns_empty(self):
        layer = DeterministicLayer()
        assert layer.io_read("/any/path") == b""

    def test_io_write_discards_data(self):
        layer = DeterministicLayer()
        n = layer.io_write("/any/path", b"should be discarded")
        assert n == len(b"should be discarded")

    def test_reset_clock(self):
        layer = DeterministicLayer(start_time=0.0)
        layer.time_now()
        layer.time_now()
        layer.reset_clock(50.0)
        assert layer.time_now() == 50.0

    def test_current_time_does_not_advance(self):
        layer = DeterministicLayer(start_time=5.0, time_step=1.0)
        assert layer.current_time == 5.0
        layer.time_now()
        assert layer.current_time == 6.0


class TestSlowTimeLayer:
    def test_factor_one_returns_approximately_wall_time(self):
        epoch = time.time()
        layer = SlowTimeLayer(factor=1.0, epoch=epoch)
        t = layer.time_now()
        # Should be very close to wall time
        assert abs(t - time.time()) < 1.0

    def test_factor_two_approximately_doubles_elapsed(self):
        epoch = time.time() - 10.0  # pretend we started 10s ago
        layer = SlowTimeLayer(factor=2.0, epoch=epoch)
        t = layer.time_now()
        # elapsed ≈ 10s; scaled ≈ 20s; so t ≈ epoch + 20
        expected = epoch + 20.0
        assert abs(t - expected) < 1.0

    def test_factor_half_slows_time(self):
        epoch = time.time() - 10.0
        layer = SlowTimeLayer(factor=0.5, epoch=epoch)
        t = layer.time_now()
        expected = epoch + 5.0
        assert abs(t - expected) < 1.0

    def test_invalid_factor_raises(self):
        with pytest.raises(ValueError):
            SlowTimeLayer(factor=0)
        with pytest.raises(ValueError):
            SlowTimeLayer(factor=-1.0)

    def test_factor_property_setter_validates(self):
        layer = SlowTimeLayer(factor=1.0)
        with pytest.raises(ValueError):
            layer.factor = 0.0

    def test_factor_property_setter_updates(self):
        layer = SlowTimeLayer(factor=1.0)
        layer.factor = 3.0
        assert layer.factor == 3.0


class TestLayerStack:
    def test_empty_stack_falls_back_to_wall_time(self):
        stack = LayerStack()
        # No layers; time_now should still return a reasonable float
        t = stack.time_now()
        assert isinstance(t, float)

    def test_deterministic_layer_overrides_time(self):
        stack = LayerStack()
        stack.push(BaseLayer())
        stack.push(DeterministicLayer(start_time=42.0, time_step=1.0))
        assert stack.time_now() == 42.0

    def test_topmost_layer_wins(self):
        stack = LayerStack()
        stack.push(DeterministicLayer(start_time=1.0))
        stack.push(DeterministicLayer(start_time=99.0))
        assert stack.time_now() == 99.0

    def test_disabled_layer_is_skipped(self):
        stack = LayerStack()
        base = BaseLayer()
        top = DeterministicLayer(start_time=0.0)
        top.enabled = False
        stack.push(base)
        stack.push(top)
        # Top layer is disabled; falls back to base
        t = stack.time_now()
        assert isinstance(t, float)
        # Should be wall-clock time, not 0.0
        assert t > 1_000_000_000  # sanity: after year 2001

    def test_drain_all_events_collects_from_all_layers(self):
        stack = LayerStack()
        l1 = BaseLayer()
        l2 = BaseLayer()
        l1.inject_event("a", {})
        l2.inject_event("b", {})
        stack.push(l1)
        stack.push(l2)
        events = stack.drain_all_events()
        types = [e["event_type"] for e in events]
        assert "a" in types
        assert "b" in types

    def test_pop_removes_topmost_layer(self):
        stack = LayerStack()
        l1 = BaseLayer()
        l2 = BaseLayer()
        stack.push(l1)
        stack.push(l2)
        popped = stack.pop()
        assert popped is l2
        assert len(stack.layers) == 1

    def test_repr(self):
        stack = LayerStack()
        stack.push(BaseLayer())
        assert "BaseLayer" in repr(stack)
