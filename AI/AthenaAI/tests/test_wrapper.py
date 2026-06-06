"""Test headless wrapper module."""

import os
from datetime import datetime
from pathlib import Path

from athenaai.wrapper import (
    HeadlessOpenCodeWrapper,
    SimulationClock,
    AgentContext,
    create_wrapper,
    run_day_ahead_planning,
)
from athenaai.config import (
    AGENT_COORDINATOR,
    AGENT_BOHEMIA_WEST,
    AGENT_ORACLE,
    KIMI_K2_6_MODEL,
    OPENCODE_GO_API_KEY_ENV_VAR,
)


class TestSimulationClock:
    def test_clock_starts_at_default_time(self):
        clock = SimulationClock()
        assert clock.current_time.year == 2026
        assert clock.current_time.month == 1
        assert clock.current_time.day == 1

    def test_clock_starts_at_custom_time(self):
        clock = SimulationClock(datetime(2026, 6, 15, 12, 0, 0))
        assert clock.current_time == datetime(2026, 6, 15, 12, 0, 0)

    def test_clock_step_increments_time(self):
        clock = SimulationClock(datetime(2026, 1, 1, 0, 0, 0))
        initial_count = clock.step_count
        clock.step()
        assert clock.step_count == initial_count + 1
        assert clock.current_time.minute == 15

    def test_clock_format_time_for_agent(self):
        clock = SimulationClock(datetime(2026, 1, 1, 0, 0, 0))
        formatted = clock.format_time_for_agent()
        assert "2026-01-01" in formatted
        assert "00:00:00" in formatted

    def test_clock_set_time(self):
        clock = SimulationClock(datetime(2026, 1, 1, 0, 0, 0))
        clock.set_time(datetime(2026, 12, 31, 23, 45, 0))
        assert clock.current_time == datetime(2026, 12, 31, 23, 45, 0)


class TestAgentContext:
    def test_agent_context_creation(self):
        ctx = AgentContext(
            agent_id="coordinator",
            model="kimi-k2.6",
            system_prompt="Test prompt",
            simulated_time=datetime(2026, 1, 1, 0, 0, 0),
        )
        assert ctx.agent_id == "coordinator"
        assert ctx.model == "kimi-k2.6"

    def test_agent_context_to_dict(self):
        ctx = AgentContext(
            agent_id="coordinator",
            model="kimi-k2.6",
            system_prompt="Test prompt",
            simulated_time=datetime(2026, 1, 1, 0, 0, 0),
        )
        data = ctx.to_dict()
        assert data["agent_id"] == "coordinator"
        assert data["model"] == "kimi-k2.6"
        assert "simulated_time" in data
        assert "time_formatted" in data


class TestHeadlessOpenCodeWrapper:
    def test_wrapper_loads_correct_config_path(self):
        wrapper = create_wrapper()
        assert wrapper.config_path.name == "opencode.jsonc"
        assert wrapper.config_path.parent.name == "opencode"

    def test_wrapper_uses_custom_config_path(self, tmp_path):
        custom_config = tmp_path / "opencode" / "opencode.jsonc"
        custom_config.parent.mkdir()
        custom_config.write_text('{"$schema": "https://opencode.ai/config.json"}')
        wrapper = create_wrapper(config_path=custom_config)
        assert wrapper.config_path == custom_config

    def test_wrapper_simulation_clock(self):
        wrapper = create_wrapper()
        assert hasattr(wrapper, "simulation_clock")
        assert isinstance(wrapper.simulation_clock, SimulationClock)

    def test_wrapper_peer_bus(self):
        wrapper = create_wrapper()
        assert hasattr(wrapper, "peer_bus")

    def test_get_agent_context(self):
        wrapper = create_wrapper()
        ctx = wrapper.get_agent_context(AGENT_COORDINATOR)
        assert ctx.agent_id == AGENT_COORDINATOR
        assert ctx.model == KIMI_K2_6_MODEL

    def test_wrapper_uses_model_overrides(self):
        wrapper = create_wrapper(model_overrides={"all": "test/model"})
        ctx = wrapper.get_agent_context(AGENT_COORDINATOR)
        assert ctx.model == "test/model"

    def test_get_all_agent_contexts(self):
        wrapper = create_wrapper()
        contexts = wrapper.get_all_agent_contexts()
        assert len(contexts) == 6
        agent_ids = [c.agent_id for c in contexts]
        assert AGENT_COORDINATOR in agent_ids
        assert AGENT_BOHEMIA_WEST in agent_ids
        assert AGENT_ORACLE in agent_ids

    def test_step_simulation(self):
        wrapper = create_wrapper()
        initial_time = wrapper.get_simulated_time()
        wrapper.step_simulation()
        new_time = wrapper.get_simulated_time()
        assert new_time > initial_time

    def test_get_simulated_time_formatted(self):
        wrapper = create_wrapper()
        formatted = wrapper.get_simulated_time_formatted()
        assert "2026-01-01" in formatted

    def test_api_key_not_configured_when_env_missing(self):
        original = os.environ.pop(OPENCODE_GO_API_KEY_ENV_VAR, None)
        try:
            wrapper = create_wrapper()
            assert wrapper.check_api_key_configured() is False
        finally:
            if original is not None:
                os.environ[OPENCODE_GO_API_KEY_ENV_VAR] = original

    def test_api_key_configured_when_env_set(self):
        os.environ[OPENCODE_GO_API_KEY_ENV_VAR] = "test-key"
        try:
            wrapper = create_wrapper()
            assert wrapper.check_api_key_configured() is True
        finally:
            os.environ.pop(OPENCODE_GO_API_KEY_ENV_VAR, None)

    def test_env_status_includes_config_path(self):
        wrapper = create_wrapper()
        status = wrapper.get_env_status()
        assert "config_path" in status
        assert "opencode.jsonc" in status["config_path"]

    def test_env_status_includes_simulation_time(self):
        wrapper = create_wrapper()
        status = wrapper.get_env_status()
        assert "simulation_time" in status


class TestRunDayAheadPlanning:
    def test_run_day_ahead_planning_returns_status(self):
        wrapper = create_wrapper()
        result = run_day_ahead_planning(wrapper)
        assert result["status"] == "day_ahead_planning_initiated"
        assert "simulated_time" in result
        assert result["forecast_horizon_h"] == 24
