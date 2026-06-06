"""Test timestamp propagation through the system."""

from datetime import datetime, timedelta

from athenaai.wrapper import SimulationClock, HeadlessOpenCodeWrapper, create_wrapper
from athenaai.peer_bus import PeerMessage, TelemetryMessage, PeerBus, get_peer_bus, reset_peer_bus, TelemetryCategory
from athenaai.agents import get_agent_config
from athenaai.tools.physics import ac_load_flow


class TestTimestampPropagation:
    def test_clock_time_increments_correctly(self):
        clock = SimulationClock(datetime(2026, 1, 1, 0, 0, 0))
        clock.step()
        assert clock.current_time == datetime(2026, 1, 1, 0, 15, 0)
        clock.step()
        assert clock.current_time == datetime(2026, 1, 1, 0, 30, 0)

    def test_wrapper_informs_agents_of_simulated_time(self):
        wrapper = create_wrapper()
        ctx = wrapper.get_agent_context("coordinator")
        assert ctx.simulated_time is not None
        assert ctx.simulated_time.year == 2026

    def test_wrapper_step_updates_agent_context_time(self):
        wrapper = create_wrapper()
        initial_ctx = wrapper.get_agent_context("coordinator")
        initial_time = initial_ctx.simulated_time
        wrapper.step_simulation()
        updated_ctx = wrapper.get_agent_context("coordinator")
        assert updated_ctx.simulated_time > initial_time

    def test_telemetry_message_carries_simulated_time(self):
        sim_time = datetime(2026, 1, 1, 12, 0, 0)
        msg = TelemetryMessage(
            sender="coordinator",
            category=TelemetryCategory.LOAD_VS_SCHEDULE,
            payload={"load_mw": 1000},
            simulated_time=sim_time,
        )
        assert msg.simulated_time == sim_time
        data = msg.to_dict()
        assert data["simulated_time"] == sim_time.isoformat()

    def test_peer_message_from_dict_preserves_simulated_time(self):
        data = {
            "id": "test-id",
            "timestamp": "2026-01-01T00:00:00",
            "sender": "coordinator",
            "message_type": "telemetry",
            "category": "load_vs_schedule",
            "payload": {},
            "simulated_time": "2026-01-01T12:00:00",
        }
        msg = PeerMessage.from_dict(data)
        assert msg.simulated_time == datetime(2026, 1, 1, 12, 0, 0)

    def test_tools_receive_simulated_time(self):
        sim_time = datetime(2026, 6, 15, 8, 30, 0)
        result = ac_load_flow({"buses": []}, sim_time)
        assert result["simulated_time"] == sim_time.isoformat()

    def test_agent_context_formatted_time_includes_date_and_time(self):
        wrapper = create_wrapper()
        ctx = wrapper.get_agent_context("coordinator")
        ctx_dict = ctx.to_dict()
        assert "time_formatted" in ctx_dict
        assert "2026" in ctx_dict["time_formatted"]

    def test_wrapper_env_status_includes_simulation_time(self):
        wrapper = create_wrapper()
        status = wrapper.get_env_status()
        assert "simulation_time" in status
        assert "2026" in status["simulation_time"]

    def test_multiple_steps_maintain_increasing_time(self):
        wrapper = create_wrapper()
        times = []
        for _ in range(10):
            times.append(wrapper.get_simulated_time())
            wrapper.step_simulation()
        for i in range(len(times) - 1):
            assert times[i] < times[i + 1]


class TestSimulatedTimeInAgents:
    def test_all_agents_receive_time_in_context(self):
        wrapper = create_wrapper()
        for agent_id in ["coordinator", "bohemia-west", "bohemia-east", "moravia", "silesia"]:
            ctx = wrapper.get_agent_context(agent_id)
            assert ctx.simulated_time is not None

    def test_oracle_context_also_has_time(self):
        wrapper = create_wrapper()
        ctx = wrapper.get_agent_context("oracle")
        assert ctx.simulated_time is not None
