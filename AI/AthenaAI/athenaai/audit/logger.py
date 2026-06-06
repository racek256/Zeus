"""Audit logging for AthenaAI - timestamp | agent | action | result format.

Logs all prompts, tool calls, actions, and physics results.
Avoids shadowing stdlib logging by using its own namespace.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuditEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: str = ""
    action: str = ""
    result: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_line(self) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        meta_str = json.dumps(self.metadata) if self.metadata else ""
        return f"{ts} | {self.agent_id} | {self.action} | {self.result} | {meta_str}"


class AuditLogger:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def log(
        self,
        agent_id: str,
        action: str,
        result: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        entry = AuditEntry(
            agent_id=agent_id,
            action=action,
            result=result,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        return entry.id

    def get_logs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "agent_id": e.agent_id,
                "action": e.action,
                "result": e.result,
                "metadata": e.metadata,
            }
            for e in self._entries
        ]

    def get_lines(self) -> list[str]:
        return [e.to_line() for e in self._entries]

    def clear(self) -> None:
        self._entries.clear()

    def filter_by_agent(self, agent_id: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.agent_id == agent_id]

    def filter_by_action(self, action: str) -> list[AuditEntry]:
        return [e for e in self._entries if e.action == action]