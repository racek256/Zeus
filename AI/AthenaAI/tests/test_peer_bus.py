"""Test peer_bus module."""

from datetime import datetime

from athenaai.peer_bus import (
    PeerBus,
    PeerMessage,
    MessageType,
    TelemetryCategory,
    NegotiationType,
    TelemetryMessage,
    NegotiationMessage,
    CommandMessage,
    get_peer_bus,
    reset_peer_bus,
)


class TestPeerMessage:
    def test_peer_message_creation(self):
        msg = PeerMessage(
            sender="coordinator",
            message_type=MessageType.TELEMETRY,
            payload={"load_mw": 1000},
        )
        assert msg.sender == "coordinator"
        assert msg.message_type == MessageType.TELEMETRY
        assert msg.payload["load_mw"] == 1000
        assert msg.id is not None

    def test_peer_message_to_dict(self):
        msg = PeerMessage(
            sender="coordinator",
            message_type=MessageType.TELEMETRY,
            payload={"key": "value"},
        )
        data = msg.to_dict()
        assert data["sender"] == "coordinator"
        assert data["message_type"] == "telemetry"
        assert data["payload"]["key"] == "value"

    def test_peer_message_from_dict(self):
        data = {
            "id": "test-id",
            "timestamp": "2026-01-01T00:00:00",
            "sender": "bohemia-west",
            "recipient": None,
            "message_type": "telemetry",
            "category": "load_vs_schedule",
            "payload": {"load_mw": 500},
            "simulated_time": "2026-01-01T00:00:00",
        }
        msg = PeerMessage.from_dict(data)
        assert msg.sender == "bohemia-west"
        assert msg.message_type == MessageType.TELEMETRY


class TestTelemetryMessage:
    def test_telemetry_message_creation(self):
        msg = TelemetryMessage(
            sender="coordinator",
            category=TelemetryCategory.LOAD_VS_SCHEDULE,
            payload={"actual_mw": 1000, "scheduled_mw": 950},
            simulated_time=datetime(2026, 1, 1, 0, 0, 0),
        )
        assert msg.sender == "coordinator"
        assert msg.category == "load_vs_schedule"
        assert msg.message_type == MessageType.TELEMETRY
        assert msg.simulated_time == datetime(2026, 1, 1, 0, 0, 0)


class TestNegotiationMessage:
    def test_negotiation_message_creation(self):
        msg = NegotiationMessage(
            sender="bohemia-west",
            recipient="coordinator",
            negotiation_type=NegotiationType.TRANSFER_REQUEST,
            payload={"mw": 100, "price_eur": 50},
            simulated_time=datetime(2026, 1, 1, 0, 0, 0),
        )
        assert msg.sender == "bohemia-west"
        assert msg.recipient == "coordinator"
        assert msg.negotiation_type == NegotiationType.TRANSFER_REQUEST
        assert msg.message_type == MessageType.NEGOTIATION


class TestCommandMessage:
    def test_command_message_creation(self):
        msg = CommandMessage(
            sender="coordinator",
            recipient="bohemia-east",
            command="redispatch",
            payload={"mw": 50, "direction": "up"},
            simulated_time=datetime(2026, 1, 1, 0, 0, 0),
        )
        assert msg.sender == "coordinator"
        assert msg.recipient == "bohemia-east"
        assert msg.category == "redispatch"
        assert msg.message_type == MessageType.COMMAND


class TestPeerBus:
    def test_publish_and_read_telemetry(self):
        reset_peer_bus()
        bus = get_peer_bus()
        msg = TelemetryMessage(
            sender="coordinator",
            category=TelemetryCategory.LOAD_VS_SCHEDULE,
            payload={"load_mw": 1000},
        )
        bus.publish(msg)
        results = bus.read_telemetry("bohemia-west")
        assert len(results) >= 1

    def test_read_telemetry_by_category(self):
        reset_peer_bus()
        bus = get_peer_bus()
        bus.publish(TelemetryMessage(
            sender="coordinator",
            category=TelemetryCategory.LOAD_VS_SCHEDULE,
            payload={"data": "1"},
        ))
        bus.publish(TelemetryMessage(
            sender="coordinator",
            category=TelemetryCategory.RESERVE_STATUS,
            payload={"data": "2"},
        ))
        results = bus.read_telemetry("bohemia-west", TelemetryCategory.LOAD_VS_SCHEDULE)
        assert all(r.category == "load_vs_schedule" for r in results)

    def test_read_negotiations(self):
        reset_peer_bus()
        bus = get_peer_bus()
        bus.publish(NegotiationMessage(
            sender="bohemia-west",
            recipient="coordinator",
            negotiation_type=NegotiationType.TRANSFER_REQUEST,
            payload={},
        ))
        results = bus.read_negotiations("coordinator")
        assert len(results) >= 1

    def test_read_commands(self):
        reset_peer_bus()
        bus = get_peer_bus()
        bus.publish(CommandMessage(
            sender="coordinator",
            recipient="bohemia-east",
            command="redispatch",
            payload={},
        ))
        results = bus.read_commands("bohemia-east")
        assert len(results) >= 1

    def test_get_all_messages(self):
        reset_peer_bus()
        bus = get_peer_bus()
        bus.publish(TelemetryMessage(
            sender="coordinator",
            category=TelemetryCategory.ACTIVE_ALARMS,
            payload={"alarms": []},
        ))
        all_msgs = bus.get_all_messages()
        assert len(all_msgs) >= 1

    def test_clear(self):
        reset_peer_bus()
        bus = get_peer_bus()
        bus.publish(TelemetryMessage(
            sender="coordinator",
            category=TelemetryCategory.LOAD_VS_SCHEDULE,
            payload={},
        ))
        bus.clear()
        assert len(bus.get_all_messages()) == 0


class TestMessageTypeEnum:
    def test_message_types_defined(self):
        assert MessageType.TELEMETRY.value == "telemetry"
        assert MessageType.NEGOTIATION.value == "negotiation"
        assert MessageType.COMMAND.value == "command"
        assert MessageType.RESPONSE.value == "response"


class TestNegotiationTypeEnum:
    def test_negotiation_types_defined(self):
        assert NegotiationType.TRANSFER_REQUEST.value == "transfer_request"
        assert NegotiationType.REDISPATCH_ASK.value == "redispatch_ask"
        assert NegotiationType.TRANSFER_ACCEPT.value == "transfer_accept"
        assert NegotiationType.TRANSFER_REJECT.value == "transfer_reject"
