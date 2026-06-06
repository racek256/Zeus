"""Tests for run_simulation controller - failure stop behavior."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from athenaai.simulator import GridSimulator
from athenaai.agent_runtime import create_runtime
from athenaai.audit.logger import AuditLogger
from athenaai.schema import ActionBundle
from run_simulation import build_model_overrides


class TestRunSimulationFailureStop:
    def test_empty_simulation_no_crash(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        runtime = create_runtime(sim, audit_logger=AuditLogger())
        obs = sim.get_observation(0)
        observations = runtime.distribute_observation(obs)
        responses = runtime.collect_agent_outputs(observations)
        actions: list[ActionBundle] = []
        for agent_id, response in responses.items():
            if response.action and not response.action.is_empty():
                actions.append(response.action)
        eval_results = runtime.execute_validated_actions(actions)
        assert isinstance(eval_results, list)

    def test_audit_logger_integrated(self):
        logger = AuditLogger()
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        runtime = create_runtime(sim, audit_logger=logger)
        obs = sim.step(0)
        observations = runtime.distribute_observation(obs)
        runtime.collect_agent_outputs(observations)
        logs = logger.get_logs()
        assert len(logs) > 0

    def test_build_model_overrides_from_cli_args(self):
        args = SimpleNamespace(
            model="test/all",
            coordinator_model="test/coordinator",
            regional_model="test/regional",
            oracle_model="test/oracle",
            bohemia_west_model="test/west",
            bohemia_east_model=None,
            moravia_model=None,
            silesia_model="test/silesia",
        )
        assert build_model_overrides(args) == {
            "all": "test/all",
            "coordinator": "test/coordinator",
            "regional": "test/regional",
            "oracle": "test/oracle",
            "bohemia-west": "test/west",
            "silesia": "test/silesia",
        }
