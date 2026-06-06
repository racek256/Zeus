"""Tests for GridSimulator - dataset loading and state management."""

from datetime import datetime
from pathlib import Path

from athenaai.simulator import GridSimulator
from athenaai.schema import ActionBundle, GeneratorSetpointChange


class TestGridSimulatorInit:
    def test_gridsimulator_creation(self):
        sim = GridSimulator(start_hour=0, allow_fallback_physics=True)
        assert sim.current_hour == 0
        assert sim.constraints is not None

    def test_gridsimulator_step(self):
        sim = GridSimulator(start_hour=0, allow_fallback_physics=True)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        obs = sim.step(5)
        assert sim.current_hour == 5
        assert obs.hour_index == 5

    def test_gridsimulator_get_observation_without_init(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        obs = sim.get_observation(0)
        assert obs.hour_index == 0
        assert obs.scada is not None

    def test_gridsimulator_loads_greenhack_generator_schema(self, tmp_path):
        data_root = tmp_path / "dataset"
        static_dir = data_root / "data" / "static"
        realtime_dir = data_root / "data" / "realtime"
        static_dir.mkdir(parents=True)
        realtime_dir.mkdir(parents=True)
        (static_dir / "buses.csv").write_text(
            "bus_name,region,in_service,v_rated_kv\n"
            "bus_001,r1,True,138\n",
            encoding="utf-8",
        )
        (static_dir / "branches.csv").write_text(
            "branch_name,from_bus,to_bus,in_service,r_ohm,x_ohm,max_i_ka\n",
            encoding="utf-8",
        )
        (static_dir / "gens.csv").write_text(
            "gen_name,bus_name,opt_category,max_p_mw,min_p_mw\n"
            "gen_001,bus_001,day_ahead,100,0\n",
            encoding="utf-8",
        )
        (static_dir / "loads.csv").write_text(
            "load_name,bus_name\n"
            "load_001,bus_001\n",
            encoding="utf-8",
        )
        (realtime_dir / "gens_ts.csv").write_text(
            "datetime,gen_name,in_service,p_mw\n"
            "2024-01-01 00:00:00,gen_001,True,42\n",
            encoding="utf-8",
        )
        (realtime_dir / "loads_ts.csv").write_text(
            "datetime,load_name,in_service,p_mw,q_mvar\n"
            "2024-01-01 00:00:00,load_001,True,35,5\n",
            encoding="utf-8",
        )
        sim = GridSimulator(dataset_root=data_root, start_hour=0)
        sim.initialize()
        obs = sim.get_observation(0)
        assert obs.scada.buses[0].bus_id == "bus_001"
        assert obs.scada.generators[0].generator_id == "gen_001"
        assert obs.scada.generators[0].generation_mw == 42.0
        assert obs.scada.loads[0].load_id == "load_001"
        assert obs.scada.loads[0].demand_mw == 35.0

    def test_gridsimulator_missing_gen_hours_detection(self):
        sim = GridSimulator(start_hour=0)
        sim._gens_ts = {
            0: {"G1": 100.0},
            1: {"G1": 100.0},
            3: {"G1": 100.0},
        }
        missing = sim.get_missing_gen_hours()
        assert len(missing) == 0

    def test_gridsimulator_historical_state(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        sim._current_network_state = {"buses": [], "branches": [], "generators": [], "loads": []}
        obs = sim.get_observation(0)
        from athenaai.schema import ActionBundle
        action = ActionBundle(timestamp=datetime.now(), agent_id="test")
        sim.evaluate(action, obs)
        hist = sim.get_historical()
        assert len(hist) == 1
        assert hist[0].hour_index == 0

    def test_gridsimulator_rollback(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        sim._current_network_state = {"buses": [], "branches": [], "generators": [], "loads": []}
        obs0 = sim.get_observation(0)
        from athenaai.schema import ActionBundle
        sim.evaluate(ActionBundle(timestamp=datetime.now(), agent_id="test"), obs0)
        obs1 = sim.get_observation(1)
        sim.evaluate(ActionBundle(timestamp=datetime.now(), agent_id="test"), obs1)
        assert len(sim.get_historical()) == 2
        sim.rollback_to_hour(0)
        assert len(sim.get_historical()) == 0
        assert sim.current_hour == 0

    def test_evaluate_does_not_mutate_authoritative_state_by_shallow_copy(self):
        sim = GridSimulator(start_hour=0)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "bus": "B1", "p_mw": 10.0}],
            "loads": [],
        }
        sim._current_network_state = {
            "buses": [],
            "branches": [],
            "generators": [{"generator_id": "G1", "bus": "B1", "p_mw": 10.0}],
            "loads": [],
        }
        obs = sim.get_observation(0)
        action = ActionBundle(
            timestamp=datetime.now(),
            agent_id="coordinator",
            generator_setpoint_changes=(
                GeneratorSetpointChange(generator_id="G1", new_setpoint_mw=20.0),
            ),
        )
        sim.evaluate(action, obs)
        assert sim._current_network_state["generators"][0]["p_mw"] == 10.0

    def test_evaluate_commits_accepted_physical_action(self):
        sim = GridSimulator(start_hour=0, allow_fallback_physics=True)
        sim._topology = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "bus": "B1", "p_mw": 10.0, "min_p_mw": 0.0, "max_p_mw": 30.0}],
            "loads": [{"load_id": "L1", "bus": "B1", "p_mw": 20.0}],
        }
        sim._current_network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "bus": "B1", "p_mw": 10.0, "min_p_mw": 0.0, "max_p_mw": 30.0}],
            "loads": [{"load_id": "L1", "bus": "B1", "p_mw": 20.0}],
        }
        obs = sim.get_observation(0)
        action = ActionBundle(
            timestamp=datetime.now(),
            agent_id="coordinator",
            generator_setpoint_changes=(
                GeneratorSetpointChange(generator_id="G1", new_setpoint_mw=20.0),
            ),
        )
        result = sim.evaluate(action, obs)
        assert result["accepted"]
        assert sim.current_network_state["generators"][0]["p_mw"] == 20.0
        assert sim.get_observation(0).scada.generators[0].setpoint_mw == 20.0
