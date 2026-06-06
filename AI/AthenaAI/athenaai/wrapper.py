"""Headless OpenCode wrapper/runtime for AthenaAI.

This module provides a Python API to run OpenCode in headless mode,
loading configuration from ./AthenaAI/opencode and interfacing with
agents through the simulation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from athenaai.agents import get_agent_config, get_all_agent_configs
from athenaai.config import (
    AGENT_COORDINATOR,
    AGENT_ORACLE,
    DEFAULT_DAY_AHEAD_HOURS,
    DEFAULT_SIMULATION_STEP_MINUTES,
    KIMI_K2_6_MODEL,
    OPENCODE_GO_API_KEY_ENV_VAR,
    REGIONAL_AGENTS,
    get_opencode_api_key,
    get_opencode_api_url,
    get_opencode_config_path,
)
from athenaai.model_client import ModelClientError, OpenCodeModelClient
from athenaai.peer_bus import PeerBus, PeerMessage, get_peer_bus


class SimulationClock:
    def __init__(self, start_time: datetime | None = None):
        self._current_time = start_time or datetime(2026, 1, 1, 0, 0, 0)
        self._step_minutes = DEFAULT_SIMULATION_STEP_MINUTES
        self._step_count = 0

    @property
    def current_time(self) -> datetime:
        return self._current_time

    @property
    def step_count(self) -> int:
        return self._step_count

    def step(self) -> None:
        self._current_time += timedelta(minutes=self._step_minutes)
        self._step_count += 1

    def set_time(self, new_time: datetime) -> None:
        self._current_time = new_time

    def format_time_for_agent(self) -> str:
        return self._current_time.strftime("%Y-%m-%d %H:%M:%S")


class AgentContext:
    def __init__(
        self,
        agent_id: str,
        model: str,
        system_prompt: str,
        simulated_time: datetime,
    ):
        self.agent_id = agent_id
        self.model = model
        self.system_prompt = system_prompt
        self.simulated_time = simulated_time

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "simulated_time": self.simulated_time.isoformat(),
            "time_formatted": self.simulated_time.strftime("%Y-%m-%d %H:%M:%S"),
        }


class HeadlessOpenCodeWrapper:
    def __init__(
        self,
        config_path: Path | None = None,
        simulation_start: datetime | None = None,
        model_overrides: Mapping[str, str] | None = None,
    ):
        if config_path is None:
            config_path = get_opencode_config_path()
        self._config_path = config_path
        self._clock = SimulationClock(simulation_start)
        self._peer_bus = get_peer_bus()
        self._opencode_api_key = get_opencode_api_key()
        self._model_overrides = dict(model_overrides or {})
        self._initialized = True

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def simulation_clock(self) -> SimulationClock:
        return self._clock

    @property
    def peer_bus(self) -> PeerBus:
        return self._peer_bus

    def get_agent_context(self, agent_id: str) -> AgentContext:
        config = get_agent_config(agent_id, self._model_overrides)
        return AgentContext(
            agent_id=config.agent_id,
            model=config.model,
            system_prompt=config.system_prompt,
            simulated_time=self._clock.current_time,
        )

    def get_all_agent_contexts(self) -> list[AgentContext]:
        return [self.get_agent_context(aid) for aid in [AGENT_COORDINATOR] + REGIONAL_AGENTS + [AGENT_ORACLE]]

    def step_simulation(self) -> None:
        self._clock.step()

    def get_simulated_time(self) -> datetime:
        return self._clock.current_time

    def get_simulated_time_formatted(self) -> str:
        return self._clock.format_time_for_agent()

    def check_api_key_configured(self) -> bool:
        return self._opencode_api_key is not None

    def get_env_status(self) -> dict[str, Any]:
        return {
            "OPENCODE_GO_API_KEY_configured": self.check_api_key_configured(),
            "config_path": str(self._config_path),
            "simulation_time": self.get_simulated_time_formatted(),
            "step_count": self._clock.step_count,
        }


def create_wrapper(
    config_path: Path | None = None,
    simulation_start: datetime | None = None,
    model_overrides: Mapping[str, str] | None = None,
) -> HeadlessOpenCodeWrapper:
    return HeadlessOpenCodeWrapper(config_path, simulation_start, model_overrides)


def run_day_ahead_planning(wrapper: HeadlessOpenCodeWrapper) -> dict[str, Any]:
    """Execute day-ahead planning using the model client.

    Calls the coordinator agent through the LLM to produce a 24-hour
    generation schedule based on forecasts and current grid state.

    Args:
        wrapper: HeadlessOpenCodeWrapper instance with simulation context.

    Returns:
        Dictionary containing:
        - status: planning status string
        - simulated_time: current simulation time
        - forecast_horizon_h: forecast horizon in hours
        - schedule: 24-hour schedule from coordinator (if successful)
        - reasoning: coordinator's rationale
        - error: error message (if failed)
    """
    try:
        model_client = OpenCodeModelClient(
            api_key=wrapper._opencode_api_key,
            api_url=get_opencode_api_url(),
        )
    except Exception as exc:
        return {
            "status": "client_init_failed",
            "error": str(exc),
            "simulated_time": wrapper.get_simulated_time_formatted(),
            "forecast_horizon_h": DEFAULT_DAY_AHEAD_HOURS,
        }

    coordinator_config = get_agent_config(AGENT_COORDINATOR, wrapper._model_overrides)
    simulated_time = wrapper.get_simulated_time()
    simulated_time_str = simulated_time.strftime("%Y-%m-%d %H:%M:%S")

    # Build day-ahead planning prompt with 24-hour forecast context
    planning_prompt = f"""You are the National Coordinator Agent for Czech Republic power grid (ČEPS).

Current simulation time: {simulated_time_str}
Planning horizon: {DEFAULT_DAY_AHEAD_HOURS} hours (24 hourly intervals starting from current time)

## Your Task: Day-Ahead Schedule Generation

Generate a 24-hour active power dispatch schedule for all controllable generators in the Czech grid.
The schedule must:
1. Meet predicted load for each hour
2. Satisfy N-1 security constraints
3. Respect generator technical limits (min/max generation, ramp rates)
4. Optimize for economic dispatch while maintaining reliability

## Output Format

Return ONLY valid JSON with this exact schema:
{{
  "reasoning": "Brief explanation of scheduling approach and key decisions",
  "schedule": {{
    "hourly_generation": [
      {{
        "hour": 0,
        "generator_dispatch": [
          {{"generator_id": "...", "generation_mw": 0.0}}
        ]
      }}
    ],
    "total_cost_eur": 0.0,
    "n1_passed": true
  }}
}}

Use null or empty arrays if no action is needed for a specific hour.
The simulator will validate the schedule against N-1 security constraints.
Prefer conservative schedules over aggressive optimization when forecasts are uncertain.

Current simulation context time: {simulated_time_str}
"""

    raw_response = None
    try:
        raw_response = model_client.complete_json(
            model=coordinator_config.model,
            system_prompt=coordinator_config.system_prompt,
            user_prompt=planning_prompt,
            timeout_s=120.0,
        )

        parsed = json.loads(raw_response)

        return {
            "status": "day_ahead_planning_completed",
            "simulated_time": simulated_time_str,
            "forecast_horizon_h": DEFAULT_DAY_AHEAD_HOURS,
            "schedule": parsed.get("schedule", {}),
            "reasoning": parsed.get("reasoning", ""),
            "model_used": coordinator_config.model,
        }

    except ModelClientError as exc:
        return {
            "status": "model_client_error",
            "error": str(exc),
            "simulated_time": simulated_time_str,
            "forecast_horizon_h": DEFAULT_DAY_AHEAD_HOURS,
        }
    except json.JSONDecodeError as exc:
        return {
            "status": "parse_error",
            "error": f"Failed to parse model response: {str(exc)[:200]}",
            "simulated_time": simulated_time_str,
            "forecast_horizon_h": DEFAULT_DAY_AHEAD_HOURS,
            "raw_response": raw_response[:500] if raw_response else "",
        }
    except Exception as exc:
        return {
            "status": "unexpected_error",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "simulated_time": simulated_time_str,
            "forecast_horizon_h": DEFAULT_DAY_AHEAD_HOURS,
        }
