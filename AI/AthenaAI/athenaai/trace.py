"""Very verbose runtime tracing for long-running AthenaAI operations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import os
import sys
from time import perf_counter
from typing import Any, Iterator


_TRACE_ENABLED = os.environ.get("ATHENAAI_TRACE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}


def set_trace_enabled(enabled: bool) -> None:
    """Enable or disable function-level tracing for this process."""

    global _TRACE_ENABLED
    _TRACE_ENABLED = enabled


def is_trace_enabled() -> bool:
    return _TRACE_ENABLED


def trace(message: str, **metadata: Any) -> None:
    """Emit one trace line when tracing is enabled."""

    if not _TRACE_ENABLED:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    parts = [f"[athena-trace] {timestamp}", message]
    if metadata:
        formatted = " ".join(f"{key}={value!r}" for key, value in metadata.items())
        parts.append(formatted)
    print(" | ".join(parts), file=sys.stderr, flush=True)


def _short_error(error: BaseException, max_length: int = 240) -> str:
    text = str(error)
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3]}..."


@contextmanager
def trace_scope(name: str, **metadata: Any) -> Iterator[None]:
    """Trace a function/block with ENTER, EXIT, and elapsed duration."""

    if not _TRACE_ENABLED:
        yield
        return

    started = perf_counter()
    trace(f"ENTER {name}", **metadata)
    try:
        yield
    except Exception as exc:
        trace(
            f"RAISE {name}",
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
            error_type=type(exc).__name__,
            error=_short_error(exc),
        )
        raise
    else:
        trace(f"EXIT {name}", elapsed_ms=round((perf_counter() - started) * 1000, 3))
