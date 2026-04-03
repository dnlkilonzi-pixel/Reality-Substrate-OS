"""
Reality Layer System — pluggable runtime modules that override system semantics.

Each layer inherits from :class:`BaseLayer` and can intercept or redefine:

* ``time_now()``          — current time (seconds since epoch)
* ``memory_alloc(size)``  — allocate *size* bytes, returns a handle
* ``process_schedule(pid, priority)``  — schedule a process
* ``io_read(path)``       — read bytes from a resource
* ``io_write(path, data)`` — write bytes to a resource

Layers stack in order::

    Base OS → Layer N → Layer N+1 → Runtime Override

Higher layers shadow lower ones; the :class:`LayerStack` class manages
the ordering and delegates each syscall down the stack until a layer
handles it.
"""
from .base_layer import BaseLayer, LayerStack
from .deterministic_layer import DeterministicLayer
from .slow_time_layer import SlowTimeLayer

__all__ = [
    "BaseLayer",
    "LayerStack",
    "DeterministicLayer",
    "SlowTimeLayer",
]
