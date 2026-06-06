"""Terminal live views for AthenaAI agent work.

The live view is intentionally dependency-free. It provides a simple ANSI TUI-like
dashboard for terminal runs and plain log lines for non-interactive output.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from shutil import get_terminal_size
from typing import Any, Protocol

from athenaai.schema import ActionBundle


ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
AUDIT_TAIL_LINES = 8


class AgentResponseLike(Protocol):
    agent_id: str
    action: ActionBundle | None
    reasoning: str
    timestamp: datetime


@dataclass(frozen=True)
class AgentWorkLog:
    hour_index: int
    timestamp: datetime
    agent_id: str
    model: str
    reasoning: str
    action_summary: str
    action_details: dict[str, Any]

    def to_line(self) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M")
        return (
            f"{ts} | hour={self.hour_index:04d} | {self.agent_id} | "
            f"model={self.model} | action={self.action_summary} | {sanitize_terminal_text(self.reasoning)}"
        )


def sanitize_terminal_text(value: str) -> str:
    return ANSI_ESCAPE_PATTERN.sub("", value)


def summarize_action(action: ActionBundle | None) -> str:
    if action is None:
        return "none"
    if action.is_empty():
        return "none"
    parts: list[str] = []
    for attr, label in [
        ("generator_setpoint_changes", "gen"),
        ("redispatch_requests", "redispatch"),
        ("load_shedding_flags", "shed"),
        ("interconnect_flow_adjustments", "tie"),
    ]:
        values = getattr(action, attr, ())
        if values:
            parts.append(f"{label}:{len(values)}")
    return ",".join(parts) if parts else "non-empty"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def action_details(action: ActionBundle | None) -> dict[str, Any]:
    if action is None:
        return {}
    return _jsonable(action)


def build_agent_work_logs(
    hour_index: int,
    responses: Mapping[str, AgentResponseLike],
    model_lookup: Mapping[str, str],
) -> list[AgentWorkLog]:
    logs: list[AgentWorkLog] = []
    for agent_id, response in responses.items():
        logs.append(
            AgentWorkLog(
                hour_index=hour_index,
                timestamp=response.timestamp,
                agent_id=agent_id,
                model=model_lookup.get(agent_id, "unknown"),
                reasoning=response.reasoning,
                action_summary=summarize_action(response.action),
                action_details=action_details(response.action),
            )
        )
    return logs


def print_agent_work_logs(logs: list[AgentWorkLog]) -> None:
    for log in logs:
        print(log.to_line())


def print_agent_output_only(logs: list[AgentWorkLog], audit_lines: list[str]) -> None:
    for line in format_agent_output_block(logs, audit_lines):
        print(line)


def format_agent_output_block(logs: list[AgentWorkLog], audit_lines: list[str]) -> list[str]:
    if not logs and not audit_lines:
        return []
    lines: list[str] = []
    if logs:
        hour_index = logs[0].hour_index
        timestamp = logs[0].timestamp.strftime("%Y-%m-%d %H:%M")
        lines.append(f"=== Agent output | hour={hour_index:04d} | {timestamp} ===")
    else:
        lines.append("=== Agent output ===")

    for log in logs:
        lines.append(log.to_line())
        lines.append(f"  Reasoning: {sanitize_terminal_text(log.reasoning)}")
        if log.action_details:
            lines.append("  Action details:")
            lines.extend(
                f"    {line}"
                for line in json.dumps(log.action_details, indent=2, sort_keys=True).splitlines()
            )

    agent_audit_lines = [
        sanitize_terminal_text(line)
        for line in audit_lines
        if " | simulator | " not in line
    ]
    if agent_audit_lines:
        lines.append("--- Agent audit/tool events ---")
        for line in agent_audit_lines:
            lines.append(line)
    return lines


class AgentOutputFileLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def append(self, logs: list[AgentWorkLog], audit_lines: list[str]) -> None:
        lines = format_agent_output_block(logs, audit_lines)
        if not lines:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
            handle.write("\n")


class AgentLogTUI:
    def __init__(self, max_lines: int = 30) -> None:
        self.max_lines = max(1, max_lines)
        self._lines: list[str] = []

    def update(
        self,
        hour_index: int,
        total_hours: int,
        logs: list[AgentWorkLog],
        audit_lines: list[str],
        failed_hours: list[int],
    ) -> None:
        for log in logs:
            self._lines.append(log.to_line())
        if len(self._lines) > self.max_lines:
            self._lines = self._lines[-self.max_lines :]

        width = get_terminal_size((120, 40)).columns
        header = f" AthenaAI live agent log | hour {hour_index}/{total_hours} | failures={len(failed_hours)} "
        print("\033[2J\033[H", end="")
        print(header[:width].ljust(width, "="))
        print("Agent work".ljust(width, "-"))
        for line in self._lines:
            print(line[:width])
        print("Audit tail".ljust(width, "-"))
        for line in audit_lines[-min(AUDIT_TAIL_LINES, self.max_lines) :]:
            print(sanitize_terminal_text(line)[:width])
        sys.stdout.flush()
