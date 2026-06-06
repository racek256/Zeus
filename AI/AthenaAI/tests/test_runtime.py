"""Tests for agent runtime and API server."""

from datetime import datetime
import importlib
from os import terminal_size
from pathlib import Path
from unittest.mock import patch

from athenaai.agent_runtime import AgentResponse, AgentRuntime, create_runtime
from athenaai.api.server import SimulationAPIServer
from athenaai.audit.logger import AuditLogger
from athenaai.audit.live_view import (
    AgentOutputFileLog,
    AgentLogTUI,
    AgentWorkLog,
    build_agent_work_logs,
    format_agent_output_block,
    print_agent_output_only,
    print_agent_work_logs,
    sanitize_terminal_text,
    summarize_action,
)
from athenaai.schema import ActionBundle, GeneratorSetpointChange, RedispatchRequest
from athenaai.simulator import GridSimulator


class FakeModelClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        timeout_s: float = 60.0,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "timeout_s": str(timeout_s),
            }
        )
        return self.response


_REAL_IMPORT_MODULE = importlib.import_module


def import_without_pandapower(name, package=None):
    if name == "pandapower":
        raise ImportError("pandapower intentionally hidden for test")
    return _REAL_IMPORT_MODULE(name, package)


class TestAuditLogger:
    def test_audit_logger_basic(self):
        logger = AuditLogger()
        entry_id = logger.log("coordinator", "step", "observation_generated", {"hour": 0})
        assert entry_id is not None
        logs = logger.get_logs()
        assert len(logs) == 1
        assert logs[0]["agent_id"] == "coordinator"
        assert logs[0]["action"] == "step"

    def test_audit_logger_lines_format(self):
        logger = AuditLogger()
        logger.log("coordinator", "step", "ok", {"hour": 0})
        lines = logger.get_lines()
        assert len(lines) == 1
        parts = lines[0].split(" | ")
        assert len(parts) == 5
        assert parts[1] == "coordinator"
        assert parts[2] == "step"
        assert parts[3] == "ok"

    def test_audit_logger_filter_by_agent(self):
        logger = AuditLogger()
        logger.log("coordinator", "step", "ok")
        logger.log("bohemia-west", "observe", "ok")
        coordinator_logs = logger.filter_by_agent("coordinator")
        assert len(coordinator_logs) == 1

    def test_audit_logger_clear(self):
        logger = AuditLogger()
        logger.log("coordinator", "step", "ok")
        logger.clear()
        assert len(logger.get_logs()) == 0


class TestAgentLiveView:
    def test_summarize_empty_action(self):
        action = ActionBundle(timestamp=datetime(2026, 1, 1), agent_id="coordinator")
        assert summarize_action(action) == "none"

    def test_summarize_action_counts_non_empty_changes(self):
        action = ActionBundle(
            timestamp=datetime(2026, 1, 1),
            agent_id="coordinator",
            generator_setpoint_changes=(GeneratorSetpointChange("G1", 120.0),),
        )
        assert summarize_action(action) == "gen:1"

    def test_build_agent_work_logs_include_model_and_reasoning(self):
        timestamp = datetime(2026, 1, 1)
        action = ActionBundle(timestamp=timestamp, agent_id="coordinator")
        responses = {
            "coordinator": AgentResponse(
                agent_id="coordinator",
                action=action,
                reasoning="balanced grid state",
                timestamp=timestamp,
            )
        }
        logs = build_agent_work_logs(
            hour_index=3,
            responses=responses,
            model_lookup={"coordinator": "test/model"},
        )
        assert len(logs) == 1
        assert logs[0].agent_id == "coordinator"
        assert logs[0].model == "test/model"
        assert "balanced grid state" in logs[0].to_line()
        assert logs[0].action_details["agent_id"] == "coordinator"

    def test_print_agent_work_logs_outputs_lines(self, capsys):
        timestamp = datetime(2026, 1, 1)
        responses = {
            "oracle": AgentResponse(
                agent_id="oracle",
                action=None,
                reasoning="n-1 pass",
                timestamp=timestamp,
            )
        }
        logs = build_agent_work_logs(0, responses, {"oracle": "test/oracle"})
        print_agent_work_logs(logs)
        captured = capsys.readouterr()
        assert "oracle" in captured.out
        assert "test/oracle" in captured.out
        assert "n-1 pass" in captured.out

    def test_agent_output_only_filters_simulator_audit(self, capsys):
        timestamp = datetime(2026, 1, 1)
        logs = [
            AgentWorkLog(
                hour_index=0,
                timestamp=timestamp,
                agent_id="coordinator",
                model="deepseek-v4-flash",
                reasoning="simulate before commit",
                action_summary="shed:1",
                action_details={"agent_id": "coordinator", "load_shedding_flags": []},
            )
        ]
        audit_lines = [
            "2026-01-01 00:00:00.000 | simulator | step | observation_generated | {}",
            "2026-01-01 00:00:00.001 | coordinator | simulate_action | accepted | {}",
        ]
        print_agent_output_only(logs, audit_lines)
        captured = capsys.readouterr()
        assert "simulate before commit" in captured.out
        assert "Reasoning: simulate before commit" in captured.out
        assert "Action details" in captured.out
        assert "simulate_action" in captured.out
        assert "simulator | step" not in captured.out

    def test_agent_output_file_log_writes_formatted_block(self, tmp_path):
        path = tmp_path / "agent-output.log"
        file_log = AgentOutputFileLog(path)
        logs = [
            AgentWorkLog(
                hour_index=2,
                timestamp=datetime(2026, 1, 1, 2),
                agent_id="oracle",
                model="deepseek-v4-flash",
                reasoning="read-only diagnostic",
                action_summary="none",
                action_details={},
            )
        ]
        file_log.append(logs, ["2026 | oracle | decide | monitoring_only | {}"])
        contents = path.read_text(encoding="utf-8")
        assert "hour=0002" in contents
        assert "read-only diagnostic" in contents
        assert "oracle | decide" in contents

    def test_format_agent_output_block_returns_no_lines_for_empty_input(self):
        assert format_agent_output_block([], []) == []

    def test_sanitize_terminal_text_strips_ansi_escape_sequences(self):
        assert sanitize_terminal_text("safe \033[31mred\033[0m") == "safe red"

    def test_agent_log_tui_renders_sanitized_bounded_output(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "athenaai.audit.live_view.get_terminal_size",
            lambda fallback: terminal_size((100, 24)),
        )
        tui = AgentLogTUI(max_lines=1)
        logs = [
            AgentWorkLog(
                hour_index=0,
                timestamp=datetime(2026, 1, 1),
                agent_id="coordinator",
                model="test/model",
                reasoning="first",
                action_summary="none",
                action_details={},
            ),
            AgentWorkLog(
                hour_index=1,
                timestamp=datetime(2026, 1, 1, 1),
                agent_id="oracle",
                model="test/oracle",
                reasoning="safe \033[31mreason\033[0m",
                action_summary="none",
                action_details={},
            ),
        ]
        tui.update(
            hour_index=1,
            total_hours=2,
            logs=logs,
            audit_lines=["audit \033[31mred\033[0m"],
            failed_hours=[],
        )
        captured = capsys.readouterr()
        assert "AthenaAI live agent log" in captured.out
        assert "oracle" in captured.out
        assert "first" not in captured.out
        assert "\033[31m" not in captured.out
        assert "audit red" in captured.out


class TestAgentRuntime:
    def test_runtime_creation(self):
        sim = GridSimulator(start_hour=0, allow_fallback_physics=True)
        runtime = create_runtime(sim)
        assert runtime is not None
        assert runtime.simulator is sim

    def test_runtime_no_api_key(self):
        sim = GridSimulator(start_hour=0, allow_fallback_physics=True)
        runtime = create_runtime(sim)
        assert not runtime.check_api_key_configured()

    def test_runtime_distribute_observation(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        runtime = create_runtime(sim)
        obs = sim.get_observation(0)
        distribution = runtime.distribute_observation(obs)
        assert "coordinator" in distribution
        assert "oracle" in distribution

    def test_runtime_collect_agent_outputs_empty(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        runtime = create_runtime(sim)
        obs = sim.get_observation(0)
        distribution = {"coordinator": obs}
        responses = runtime.collect_agent_outputs(distribution)
        assert "coordinator" in responses
        assert responses["coordinator"].action is None
        assert "no controllable generators" in responses["coordinator"].reasoning

    def test_runtime_collect_agent_outputs_generates_advisory_actions(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 200.0},
                {"generator_id": "G2", "name": "Gen 2", "bus": "B1", "p_mw": 50.0, "min_p_mw": 0.0, "max_p_mw": 100.0},
            ],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 120.0}],
        }
        sim._gens_ts = {0: {"G1": 100.0, "G2": 50.0}}
        sim._loads_ts = {0: {"L1": 120.0}}
        runtime = create_runtime(sim)
        obs = sim.get_observation(0)
        responses = runtime.collect_agent_outputs(runtime.distribute_observation(obs))
        coordinator = responses["coordinator"]
        assert coordinator.action is not None
        assert not coordinator.action.is_empty()
        assert coordinator.action.redispatch_requests[0].generator_id == "G1"
        assert "Decision for coordinator" in coordinator.reasoning
        assert responses["bohemia-west"].action is None
        assert "monitoring" in responses["bohemia-west"].reasoning
        assert responses["oracle"].action is None
        assert "read-only" in responses["oracle"].reasoning

    def test_runtime_coordinator_uses_model_json_action_when_available(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "is_slack": True}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 200.0},
            ],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 120.0}],
        }
        sim._current_network_state = sim._topology
        sim._gens_ts = {0: {"G1": 100.0}}
        sim._loads_ts = {0: {"L1": 120.0}}
        model_client = FakeModelClient(
            '{"reasoning":"raise G1 by model choice", "action":{"generator_setpoint_changes":[{"generator_id":"G1","new_setpoint_mw":125.0}], "redispatch_requests":[], "load_shedding_flags":[], "interconnect_flow_adjustments":[]}}'
        )
        runtime = create_runtime(sim, model_client=model_client)
        obs = sim.get_observation(0)
        responses = runtime.collect_agent_outputs({"coordinator": obs})
        action = responses["coordinator"].action
        assert model_client.calls
        assert action is not None
        assert action.generator_setpoint_changes[0].new_setpoint_mw == 125.0
        assert "Model decision" in responses["coordinator"].reasoning
        assert "raise G1 by model choice" in responses["coordinator"].reasoning

    def test_runtime_falls_back_when_model_json_invalid(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "is_slack": True}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 200.0},
            ],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 120.0}],
        }
        sim._current_network_state = sim._topology
        sim._gens_ts = {0: {"G1": 100.0}}
        sim._loads_ts = {0: {"L1": 120.0}}
        logger = AuditLogger()
        runtime = create_runtime(sim, audit_logger=logger, model_client=FakeModelClient("not-json"))
        obs = sim.get_observation(0)
        responses = runtime.collect_agent_outputs({"coordinator": obs})
        action = responses["coordinator"].action
        assert action is not None
        assert action.redispatch_requests[0].generator_id == "G1"
        assert "Decision for coordinator" in responses["coordinator"].reasoning
        assert any(log["action"] == "model_control" and log["result"] == "fallback_deterministic" for log in logger.get_logs())

    def test_materialize_redispatch_does_not_override_explicit_model_setpoint(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 200.0},
            ],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 100.0}],
        }
        sim._current_network_state = sim._topology
        sim._gens_ts = {0: {"G1": 100.0}}
        sim._loads_ts = {0: {"L1": 100.0}}
        runtime = create_runtime(sim)
        action = ActionBundle(
            timestamp=datetime(2026, 1, 1),
            agent_id="coordinator",
            generator_setpoint_changes=(GeneratorSetpointChange("G1", 150.0),),
            redispatch_requests=(
                RedispatchRequest(
                    generator_id="G1",
                    region="national",
                    upward_mw=20.0,
                    reason="should not override explicit setpoint",
                ),
            ),
        )
        materialized = runtime._materialize_redispatch(action)
        assert len(materialized.generator_setpoint_changes) == 1
        assert materialized.generator_setpoint_changes[0].new_setpoint_mw == 150.0

    def test_model_parser_skips_unknown_generator_setpoints(self, monkeypatch):
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 200.0},
            ],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 100.0}],
        }
        sim._current_network_state = sim._topology
        runtime = create_runtime(sim, model_client=FakeModelClient("{}"))
        obs = sim.get_observation(0)
        action, reasoning = runtime._parse_model_action(
            "coordinator",
            obs,
            '{"reasoning":"ignore unknown", "action":{"generator_setpoint_changes":[{"generator_id":"UNKNOWN","new_setpoint_mw":999.0}], "redispatch_requests":[], "load_shedding_flags":[], "interconnect_flow_adjustments":[]}}',
        )
        assert action is None
        assert reasoning == "ignore unknown"

    def test_runtime_collect_agent_outputs_balanced_grid_monitors_only(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 150.0}],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 100.0}],
        }
        sim._gens_ts = {0: {"G1": 100.0}}
        sim._loads_ts = {0: {"L1": 100.0}}
        runtime = create_runtime(sim)
        obs = sim.get_observation(0)
        responses = runtime.collect_agent_outputs(runtime.distribute_observation(obs))
        assert responses["coordinator"].action is None
        assert "no redispatch required" in responses["coordinator"].reasoning

    def test_runtime_executes_redispatch_as_physical_control(self):
        sim = GridSimulator(start_hour=0, allow_fallback_physics=True)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 150.0}],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 120.0}],
        }
        sim._gens_ts = {0: {"G1": 100.0}}
        sim._loads_ts = {0: {"L1": 120.0}}
        sim._current_network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 150.0}],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 120.0}],
        }
        runtime = create_runtime(sim)
        obs = sim.get_observation(0)
        responses = runtime.collect_agent_outputs(runtime.distribute_observation(obs))
        actions = [response.action for response in responses.values() if response.action is not None]
        results = runtime.execute_validated_actions(actions)
        assert results
        assert all(result["accepted"] for result in results)
        assert all(result["load_flow_result"]["status"] in {"success", "fallback_used"} for result in results)
        assert sim.current_network_state["generators"][0]["p_mw"] == 120.0

    def test_runtime_blocks_fallback_physics_by_default(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 150.0}],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 120.0}],
        }
        sim._gens_ts = {0: {"G1": 100.0}}
        sim._loads_ts = {0: {"L1": 120.0}}
        sim._current_network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "name": "Gen 1", "bus": "B1", "p_mw": 100.0, "min_p_mw": 0.0, "max_p_mw": 150.0}],
            "loads": [{"load_id": "L1", "name": "Load 1", "bus": "B1", "p_mw": 120.0}],
        }
        runtime = create_runtime(sim)
        obs = sim.get_observation(0)
        responses = runtime.collect_agent_outputs(runtime.distribute_observation(obs))
        actions = [response.action for response in responses.values() if response.action is not None]
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            results = runtime.execute_validated_actions(actions)
        assert results
        assert not results[0]["accepted"]
        assert results[0]["load_flow_result"]["status"] == "fallback_used"
        assert results[0]["load_flow_result"]["fallback_blocked"]
        assert sim.current_network_state["generators"][0]["p_mw"] == 100.0

    def test_runtime_uses_model_overrides(self):
        sim = GridSimulator(start_hour=0)
        runtime = create_runtime(
            sim,
            model_overrides={"all": "test/global", "oracle": "test/oracle"},
        )
        assert runtime.get_agent_model("coordinator") == "test/global"
        assert runtime.get_agent_model("oracle") == "test/oracle"


class TestSimulationAPIServer:
    def test_server_creation(self):
        sim = GridSimulator(start_hour=0)
        server = SimulationAPIServer(sim)
        assert server is not None
        assert server.replay_mode

    def test_server_replay_mode_toggle(self):
        sim = GridSimulator(start_hour=0)
        server = SimulationAPIServer(sim)
        assert server.replay_mode
        server.replay_mode = False
        assert not server.replay_mode
