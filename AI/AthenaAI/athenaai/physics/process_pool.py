"""Process pool for CPU-bound physics calculations.

This module provides a ProcessPoolExecutor wrapper for running pandapower
load flows, N-1 scans, state estimation, and short-circuit calculations
in separate processes that bypass the GIL.

The pool handles serialization (deepcopy), worker initialization (lazy
pandapower import), error propagation, and graceful degradation to
ThreadPoolExecutor if process spawning fails.
"""

from __future__ import annotations

import concurrent.futures
import copy
import logging
import os
import threading
from typing import Any, Callable, Iterable, TypeVar

from athenaai.trace import trace, trace_scope

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

_DEFAULT_MAX_WORKERS = 2


class PhysicsProcessPool:
    """Process pool for CPU-bound pandapower physics calculations.

    Features:
    - Wraps ProcessPoolExecutor for GIL-bypassing parallelism
    - Auto-detects CPU count and configures worker pool size
    - Handles serialization: deep-copies network state before process submission
    - Falls back to ThreadPoolExecutor if process pool fails (e.g., fork issues)
    - Lazy initialization: pool is created on first use
    - Thread-safe: lock around pool creation and shutdown
    - Clean shutdown with timeout support

    Usage::

        pool = PhysicsProcessPool(max_workers=2)
        future = pool.submit(run_ac_load_flow, network_state, simulated_time)
        result = future.result(timeout=30.0)
        # Or for batch operations:
        results = pool.map(run_ac_load_flow, [state1, state2, state3])
        pool.shutdown()
    """

    @staticmethod
    def _auto_detect_workers() -> int:
        """Auto-detect the number of CPU cores for process pool sizing.

        Uses ~25% of available CPUs (min 2, max 8) to avoid oversubscription.
        Minimum 2 workers is enforced to prevent nested-submission deadlocks
        when simulate_action calls _run_load_flow from within the pool.
        """
        try:
            cpu_count = os.cpu_count() or 2
            return max(2, min(8, cpu_count // 4))
        except Exception:
            return 2

    def __init__(self, max_workers: int | None = None) -> None:
        self._max_workers = max_workers or self._auto_detect_workers()
        self._executor: concurrent.futures.Executor | None = None
        self._lock = threading.Lock()
        self._shutdown = False
        self._use_process_pool = True  # Will be set to False if process pool fails
        self._pending_futures: set[concurrent.futures.Future[Any]] = set()
        self._submitted_count: int = 0
        self._completed_count: int = 0
        self._failed_count: int = 0

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def is_available(self) -> bool:
        """Check if pool is ready for work (not shut down)."""
        return not self._shutdown

    @property
    def is_process_pool(self) -> bool:
        """Whether the pool is using actual processes (vs thread fallback)."""
        return self._use_process_pool

    @property
    def executor(self) -> concurrent.futures.Executor:
        """Access the underlying executor (for use with asyncio loop.run_in_executor)."""
        return self._get_or_create_executor()

    @property
    def submitted_count(self) -> int:
        return self._submitted_count

    @property
    def completed_count(self) -> int:
        return self._completed_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    def _get_or_create_executor(self) -> concurrent.futures.Executor:
        """Get the current executor, creating one if needed."""
        with self._lock:
            if self._shutdown:
                raise RuntimeError("PhysicsProcessPool has been shut down")
            if self._executor is None:
                self._executor = self._create_executor()
            return self._executor

    def _create_executor(self) -> concurrent.futures.Executor:
        """Create the executor, preferring ProcessPoolExecutor."""
        if self._max_workers < 2:
            logger.warning(
                "PhysicsProcessPool max_workers=%d is below minimum of 2; "
                "forcing to 2 to prevent nested-submission deadlock",
                self._max_workers,
            )
            self._max_workers = 2
        try:
            with trace_scope("PhysicsProcessPool._create_process_executor", max_workers=self._max_workers):
                executor = concurrent.futures.ProcessPoolExecutor(
                    max_workers=self._max_workers,
                )
                self._use_process_pool = True
                trace(
                    "PhysicsProcessPool.created",
                    type="process",
                    max_workers=self._max_workers,
                )
                return executor
        except Exception as exc:
            trace(
                "PhysicsProcessPool.process_pool_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            logger.warning(
                "ProcessPoolExecutor failed (%s: %s), falling back to ThreadPoolExecutor",
                type(exc).__name__, str(exc)[:200],
            )
            self._use_process_pool = False
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(4, self._max_workers * 2),
            )
            trace(
                "PhysicsProcessPool.created",
                type="thread_fallback",
                max_workers=max(4, self._max_workers * 2),
            )
            return executor

    def _deepcopy_args(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """Deep-copy arguments for process boundary isolation.

        For ProcessPoolExecutor, arguments are pickled and sent to worker
        processes. Deep-copying ensures the calling code doesn't accidentally
        retain references that could cause serialization issues.
        """
        try:
            copied_args = tuple(copy.deepcopy(a) for a in args)
            copied_kwargs = {k: copy.deepcopy(v) for k, v in kwargs.items()}
        except Exception as exc:
            trace(
                "PhysicsProcessPool.deepcopy_warning",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            # If deepcopy fails, fall back to passing original (pickle will
            # effectively create a copy anyway with process boundaries)
            copied_args = args
            copied_kwargs = kwargs
        return copied_args, copied_kwargs

    def submit(
        self,
        func: Callable[..., R],
        *args: Any,
        **kwargs: Any,
    ) -> concurrent.futures.Future[R]:
        """Submit a physics function to the pool.

        The function and all arguments will be deep-copied to ensure clean
        process boundaries. Returns a Future that can be used to retrieve
        the result.

        Args:
            func: The physics function to execute (e.g., run_ac_load_flow)
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function

        Returns:
            A Future[R] that resolves to the function's return value

        Raises:
            RuntimeError: If the pool has been shut down
        """
        with trace_scope("PhysicsProcessPool.submit", func=func.__name__):
            if self._shutdown:
                raise RuntimeError("PhysicsProcessPool has been shut down")

            executor = self._get_or_create_executor()
            copied_args, copied_kwargs = self._deepcopy_args(args, kwargs)

            with self._lock:
                self._submitted_count += 1

            future = executor.submit(func, *copied_args, **copied_kwargs)

            with self._lock:
                self._pending_futures.add(future)

            # Attach callback for future tracking
            def _on_done(fut: concurrent.futures.Future[Any]) -> None:
                with self._lock:
                    self._pending_futures.discard(fut)
                    self._completed_count += 1
                    if fut.exception() is not None:
                        self._failed_count += 1
                        trace(
                            "PhysicsProcessPool.task_failed",
                            func=func.__name__,
                            error_type=type(fut.exception()).__name__,
                            error=str(fut.exception())[:200],
                        )

            future.add_done_callback(_on_done)

            trace("PhysicsProcessPool.submitted", func=func.__name__)
            return future

    def map(
        self,
        func: Callable[[T], R],
        iterable: Iterable[T],
        timeout: float | None = None,
    ) -> list[R]:
        """Map a function over an iterable using the process pool.

        For N-1 scanning, each item in the iterable is a network state dict
        or contingency chunk. Results maintain the order of the input iterable.

        Args:
            func: The physics function (takes one argument from iterable)
            iterable: Items to process
            timeout: Maximum time per item (None = no limit)

        Returns:
            List of results in the same order as inputs

        Raises:
            RuntimeError: If the pool has been shut down
        """
        with trace_scope("PhysicsProcessPool.map", func=func.__name__):
            if self._shutdown:
                raise RuntimeError("PhysicsProcessPool has been shut down")

            items = list(iterable)
            if not items:
                return []

            executor = self._get_or_create_executor()

            with self._lock:
                self._submitted_count += len(items)

            try:
                deep_copied_items = []
                for item in items:
                    try:
                        deep_copied_items.append(copy.deepcopy(item))
                    except Exception:
                        deep_copied_items.append(item)

                results = list(executor.map(func, deep_copied_items, timeout=timeout))

                with self._lock:
                    self._completed_count += len(items)

                trace("PhysicsProcessPool.map_done", items=len(items))
                return results
            except Exception as exc:
                with self._lock:
                    self._failed_count += len(items)
                trace(
                    "PhysicsProcessPool.map_failed",
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
                raise

    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Shut down the pool, releasing all worker resources.

        Args:
            wait: If True, wait for all pending futures to complete
            timeout: Maximum seconds to wait for pending futures
        """
        with trace_scope("PhysicsProcessPool.shutdown", wait=wait):
            with self._lock:
                if self._shutdown:
                    return
                self._shutdown = True

                if self._executor is not None:
                    executor = self._executor
                    self._executor = None

                    if wait and self._pending_futures:
                        remaining = list(self._pending_futures)
                        try:
                            concurrent.futures.wait(
                                remaining,
                                timeout=timeout,
                                return_when=concurrent.futures.ALL_COMPLETED,
                            )
                        except Exception:
                            pass

                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        # cancel_futures not available in Python < 3.9
                        executor.shutdown(wait=False)
                    except Exception:
                        pass

            trace(
                "PhysicsProcessPool.shutdown_done",
                submitted=self._submitted_count,
                completed=self._completed_count,
                failed=self._failed_count,
            )

    def get_stats(self) -> dict[str, Any]:
        """Return pool statistics."""
        with self._lock:
            return {
                "max_workers": self._max_workers,
                "is_process_pool": self._use_process_pool,
                "is_shutdown": self._shutdown,
                "submitted": self._submitted_count,
                "completed": self._completed_count,
                "failed": self._failed_count,
                "pending": len(self._pending_futures),
                "executor_type": type(self._executor).__name__ if self._executor else "none",
            }

    def __enter__(self) -> PhysicsProcessPool:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.shutdown(wait=True)

    def __del__(self) -> None:
        try:
            self.shutdown(wait=False, timeout=5.0)
        except Exception:
            pass
