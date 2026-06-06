"""MCP-first peer-bus scaffold for AthenaAI agent communication.

This module implements a typed message bus for peer-to-peer communication
between coordinator and regional agents. The bus follows MCP-first design
principles where agents communicate via typed messages, not direct calls.

Message types:
- Telemetry: Read-only data visible to all agents
- Negotiation: Typed requests between agents (transfer requests, redispatch)
- Commands: Coordinator-issued directives (regional agents cannot issue commands)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from athenaai.config import (
    AGENT_BOHEMIA_EAST,
    AGENT_BOHEMIA_WEST,
    AGENT_COORDINATOR,
    AGENT_MORAVIA,
    AGENT_ORACLE,
    AGENT_SILESIA,
)


class MessageType(str, Enum):
    TELEMETRY = "telemetry"
    NEGOTIATION = "negotiation"
    COMMAND = "command"
    RESPONSE = "response"


class TelemetryCategory(str, Enum):
    LOAD_VS_SCHEDULE = "load_vs_schedule"
    AVAILABLE_HEADROOM = "available_headroom"
    RESERVE_STATUS = "reserve_status"
    ACTIVE_ALARMS = "active_alarms"


class NegotiationType(str, Enum):
    TRANSFER_REQUEST = "transfer_request"
    REDISPATCH_ASK = "redispatch_ask"
    REDISPATCH_OFFER = "redispatch_offer"
    TRANSFER_ACCEPT = "transfer_accept"
    TRANSFER_REJECT = "transfer_reject"


@dataclass
class PeerMessage:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sender: str = ""
    recipient: str | None = None
    message_type: MessageType = MessageType.TELEMETRY
    category: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    simulated_time: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "sender": self.sender,
            "recipient": self.recipient,
            "message_type": self.message_type.value,
            "category": self.category,
            "payload": self.payload,
            "simulated_time": (
                self.simulated_time.isoformat() if self.simulated_time else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeerMessage:
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            sender=data["sender"],
            recipient=data.get("recipient"),
            message_type=MessageType(data["message_type"]),
            category=data.get("category"),
            payload=data.get("payload", {}),
            simulated_time=(
                datetime.fromisoformat(data["simulated_time"])
                if data.get("simulated_time")
                else None
            ),
        )


@dataclass
class TelemetryMessage(PeerMessage):
    category: str | None = None
    message_type: MessageType = field(default=MessageType.TELEMETRY)

    def __post_init__(self) -> None:
        if isinstance(self.category, TelemetryCategory):
            object.__setattr__(self, 'category', self.category.value)


@dataclass
class NegotiationMessage(PeerMessage):
    negotiation_type: NegotiationType | None = None
    message_type: MessageType = field(default=MessageType.NEGOTIATION)


@dataclass
class CommandMessage(PeerMessage):
    category: str | None = None
    message_type: MessageType = field(default=MessageType.COMMAND)
    command: str | None = None

    def __post_init__(self) -> None:
        if self.command is not None and self.category is None:
            object.__setattr__(self, 'category', self.command)


class PeerBus:
    def __init__(self) -> None:
        self._messages: list[PeerMessage] = []
        self._subscriptions: dict[str, list[str]] = {}

    def publish(self, message: PeerMessage) -> None:
        self._messages.append(message)

    def read_telemetry(
        self,
        agent_id: str,
        category: TelemetryCategory | None = None,
    ) -> list[PeerMessage]:
        results = [
            m
            for m in self._messages
            if m.message_type == MessageType.TELEMETRY
            and (category is None or m.category == category.value)
        ]
        return results

    def read_negotiations(
        self,
        agent_id: str,
        negotiation_type: NegotiationType | None = None,
    ) -> list[NegotiationMessage]:
        results: list[NegotiationMessage] = []
        for m in self._messages:
            if m.message_type == MessageType.NEGOTIATION and m.recipient == agent_id:
                if isinstance(m, NegotiationMessage):
                    if negotiation_type is None or m.negotiation_type == negotiation_type:
                        results.append(m)
        return results

    def read_commands(self, agent_id: str) -> list[CommandMessage]:
        results: list[CommandMessage] = []
        for m in self._messages:
            if m.message_type == MessageType.COMMAND and m.recipient == agent_id:
                if isinstance(m, CommandMessage):
                    results.append(m)
        return results

    def get_all_messages(self) -> list[PeerMessage]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def subscribe(self, agent_id: str, channel: str) -> None:
        if agent_id not in self._subscriptions:
            self._subscriptions[agent_id] = []
        if channel not in self._subscriptions[agent_id]:
            self._subscriptions[agent_id].append(channel)


GLOBAL_PEER_BUS: PeerBus = PeerBus()


def get_peer_bus() -> PeerBus:
    return GLOBAL_PEER_BUS


def reset_peer_bus() -> None:
    GLOBAL_PEER_BUS.clear()
    GLOBAL_PEER_BUS._subscriptions.clear()
