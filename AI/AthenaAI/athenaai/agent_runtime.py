"""Agent runtime - coordinates agents, routes tool calls, manages simulation."""

from __future__ import annotations

import asyncio
import os
import copy
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from athenaai.agents import get_all_agent_configs, get_agent_config
from athenaai.audit.logger import AuditLogger
from athenaai.config import (
    AGENT_COORDINATOR,
    AGENT_ORACLE,
    ALL_AGENTS,
    REGIONAL_AGENTS,
    get_opencode_api_key,
    get_opencode_config_path,
)
from athenaai.model_client import ModelActionClient, ModelClientError, OpenCodeModelClient
from athenaai.peer_bus import PeerBus, get_peer_bus
from athenaai.physics.engine import PhysicsStatus, run_ac_load_flow
from athenaai.physics.n1 import n1_security_scan
from athenaai.schema import (
    ActionBundle,
    GeneratorSetpointChange,
    InterconnectFlowAdjustment,
    LoadSheddingFlag,
    ObservationBundle,
)
from athenaai.schema import RedispatchRequest
from athenaai.simulator import GridSimulator
from athenaai.trace import trace, trace_scope


@dataclass
class AgentResponse:
    agent_id: str
    action: ActionBundle | None
    reasoning: str
    timestamp: datetime


@dataclass
class ToolCall:
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class AgentDecision:
    agent_id: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    action: ActionBundle | None = None
    reasoning: str = ""
    timestamp: datetime | None = None


class AgentRuntime:
    def __init__(
        self,
        simulator: GridSimulator,
        opencode_config_path: Path | None = None,
        audit_logger: AuditLogger | None = None,
        model_overrides: Mapping[str, str] | None = None,
        model_client: ModelActionClient | None = None,
    ) -> None:
        self._simulator = simulator
        self._opencode_config_path = opencode_config_path or get_opencode_config_path()
        self._audit_logger = audit_logger or AuditLogger()
        self._peer_bus = get_peer_bus()
        self._opencode_api_key = get_opencode_api_key()
        self._model_client = model_client or OpenCodeModelClient()
        self._model_overrides = dict(model_overrides or {})
        self._agent_configs = {
            config.agent_id: config
            for config in get_all_agent_configs(self._model_overrides)
        }
        self._coordinator: AgentDecision | None = None
        self._regional_agents: dict[str, AgentDecision] = {}
        self._oracle: AgentDecision | None = None

    @property
    def simulator(self) -> GridSimulator:
        return self._simulator

    @property
    def audit_logger(self) -> AuditLogger:
        return self._audit_logger

    def get_opencode_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self._opencode_api_key:
            env["OPENCODE_GO_API_KEY"] = self._opencode_api_key
        return env

    def get_agent_model(self, agent_id: str) -> str:
        return self._agent_configs[agent_id].model

    @staticmethod
    def _agent_region(agent_id: str) -> str:
        if agent_id in REGIONAL_AGENTS:
            return agent_id
        return "national"

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if is_dataclass(value) and not isinstance(value, type):
            return AgentRuntime._jsonable(asdict(value))
        if isinstance(value, dict):
            return {str(key): AgentRuntime._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [AgentRuntime._jsonable(item) for item in value]
        return value

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("model response did not contain a JSON object")
        decoded = json.loads(text[start:end + 1])
        if not isinstance(decoded, dict):
            raise ValueError("model response JSON root must be an object")
        return decoded

    def _build_model_control_prompt(
        self,
        agent_id: str,
        observation: ObservationBundle,
        n1_context: dict[str, Any],
    ) -> str:
        state_generators = {
            str(gen.get("generator_id", gen.get("name", ""))): gen
            for gen in self._simulator.current_network_state.get("generators", [])
        }
        observation_context = {
            "hour_index": observation.hour_index,
            "timestamp": observation.timestamp.isoformat(),
            "totals": {
                "generation_mw": observation.scada.total_generation_mw,
                "load_mw": observation.scada.total_load_mw,
                "imbalance_mw": observation.scada.total_load_mw - observation.scada.total_generation_mw,
            },
            "constraints": self._jsonable(observation.network_constraints),
            "buses": self._jsonable(observation.scada.buses),
            "branches": self._jsonable(observation.scada.branches),
            "generators": [
                {
                    **self._jsonable(generator),
                    "min_p_mw": float(state_generators.get(generator.generator_id, {}).get("min_p_mw", 0.0)),
                    "max_p_mw": float(state_generators.get(generator.generator_id, {}).get("max_p_mw", generator.setpoint_mw)),
                }
                for generator in observation.scada.generators
            ],
            "loads": self._jsonable(observation.scada.loads),
            "n1_context": n1_context,
        }
        return (
            "You are controlling the AthenaAI grid simulator as the national coordinator.\n"
            "Return ONLY valid JSON. Do not include markdown.\n"
            "Your JSON schema is:\n"
            "{\n"
            "  \"reasoning\": \"short operator-visible rationale\",\n"
            "  \"action\": {\n"
            "    \"generator_setpoint_changes\": [{\"generator_id\": \"...\", \"new_setpoint_mw\": 0.0}],\n"
            "    \"redispatch_requests\": [{\"generator_id\": \"...\", \"region\": \"national\", \"upward_mw\": 0.0, \"downward_mw\": 0.0, \"reason\": \"...\"}],\n"
            "    \"load_shedding_flags\": [{\"load_id\": \"...\", \"region\": \"national\", \"shed_mw\": 0.0, \"priority\": 1}],\n"
            "    \"interconnect_flow_adjustments\": [{\"border\": \"DE\", \"target_flow_mw\": 0.0, \"current_flow_mw\": 0.0}]\n"
            "  }\n"
            "}\n"
            "Use empty arrays for no action type. Use null action only if no control is needed.\n"
            "The simulator will dry-run and reject unsafe actions. Prefer no action over invalid control.\n"
            "Current observation and tool context:\n"
            f"{json.dumps(observation_context, sort_keys=True)}"
        )

    def _build_n1_context(self, observation: ObservationBundle) -> dict[str, Any]:
        state = self._simulator.current_network_state
        if not state:
            return {"available": False, "message": "no current network state"}
        result = n1_security_scan(
            state,
            simulated_time=observation.timestamp,
            max_loading_percent=observation.network_constraints.max_branch_loading_percent,
            min_voltage_pu=observation.network_constraints.min_voltage_pu,
            max_voltage_pu=observation.network_constraints.max_voltage_pu,
            stop_on_first_violation=True,
        )
        failed = result.contingencies[0] if result.contingencies and not result.passed else None
        return {
            "available": True,
            "passed": result.passed,
            "status": result.status.value,
            "message": result.message,
            "first_failed_contingency": self._jsonable(failed) if failed is not None else None,
        }

    async def _build_n1_context_async(self, observation: ObservationBundle) -> dict[str, Any]:
        pool = self._simulator.physics_pool
        if pool is not None and pool.is_available and pool.is_process_pool:
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(
                    pool.executor,
                    self._build_n1_context,
                    observation,
                )
            except Exception:
                trace("agent_runtime._build_n1_context_async.pool_failed")
        return await asyncio.to_thread(self._build_n1_context, observation)

    async def _run_in_pool_or_thread(self, func: Any, *args: Any) -> Any:
        pool = self._simulator.physics_pool
        if pool is not None and pool.is_available and pool.is_process_pool:
            loop = asyncio.get_running_loop()
            try:
                return await loop.run_in_executor(pool.executor, func, *args)
            except Exception:
                trace("agent_runtime._run_in_pool_or_thread.pool_failed")
        return await asyncio.to_thread(func, *args)

    def _parse_model_action(
        self,
        agent_id: str,
        observation: ObservationBundle,
        raw_text: str,
    ) -> tuple[ActionBundle | None, str]:
        decoded = self._extract_json_object(raw_text)
        reasoning = str(decoded.get("reasoning") or decoded.get("rationale") or "Model returned no rationale.")
        action_data = decoded.get("action", decoded)
        if action_data is None:
            return None, reasoning
        if not isinstance(action_data, dict):
            raise ValueError("model action must be an object or null")

        generator_bounds = {
            str(gen.get("generator_id", gen.get("name", ""))): gen
            for gen in self._simulator.current_network_state.get("generators", [])
        }
        setpoint_changes: list[GeneratorSetpointChange] = []
        for item in action_data.get("generator_setpoint_changes", []) or []:
            if not isinstance(item, dict):
                continue
            generator_id = str(item.get("generator_id", ""))
            if not generator_id:
                continue
            if generator_id not in generator_bounds:
                continue
            requested = float(item.get("new_setpoint_mw", 0.0))
            bounds = generator_bounds.get(generator_id, {})
            min_mw = float(bounds.get("min_p_mw", 0.0))
            max_mw = float(bounds.get("max_p_mw", max(requested, 0.0)))
            setpoint_changes.append(
                GeneratorSetpointChange(
                    generator_id=generator_id,
                    new_setpoint_mw=max(min_mw, min(max_mw, requested)),
                    ramp_rate_mw_per_min=(
                        float(item["ramp_rate_mw_per_min"])
                        if item.get("ramp_rate_mw_per_min") is not None
                        else None
                    ),
                )
            )

        redispatch_requests: list[RedispatchRequest] = []
        for item in action_data.get("redispatch_requests", []) or []:
            if not isinstance(item, dict):
                continue
            generator_id = str(item.get("generator_id", ""))
            if not generator_id:
                continue
            redispatch_requests.append(
                RedispatchRequest(
                    generator_id=generator_id,
                    region=str(item.get("region", self._agent_region(agent_id))),
                    upward_mw=max(0.0, float(item.get("upward_mw", 0.0))),
                    downward_mw=max(0.0, float(item.get("downward_mw", 0.0))),
                    reason=str(item.get("reason", reasoning)),
                )
            )

        shedding_flags: list[LoadSheddingFlag] = []
        for item in action_data.get("load_shedding_flags", []) or []:
            if not isinstance(item, dict):
                continue
            load_id = str(item.get("load_id", ""))
            if not load_id:
                continue
            shedding_flags.append(
                LoadSheddingFlag(
                    load_id=load_id,
                    region=str(item.get("region", self._agent_region(agent_id))),
                    shed_mw=max(0.0, float(item.get("shed_mw", 0.0))),
                    priority=int(item.get("priority", 1)),
                )
            )

        interconnect_adjustments: list[InterconnectFlowAdjustment] = []
        for item in action_data.get("interconnect_flow_adjustments", []) or []:
            if not isinstance(item, dict):
                continue
            border = str(item.get("border", ""))
            if not border:
                continue
            interconnect_adjustments.append(
                InterconnectFlowAdjustment(
                    border=border,
                    target_flow_mw=float(item.get("target_flow_mw", 0.0)),
                    current_flow_mw=float(item.get("current_flow_mw", 0.0)),
                )
            )

        action = ActionBundle(
            timestamp=observation.timestamp,
            agent_id=agent_id,
            generator_setpoint_changes=tuple(setpoint_changes),
            redispatch_requests=tuple(redispatch_requests),
            load_shedding_flags=tuple(shedding_flags),
            interconnect_flow_adjustments=tuple(interconnect_adjustments),
        )
        if action.is_empty():
            return None, reasoning
        return action, reasoning

    def _build_model_control_action(
        self,
        agent_id: str,
        observation: ObservationBundle,
    ) -> tuple[ActionBundle | None, str] | None:
        """Sync wrapper around the async model control implementation."""
        return asyncio.run(
            self._build_model_control_action_async(agent_id, observation)
        )

    async def _build_model_control_action_async(
        self,
        agent_id: str,
        observation: ObservationBundle,
    ) -> tuple[ActionBundle | None, str] | None:
        n1_context = await self._build_n1_context_async(observation)
        user_prompt = self._build_model_control_prompt(agent_id, observation, n1_context)
        model = self.get_agent_model(agent_id)

        try:
            complete_json_async = getattr(
                self._model_client, "complete_json_async", None
            )
            if complete_json_async is not None:
                raw_response = await asyncio.wait_for(
                    complete_json_async(
                        model=model,
                        system_prompt=self._agent_configs[agent_id].system_prompt,
                        user_prompt=user_prompt,
                        timeout_s=60.0,
                    ),
                    timeout=70.0,
                )
            else:
                raw_response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._model_client.complete_json,
                        model=model,
                        system_prompt=self._agent_configs[agent_id].system_prompt,
                        user_prompt=user_prompt,
                        timeout_s=60.0,
                    ),
                    timeout=70.0,
                )
            action, reasoning = self._parse_model_action(agent_id, observation, raw_response)

        except (ModelClientError, ValueError, json.JSONDecodeError, asyncio.TimeoutError) as exc:
            self._audit_logger.log(
                agent_id=agent_id,
                action="model_control",
                result="fallback_deterministic",
                metadata={"error_type": type(exc).__name__, "error": str(exc)[:500]},
            )
            return None

        self._audit_logger.log(
            agent_id=agent_id,
            action="model_control",
            result="action_proposed" if action is not None else "monitoring_only",
            metadata={
                "model": model,
                "reasoning": reasoning,
                "n1_passed": n1_context.get("passed"),
                "action_empty": action is None or action.is_empty(),
            },
        )
        if action is None and n1_context.get("passed") is False:
            return None
        return (
            action,
            f"Model decision for {agent_id} using {model}: {reasoning}",
        )

    def _build_agent_action(
        self,
        agent_id: str,
        observation: ObservationBundle,
    ) -> tuple[ActionBundle | None, str]:
        if agent_id == AGENT_ORACLE:
            return (
                None,
                (
                    f"Oracle diagnostic review using model {self.get_agent_model(agent_id)}: "
                    "read-only agent, no dispatch authority."
                ),
            )

        if agent_id != AGENT_COORDINATOR:
            return (
                None,
                (
                    f"Regional monitoring for {agent_id} using model {self.get_agent_model(agent_id)}: "
                    "national coordinator has binding dispatch authority in this control loop."
                ),
            )

        model_decision = self._build_model_control_action(agent_id, observation)
        if model_decision is not None:
            return model_decision

        return self._build_deterministic_coordinator_action(agent_id, observation)

    async def _build_agent_action_async(
        self,
        agent_id: str,
        observation: ObservationBundle,
    ) -> tuple[ActionBundle | None, str]:
        if agent_id == AGENT_ORACLE:
            return (
                None,
                (
                    f"Oracle diagnostic review using model {self.get_agent_model(agent_id)}: "
                    "read-only agent, no dispatch authority."
                ),
            )

        if agent_id != AGENT_COORDINATOR:
            return (
                None,
                (
                    f"Regional monitoring for {agent_id} using model {self.get_agent_model(agent_id)}: "
                    "national coordinator has binding dispatch authority in this control loop."
                ),
            )

        model_decision = await self._build_model_control_action_async(
            agent_id, observation
        )
        if model_decision is not None:
            return model_decision

        return await asyncio.to_thread(
            self._build_deterministic_coordinator_action, agent_id, observation
        )

    def _build_deterministic_coordinator_action(
        self,
        agent_id: str,
        observation: ObservationBundle,
    ) -> tuple[ActionBundle | None, str]:
        security_action = self._build_security_remedial_action(agent_id, observation)
        if security_action is not None:
            shed_total = sum(flag.shed_mw for flag in security_action.load_shedding_flags)
            shed_loads = ", ".join(
                f"{flag.load_id}:{flag.shed_mw:.1f}MW"
                for flag in security_action.load_shedding_flags
            )
            return (
                security_action,
                (
                    f"Decision for {agent_id} using model {self.get_agent_model(agent_id)}: "
                    f"pre-contingency N-1 check found insecure low-voltage buses; "
                    f"issued targeted load shedding ({shed_loads}) totaling {shed_total:.1f} MW."
                ),
            )

        available_generators = tuple(
            gen for gen in observation.scada.generators if gen.status == "online"
        )
        if not available_generators:
            return (
                None,
                (
                    f"Monitoring for {agent_id} using model {self.get_agent_model(agent_id)}: "
                    "no controllable generators in the current observation."
                ),
            )

        imbalance_mw = observation.scada.total_load_mw - observation.scada.total_generation_mw
        if imbalance_mw == 0:
            return (
                None,
                (
                    f"Monitoring for {agent_id} using model {self.get_agent_model(agent_id)}: "
                    "generation and load are balanced; no redispatch required."
                ),
            )

        state_generators = {
            str(gen.get("generator_id", gen.get("name", ""))): gen
            for gen in self._simulator.current_network_state.get("generators", [])
        }

        if imbalance_mw >= 0:
            selected_generator = max(
                available_generators,
                key=lambda gen: max(
                    0.0,
                    float(state_generators.get(gen.generator_id, {}).get("max_p_mw", gen.setpoint_mw))
                    - gen.setpoint_mw,
                ),
            )
            state_generator = state_generators.get(selected_generator.generator_id, {})
            capability_mw = max(
                0.0,
                float(state_generator.get("max_p_mw", selected_generator.setpoint_mw))
                - selected_generator.setpoint_mw,
            )
            request_mw = round(min(abs(imbalance_mw), capability_mw), 3)
            if request_mw == 0:
                return (
                    None,
                    (
                        f"Monitoring for {agent_id} using model {self.get_agent_model(agent_id)}: "
                        "generation deficit observed but no upward headroom is available."
                    ),
                )
            upward_mw = request_mw
            downward_mw = 0.0
            direction = "upward"
        else:
            selected_generator = max(available_generators, key=lambda gen: gen.setpoint_mw)
            state_generator = state_generators.get(selected_generator.generator_id, {})
            capability_mw = max(
                0.0,
                selected_generator.setpoint_mw
                - float(state_generator.get("min_p_mw", 0.0)),
            )
            request_mw = round(min(abs(imbalance_mw), capability_mw), 3)
            if request_mw == 0:
                return (
                    None,
                    (
                        f"Monitoring for {agent_id} using model {self.get_agent_model(agent_id)}: "
                        "generation surplus observed but no downward headroom is available."
                    ),
                )
            upward_mw = 0.0
            downward_mw = request_mw
            direction = "downward"

        action = ActionBundle(
            timestamp=observation.timestamp,
            agent_id=agent_id,
            redispatch_requests=(
                RedispatchRequest(
                    generator_id=selected_generator.generator_id,
                    region=self._agent_region(agent_id),
                    upward_mw=upward_mw,
                    downward_mw=downward_mw,
                    reason=(
                        f"Deterministic advisory {direction} redispatch request from "
                        f"observed imbalance {imbalance_mw:.3f} MW."
                    ),
                ),
            ),
        )
        return (
            action,
            (
                f"Decision for {agent_id} using model {self.get_agent_model(agent_id)}: "
                f"selected {selected_generator.generator_id}; observed generation "
                f"{observation.scada.total_generation_mw:.3f} MW vs load "
                f"{observation.scada.total_load_mw:.3f} MW; issued {direction} "
                f"redispatch advisory of {request_mw:.3f} MW."
            ),
        )

    def _build_security_remedial_action(
        self,
        agent_id: str,
        observation: ObservationBundle,
    ) -> ActionBundle | None:
        state = self._simulator.current_network_state
        if not state:
            return None

        constraints = self._simulator.constraints
        loads_by_bus: dict[str, list[Any]] = {}
        for load in observation.scada.loads:
            if load.status == "connected" and load.demand_mw > 0:
                loads_by_bus.setdefault(load.bus, []).append(load)

        current_state = state
        accepted_flags: list[LoadSheddingFlag] = []
        for _ in range(8):
            current_n1 = n1_security_scan(
                current_state,
                simulated_time=observation.timestamp,
                max_loading_percent=constraints.max_branch_loading_percent,
                min_voltage_pu=constraints.min_voltage_pu,
                max_voltage_pu=constraints.max_voltage_pu,
                stop_on_first_violation=True,
            )
            if current_n1.passed:
                if not accepted_flags:
                    return None
                return ActionBundle(
                    timestamp=observation.timestamp,
                    agent_id=agent_id,
                    load_shedding_flags=tuple(accepted_flags),
                )

            failed_contingency = next(
                (
                    contingency for contingency in current_n1.contingencies
                    if getattr(contingency.status, "value", contingency.status) != "passed"
                ),
                None,
            )
            if failed_contingency is None:
                return None

            target_buses = self._low_voltage_buses(failed_contingency.violations)
            target_buses = [bus for bus in target_buses if loads_by_bus.get(bus)]

            # When N-1 fails with NON_CONVERGENCE (fallback load flow),
            # shed load from highest-demand buses to restore balance
            if not target_buses and "NON_CONVERGENCE" in failed_contingency.violations:
                target_buses = self._non_convergence_target_buses(loads_by_bus)

            if not target_buses:
                return None

            chosen_flags: list[LoadSheddingFlag] = []
            shed_mw = 50.0 if "NON_CONVERGENCE" in failed_contingency.violations else 25.0
            for bus in target_buses:
                chosen_flags.extend(self._shed_from_bus(agent_id, bus, shed_mw, loads_by_bus))

            if not chosen_flags:
                return None

            accepted_flags = self._merge_load_shedding_flags(accepted_flags, chosen_flags)
            current_state = self._apply_load_shedding_to_state(state, accepted_flags)

            if "NON_CONVERGENCE" in failed_contingency.violations:
                return ActionBundle(
                    timestamp=observation.timestamp,
                    agent_id=agent_id,
                    load_shedding_flags=tuple(accepted_flags),
                )

            lf_result = run_ac_load_flow(current_state, observation.timestamp)
            lf_violations = lf_result.violations(
                constraints.max_branch_loading_percent,
                constraints.min_voltage_pu,
                constraints.max_voltage_pu,
            )
            fallback_blocked = (
                lf_result.status == PhysicsStatus.FALLBACK_USED
                and not self._simulator.allow_fallback_physics
            )
            if not lf_result.converged or lf_violations or fallback_blocked:
                return None

        return None

    @staticmethod
    def _merge_load_shedding_flags(
        existing: list[LoadSheddingFlag],
        new_flags: list[LoadSheddingFlag],
    ) -> list[LoadSheddingFlag]:
        merged: dict[str, LoadSheddingFlag] = {flag.load_id: flag for flag in existing}
        for flag in new_flags:
            if flag.load_id in merged:
                previous = merged[flag.load_id]
                merged[flag.load_id] = LoadSheddingFlag(
                    load_id=flag.load_id,
                    region=flag.region,
                    shed_mw=round(previous.shed_mw + flag.shed_mw, 3),
                    priority=min(previous.priority, flag.priority),
                )
            else:
                merged[flag.load_id] = flag
        return list(merged.values())

    def _load_shedding_candidates(
        self,
        agent_id: str,
        target_buses: list[str],
        loads_by_bus: dict[str, list[Any]],
    ) -> list[list[LoadSheddingFlag]]:
        candidates: list[list[LoadSheddingFlag]] = []
        steps = (25.0, 50.0, 75.0, 100.0, 125.0, 150.0)

        for shed_step_mw in steps:
            for bus in target_buses:
                candidates.append(
                    self._shed_from_bus(agent_id, bus, shed_step_mw, loads_by_bus)
                )

            combined: list[LoadSheddingFlag] = []
            for bus in target_buses:
                combined.extend(self._shed_from_bus(agent_id, bus, shed_step_mw, loads_by_bus))
            candidates.append(combined)

        candidates.sort(key=lambda flags: sum(flag.shed_mw for flag in flags))
        return candidates

    def _shed_from_bus(
        self,
        agent_id: str,
        bus: str,
        shed_mw: float,
        loads_by_bus: dict[str, list[Any]],
    ) -> list[LoadSheddingFlag]:
        flags: list[LoadSheddingFlag] = []
        remaining = shed_mw
        for load in sorted(loads_by_bus.get(bus, []), key=lambda item: item.demand_mw, reverse=True):
            if remaining <= 0:
                break
            load_shed_mw = min(remaining, load.demand_mw)
            if load_shed_mw > 0:
                flags.append(
                    LoadSheddingFlag(
                        load_id=load.load_id,
                        region=self._agent_region(agent_id),
                        shed_mw=round(load_shed_mw, 3),
                        priority=1,
                    )
                )
                remaining -= load_shed_mw
        return flags

    @staticmethod
    def _low_voltage_buses(violations: tuple[str, ...]) -> list[str]:
        buses: list[str] = []
        for violation in violations:
            if not violation.startswith("LOW_VOLTAGE bus="):
                continue
            bus_id = violation.split("LOW_VOLTAGE bus=", 1)[1].split(" ", 1)[0]
            if bus_id not in buses:
                buses.append(bus_id)
        return buses

    @staticmethod
    def _non_convergence_target_buses(
        loads_by_bus: dict[str, list[Any]],
        max_buses: int = 3,
    ) -> list[str]:
        """Find high-demand buses to shed load from when N-1 fails with NON_CONVERGENCE.

        When pandapower is unavailable, the fallback load flow cannot solve for
        voltage violations and instead reports NON_CONVERGENCE due to generation
        imbalance. In this case, we shed load from the highest-demand buses to
        restore balance.
        """
        bus_demands: list[tuple[str, float]] = []
        for bus_id, loads in loads_by_bus.items():
            total_demand = sum(load.demand_mw for load in loads)
            if total_demand > 0:
                bus_demands.append((bus_id, total_demand))
        bus_demands.sort(key=lambda x: x[1], reverse=True)
        return [bus_id for bus_id, _ in bus_demands[:max_buses]]

    @staticmethod
    def _apply_load_shedding_to_state(
        state: dict[str, Any],
        flags: list[LoadSheddingFlag],
    ) -> dict[str, Any]:
        modified_state = copy.deepcopy(state)
        shed_by_load = {flag.load_id: flag.shed_mw for flag in flags}
        for load in modified_state.get("loads", []):
            load_id = str(load.get("load_id", load.get("name", "")))
            if load_id in shed_by_load:
                load["p_mw"] = max(0.0, float(load.get("p_mw", 0.0)) - shed_by_load[load_id])
        return modified_state

    def distribute_observation(
        self, observation: ObservationBundle
    ) -> dict[str, ObservationBundle]:
        distribution: dict[str, ObservationBundle] = {}
        for agent_id in ALL_AGENTS:
            distribution[agent_id] = observation
        return distribution

    def collect_agent_outputs(
        self, observations: dict[str, ObservationBundle]
    ) -> dict[str, AgentResponse]:
        responses: dict[str, AgentResponse] = {}

        for agent_id in ALL_AGENTS:
            obs = observations.get(agent_id)
            if obs is None:
                continue

            action, reasoning = self._build_agent_action(agent_id, obs)
            response = AgentResponse(
                agent_id=agent_id,
                action=action,
                reasoning=reasoning,
                timestamp=obs.timestamp,
            )
            responses[agent_id] = response
            decision = AgentDecision(
                agent_id=agent_id,
                action=action,
                reasoning=reasoning,
                timestamp=obs.timestamp,
            )
            if agent_id == AGENT_COORDINATOR:
                self._coordinator = decision
            elif agent_id == AGENT_ORACLE:
                self._oracle = decision
            elif agent_id in REGIONAL_AGENTS:
                self._regional_agents[agent_id] = decision

            self._audit_logger.log(
                agent_id=agent_id,
                action="decide",
                result="action_proposed" if action is not None else "monitoring_only",
                metadata={
                    "hour_index": obs.hour_index,
                    "timestamp": obs.timestamp.isoformat(),
                    "has_violations": obs.has_violations(),
                    "action_empty": action is None or action.is_empty(),
                    "reasoning": reasoning,
                    "action_summary": {
                        "generator_setpoint_changes": len(action.generator_setpoint_changes) if action else 0,
                        "redispatch_requests": len(action.redispatch_requests) if action else 0,
                        "load_shedding_flags": len(action.load_shedding_flags) if action else 0,
                        "interconnect_flow_adjustments": len(action.interconnect_flow_adjustments) if action else 0,
                    },
                },
            )

        return responses

    async def collect_agent_outputs_async(
        self, observations: dict[str, ObservationBundle]
    ) -> dict[str, AgentResponse]:
        async def _run_agent(
            agent_id: str,
        ) -> tuple[str, ActionBundle | None, str, datetime, str | None]:
            obs = observations.get(agent_id)
            if obs is None:
                return agent_id, None, "", datetime.now(), None

            try:
                action, reasoning = await self._build_agent_action_async(
                    agent_id, obs
                )
                return agent_id, action, reasoning, obs.timestamp, None
            except Exception as exc:
                return (
                    agent_id,
                    None,
                    f"Agent {agent_id} encountered an error: {type(exc).__name__}",
                    obs.timestamp,
                    type(exc).__name__,
                )

        tasks = [_run_agent(aid) for aid in ALL_AGENTS]
        results = await asyncio.gather(*tasks)

        responses: dict[str, AgentResponse] = {}
        for agent_id, action, reasoning, timestamp, error_type in sorted(
            results, key=lambda r: r[0]
        ):
            if error_type is not None and agent_id == AGENT_COORDINATOR:
                obs = observations.get(agent_id)
                if obs is not None:
                    action, reasoning = await asyncio.to_thread(
                        self._build_deterministic_coordinator_action,
                        agent_id,
                        obs,
                    )

            response = AgentResponse(
                agent_id=agent_id,
                action=action,
                reasoning=reasoning,
                timestamp=timestamp,
            )
            responses[agent_id] = response
            decision = AgentDecision(
                agent_id=agent_id,
                action=action,
                reasoning=reasoning,
                timestamp=timestamp,
            )
            if agent_id == AGENT_COORDINATOR:
                self._coordinator = decision
            elif agent_id == AGENT_ORACLE:
                self._oracle = decision
            elif agent_id in REGIONAL_AGENTS:
                self._regional_agents[agent_id] = decision

            obs = observations.get(agent_id)
            self._audit_logger.log(
                agent_id=agent_id,
                action="decide",
                result="action_proposed" if action is not None else "monitoring_only",
                metadata={
                    "hour_index": obs.hour_index if obs else -1,
                    "timestamp": timestamp.isoformat(),
                    "has_violations": obs.has_violations() if obs else False,
                    "action_empty": action is None or action.is_empty(),
                    "reasoning": reasoning,
                    "action_summary": {
                        "generator_setpoint_changes": (
                            len(action.generator_setpoint_changes) if action else 0
                        ),
                        "redispatch_requests": (
                            len(action.redispatch_requests) if action else 0
                        ),
                        "load_shedding_flags": (
                            len(action.load_shedding_flags) if action else 0
                        ),
                        "interconnect_flow_adjustments": (
                            len(action.interconnect_flow_adjustments) if action else 0
                        ),
                    },
                },
            )

        return responses

    def _materialize_redispatch(self, action: ActionBundle) -> ActionBundle:
        trace(
            "AgentRuntime._materialize_redispatch.start",
            agent_id=action.agent_id,
            redispatch_requests=len(action.redispatch_requests),
            existing_setpoint_changes=len(action.generator_setpoint_changes),
        )
        if not action.redispatch_requests:
            return action

        obs = self._simulator.get_observation()
        setpoint_changes = list(action.generator_setpoint_changes)
        explicit_setpoint_generators = {change.generator_id for change in setpoint_changes}
        state_generators = {
            str(gen.get("generator_id", gen.get("name", ""))): gen
            for gen in self._simulator.current_network_state.get("generators", [])
        }

        for request in action.redispatch_requests:
            trace(
                "AgentRuntime._materialize_redispatch.request",
                agent_id=action.agent_id,
                generator_id=request.generator_id,
                upward_mw=request.upward_mw,
                downward_mw=request.downward_mw,
            )
            if request.generator_id in explicit_setpoint_generators:
                trace(
                    "AgentRuntime._materialize_redispatch.skip_explicit_setpoint",
                    generator_id=request.generator_id,
                )
                continue
            observed_generator = obs.scada.get_generator(request.generator_id)
            if observed_generator is None:
                trace(
                    "AgentRuntime._materialize_redispatch.skip_missing_generator",
                    generator_id=request.generator_id,
                )
                continue

            state_generator = state_generators.get(request.generator_id, {})
            min_mw = float(state_generator.get("min_p_mw", 0.0))
            max_mw = float(state_generator.get("max_p_mw", max(observed_generator.setpoint_mw, 0.0)))
            requested_setpoint = (
                observed_generator.setpoint_mw
                + request.upward_mw
                - request.downward_mw
            )
            new_setpoint = max(min_mw, min(max_mw, requested_setpoint))
            setpoint_changes.append(
                GeneratorSetpointChange(
                    generator_id=request.generator_id,
                    new_setpoint_mw=new_setpoint,
                )
            )
            trace(
                "AgentRuntime._materialize_redispatch.setpoint_change",
                generator_id=request.generator_id,
                old_setpoint_mw=observed_generator.setpoint_mw,
                new_setpoint_mw=new_setpoint,
            )

        return ActionBundle(
            timestamp=action.timestamp,
            agent_id=action.agent_id,
            generator_setpoint_changes=tuple(setpoint_changes),
            redispatch_requests=action.redispatch_requests,
            load_shedding_flags=action.load_shedding_flags,
            interconnect_flow_adjustments=action.interconnect_flow_adjustments,
        )

    def execute_validated_actions(
        self, actions: list[ActionBundle]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with trace_scope("AgentRuntime.execute_validated_actions", actions=len(actions)):
            for index, action in enumerate(actions):
                trace(
                    "AgentRuntime.execute_validated_actions.action",
                    index=index,
                    agent_id=action.agent_id,
                    empty=action.is_empty(),
                )
                if action.is_empty():
                    continue

                obs = self._simulator.get_observation()
                physical_action = self._materialize_redispatch(action)
                with trace_scope(
                    "AgentRuntime.execute_validated_actions.simulator.evaluate",
                    agent_id=physical_action.agent_id,
                    setpoint_changes=len(physical_action.generator_setpoint_changes),
                ):
                    prediction_result = self._simulator.simulate_action(physical_action, obs)
                    self._audit_logger.log(
                        agent_id=physical_action.agent_id,
                        action="simulate_action",
                        result="accepted" if prediction_result["accepted"] else "rejected",
                        metadata={
                            "accepted": prediction_result["accepted"],
                            "committed": prediction_result.get("committed", False),
                            "materialized_setpoint_changes": len(physical_action.generator_setpoint_changes),
                            "load_shedding_flags": len(physical_action.load_shedding_flags),
                            "redispatch_requests": len(physical_action.redispatch_requests),
                            "validation_errors": prediction_result.get("validation_errors", []),
                            "violations": (
                                prediction_result.get("load_flow_result", {}).get("violations", [])
                                if prediction_result.get("load_flow_result")
                                else []
                            ),
                            "reasoning": next(
                                (
                                    decision.reasoning for decision in [
                                        self._coordinator,
                                        *self._regional_agents.values(),
                                        self._oracle,
                                    ]
                                    if decision is not None and decision.agent_id == physical_action.agent_id
                                ),
                                "",
                            ),
                        },
                    )
                    eval_result = self._simulator.evaluate(physical_action, obs)
                results.append(eval_result)

                trace(
                    "AgentRuntime.execute_validated_actions.result",
                    agent_id=physical_action.agent_id,
                    accepted=eval_result["accepted"],
                    load_flow_status=(eval_result.get("load_flow_result") or {}).get("status"),
                )

                self._audit_logger.log(
                    agent_id=physical_action.agent_id,
                    action="execute_action",
                    result="accepted" if eval_result["accepted"] else "rejected",
                    metadata={
                        "accepted": eval_result["accepted"],
                        "materialized_setpoint_changes": len(physical_action.generator_setpoint_changes),
                        "redispatch_requests": len(physical_action.redispatch_requests),
                        "validation_errors": eval_result.get("validation_errors", []),
                        "violations": (
                            eval_result.get("load_flow_result", {}).get("violations", [])
                            if eval_result.get("load_flow_result")
                            else []
                        ),
                    },
                )

        return results

    async def execute_validated_actions_async(
        self, actions: list[ActionBundle]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with trace_scope(
            "AgentRuntime.execute_validated_actions_async", actions=len(actions)
        ):
            for index, action in enumerate(actions):
                trace(
                    "AgentRuntime.execute_validated_actions_async.action",
                    index=index,
                    agent_id=action.agent_id,
                    empty=action.is_empty(),
                )
                if action.is_empty():
                    continue

                obs = self._simulator.get_observation()
                physical_action = self._materialize_redispatch(action)
                with trace_scope(
                    "AgentRuntime.execute_validated_actions_async.simulator.evaluate",
                    agent_id=physical_action.agent_id,
                    setpoint_changes=len(physical_action.generator_setpoint_changes),
                ):
                    prediction_result = await self._run_in_pool_or_thread(
                        self._simulator.simulate_action,
                        physical_action,
                        obs,
                    )
                    self._audit_logger.log(
                        agent_id=physical_action.agent_id,
                        action="simulate_action",
                        result="accepted" if prediction_result["accepted"] else "rejected",
                        metadata={
                            "accepted": prediction_result["accepted"],
                            "committed": prediction_result.get("committed", False),
                            "materialized_setpoint_changes": len(
                                physical_action.generator_setpoint_changes
                            ),
                            "load_shedding_flags": len(
                                physical_action.load_shedding_flags
                            ),
                            "redispatch_requests": len(
                                physical_action.redispatch_requests
                            ),
                            "validation_errors": prediction_result.get(
                                "validation_errors", []
                            ),
                            "violations": (
                                prediction_result.get("load_flow_result", {}).get(
                                    "violations", []
                                )
                                if prediction_result.get("load_flow_result")
                                else []
                            ),
                            "reasoning": next(
                                (
                                    decision.reasoning
                                    for decision in [
                                        self._coordinator,
                                        *self._regional_agents.values(),
                                        self._oracle,
                                    ]
                                    if decision is not None
                                    and decision.agent_id == physical_action.agent_id
                                ),
                                "",
                            ),
                        },
                    )
                    eval_result = await self._run_in_pool_or_thread(
                        self._simulator.evaluate,
                        physical_action,
                        obs,
                    )
                results.append(eval_result)

                trace(
                    "AgentRuntime.execute_validated_actions_async.result",
                    agent_id=physical_action.agent_id,
                    accepted=eval_result["accepted"],
                    load_flow_status=(
                        eval_result.get("load_flow_result") or {}
                    ).get("status"),
                )

                self._audit_logger.log(
                    agent_id=physical_action.agent_id,
                    action="execute_action",
                    result="accepted" if eval_result["accepted"] else "rejected",
                    metadata={
                        "accepted": eval_result["accepted"],
                        "materialized_setpoint_changes": len(
                            physical_action.generator_setpoint_changes
                        ),
                        "redispatch_requests": len(
                            physical_action.redispatch_requests
                        ),
                        "validation_errors": eval_result.get(
                            "validation_errors", []
                        ),
                        "violations": (
                            eval_result.get("load_flow_result", {}).get(
                                "violations", []
                            )
                            if eval_result.get("load_flow_result")
                            else []
                        ),
                    },
                )

        return results

    async def run_hour_step_async(
        self, hour: int
    ) -> dict[str, Any]:
        obs = self._simulator.step(hour)

        self._audit_logger.log(
            agent_id="simulator",
            action="step",
            result="observation_generated",
            metadata={
                "hour_index": hour,
                "timestamp": obs.timestamp.isoformat(),
            },
        )

        observations = self.distribute_observation(obs)
        responses = await self.collect_agent_outputs_async(observations)

        actions: list[ActionBundle] = []
        for agent_id, response in responses.items():
            if response.action and not response.action.is_empty():
                actions.append(response.action)

        eval_results = await self.execute_validated_actions_async(actions)

        return {
            "hour_index": hour,
            "observation": obs,
            "agent_responses": responses,
            "evaluation_results": eval_results,
        }

    def run_hour_step(
        self, hour: int
    ) -> dict[str, Any]:
        obs = self._simulator.step(hour)

        self._audit_logger.log(
            agent_id="simulator",
            action="step",
            result="observation_generated",
            metadata={
                "hour_index": hour,
                "timestamp": obs.timestamp.isoformat(),
            },
        )

        observations = self.distribute_observation(obs)
        responses = self.collect_agent_outputs(observations)

        actions: list[ActionBundle] = []
        for agent_id, response in responses.items():
            if response.action and not response.action.is_empty():
                actions.append(response.action)

        eval_results = self.execute_validated_actions(actions)

        return {
            "hour_index": hour,
            "observation": obs,
            "agent_responses": responses,
            "evaluation_results": eval_results,
        }

    def check_api_key_configured(self) -> bool:
        return self._opencode_api_key is not None


class AsyncAgentRuntime(AgentRuntime):
    """Variant of AgentRuntime with all methods exposed as native async."""

    async def collect_agent_outputs(  # type: ignore[override]
        self, observations: dict[str, ObservationBundle]
    ) -> dict[str, AgentResponse]:
        return await self.collect_agent_outputs_async(observations)

    async def execute_validated_actions(  # type: ignore[override]
        self, actions: list[ActionBundle]
    ) -> list[dict[str, Any]]:
        return await self.execute_validated_actions_async(actions)

    async def run_hour_step(  # type: ignore[override]
        self, hour: int
    ) -> dict[str, Any]:
        return await self.run_hour_step_async(hour)


def create_runtime(
    simulator: GridSimulator,
    audit_logger: AuditLogger | None = None,
    model_overrides: Mapping[str, str] | None = None,
    model_client: ModelActionClient | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        simulator=simulator,
        audit_logger=audit_logger,
        model_overrides=model_overrides,
        model_client=model_client,
    )


def create_async_runtime(
    simulator: GridSimulator,
    audit_logger: AuditLogger | None = None,
    model_overrides: Mapping[str, str] | None = None,
    model_client: ModelActionClient | None = None,
) -> AsyncAgentRuntime:
    return AsyncAgentRuntime(
        simulator=simulator,
        audit_logger=audit_logger,
        model_overrides=model_overrides,
        model_client=model_client,
    )
