"""
State Store — a key/value store for the current system state snapshot.

The :class:`StateStore` acts as the shared memory of the RS-CCE runtime.
All causal node predicates read from it, and action nodes may write
back updated values.

It also keeps a full change log so that any past state can be
reconstructed for replay.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Optional, Tuple


class StateStore:
    """
    Thread-safe-by-convention key/value store with change history.

    Values are stored as plain Python objects.  Every mutation is
    recorded in :attr:`changelog` as a ``(timestamp, key, old, new)``
    tuple, enabling deterministic replay.

    Usage::

        store = StateStore()
        store.set("cpu_usage", 85)
        store.set("packet_loss", 3.2)

        print(store.get("cpu_usage"))   # 85
        print(store.snapshot())         # {'cpu_usage': 85, 'packet_loss': 3.2}
    """

    def __init__(self, initial: Optional[Dict[str, Any]] = None) -> None:
        self._data: Dict[str, Any] = dict(initial or {})
        self.changelog: List[Tuple[float, str, Any, Any]] = []

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, or *default* if absent."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key* and append to the changelog."""
        old = self._data.get(key)
        self._data[key] = value
        self.changelog.append((time.time(), key, old, value))

    def update(self, mapping: Dict[str, Any]) -> None:
        """Bulk-update from a dict; each entry is logged individually."""
        for k, v in mapping.items():
            self.set(k, v)

    def delete(self, key: str) -> None:
        """Remove *key* from the store."""
        old = self._data.pop(key, None)
        self.changelog.append((time.time(), key, old, None))

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a shallow copy of the current state."""
        return dict(self._data)

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """Replace the current state with *snapshot* (changelog is preserved)."""
        self._data = dict(snapshot)

    # ------------------------------------------------------------------
    # Replay support
    # ------------------------------------------------------------------

    def replay_to(self, timestamp: float) -> Dict[str, Any]:
        """
        Reconstruct the state as it was at *timestamp* by replaying the
        changelog up to that point.

        Returns the reconstructed state dict without modifying the live
        store.
        """
        state: Dict[str, Any] = {}
        for ts, key, _old, new in self.changelog:
            if ts > timestamp:
                break
            if new is None:
                state.pop(key, None)
            else:
                state[key] = new
        return state

    def clear_changelog(self) -> None:
        """Discard the change history (live state is unaffected)."""
        self.changelog.clear()

    def __repr__(self) -> str:
        return f"StateStore(keys={list(self._data.keys())}, changelog={len(self.changelog)})"
