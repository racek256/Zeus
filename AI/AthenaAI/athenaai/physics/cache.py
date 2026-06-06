"""Intelligent result caching for physics engine computations.

This module provides topology-aware caching with TTL-based expiration.
Cache keys are deterministic hashes of network topology and operating point
features, enabling cache hits across repeated analyses of similar states.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    """A single entry in the result cache."""

    key: str
    result: Any
    created_at: float
    ttl: float
    hit_count: int = 0

    def is_expired(self) -> bool:
        return time.monotonic() - self.created_at > self.ttl


class ResultCache:
    """Topology-aware cache for physics engine results.

    Features:
    - Deterministic key generation from network topology and operating point
    - TTL-based expiration (configurable per cache type)
    - Thread-safe operations
    - Memory-efficient: limits total entries via max_size
    - Hit/miss statistics

    Usage::

        cache = ResultCache()
        key = cache.make_key(network_state, operation="load_flow")
        result = cache.get(key)
        if result is None:
            result = run_load_flow(network_state)
            cache.put(key, result, ttl=60.0)
    """

    def __init__(self, max_size: int = 256) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def make_key(
        self,
        network_state: dict[str, Any],
        operation: str = "",
        **extra_params: Any,
    ) -> str:
        """Generate a deterministic cache key from network state.

        The key incorporates:
        - Topology signature: bus IDs, branch connectivity (but NOT voltage/current values)
        - Operating point signature: generator dispatch, load levels
        - Operation type: load_flow, opf, n1, etc.
        - Extra parameters specific to the analysis type
        """
        topology_features = self._extract_topology_features(network_state)
        operating_features = self._extract_operating_features(network_state)
        components = {
            "op": operation,
            "topo": topology_features,
            "oper": operating_features,
            "extra": extra_params,
        }
        serialized = json.dumps(components, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _extract_topology_features(network_state: dict[str, Any]) -> dict[str, Any]:
        """Extract topology-relevant features (connectivity, NOT values)."""
        buses = network_state.get("buses", [])
        branches = network_state.get("branches", [])
        generators = network_state.get("generators", [])
        loads = network_state.get("loads", [])

        bus_ids = sorted(str(b.get("bus_id", b.get("name", ""))) for b in buses)
        branch_edges = sorted(
            (str(b.get("from_bus", "")), str(b.get("to_bus", "")))
            for b in branches
        )
        gen_buses = sorted(str(g.get("bus", "")) for g in generators)
        load_buses = sorted(str(l.get("bus", "")) for l in loads)

        return {
            "bus_count": len(buses),
            "bus_ids": bus_ids,
            "branch_edges": branch_edges,
            "gen_buses": gen_buses,
            "load_buses": load_buses,
        }

    @staticmethod
    def _extract_operating_features(network_state: dict[str, Any]) -> dict[str, Any]:
        """Extract operating point features (rounded values for cacheability)."""
        generators = network_state.get("generators", [])
        loads = network_state.get("loads", [])

        gen_dispatch = sorted(
            (str(g.get("generator_id", g.get("name", ""))), round(float(g.get("p_mw", 0.0)), 2))
            for g in generators
        )
        load_levels = sorted(
            (str(l.get("load_id", l.get("name", ""))), round(float(l.get("p_mw", 0.0)), 2))
            for l in loads
        )
        gen_total = round(sum(p for _, p in gen_dispatch), 2)
        load_total = round(sum(p for _, p in load_levels), 2)

        return {
            "gen_total_mw": gen_total,
            "load_total_mw": load_total,
            "gen_dispatch": gen_dispatch,
            "load_levels": load_levels,
        }

    def get(self, key: str) -> Any | None:
        """Retrieve a cached result if present and not expired."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired():
                del self._entries[key]
                self._evictions += 1
                self._misses += 1
                return None
            entry.hit_count += 1
            self._hits += 1
            return entry.result

    def put(self, key: str, result: Any, ttl: float = 300.0) -> None:
        """Store a result in the cache with TTL (seconds)."""
        with self._lock:
            if len(self._entries) >= self._max_size:
                self._evict_lru()
            self._entries[key] = CacheEntry(
                key=key,
                result=result,
                created_at=time.monotonic(),
                ttl=ttl,
            )

    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if not self._entries:
            return
        lru_key = min(self._entries, key=lambda k: self._entries[k].created_at)
        del self._entries[lru_key]
        self._evictions += 1

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate a specific key or all entries."""
        with self._lock:
            if key is not None:
                self._entries.pop(key, None)
            else:
                self._entries.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "size": len(self._entries),
                "max_size": self._max_size,
                "hit_rate": round(hit_rate, 4),
            }
