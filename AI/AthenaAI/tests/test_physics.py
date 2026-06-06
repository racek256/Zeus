"""Tests for physics engine - load flow, OPF, N-1."""

from datetime import datetime
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from athenaai.physics import (
    LoadFlowResult,
    N1Result,
    N1Status,
    n1_security_scan,
    run_ac_load_flow,
    run_opf,
    PhysicsStatus,
)
from athenaai.physics.engine import _build_pandapower_net


_REAL_IMPORT_MODULE = importlib.import_module


def import_without_pandapower(name, package=None):
    if name == "pandapower":
        raise ImportError("pandapower intentionally hidden for test")
    return _REAL_IMPORT_MODULE(name, package)


class TestLoadFlow:
    def test_load_flow_without_pandapower_uses_fallback(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0, "type": "b"}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_ac_load_flow(network_state, datetime.now())
        assert result.status == PhysicsStatus.FALLBACK_USED
        assert result.converged

    def test_load_flow_fallback_rejects_imbalanced_network(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0, "type": "b"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "bus": "B1", "p_mw": 10.0, "max_p_mw": 20.0}],
            "loads": [{"load_id": "L1", "bus": "B1", "p_mw": 100.0}],
        }
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_ac_load_flow(network_state, datetime.now())
        assert result.status == PhysicsStatus.NON_CONVERGENCE
        assert not result.converged


class TestN1:
    def test_n1_empty_network(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        result = n1_security_scan(network_state, datetime.now())
        assert result.status in (N1Status.PASSED, N1Status.FAILED)

    def test_n1_no_critical_elements(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        result = n1_security_scan(network_state, datetime.now(), critical_elements=[])
        assert result.passed
        assert len(result.contingencies) == 0

    def test_n1_with_critical_generators(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0}],
            "branches": [],
            "generators": [{"generator_id": "G1", "bus": "B1", "p_mw": 100.0, "name": "Gen 1"}],
            "loads": [],
        }
        result = n1_security_scan(
            network_state,
            datetime.now(),
            critical_elements=[{"type": "generator", "id": "G1"}],
        )
        assert len(result.contingencies) == 1

    def test_n1_can_stop_on_first_violation(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "bus": "B1", "p_mw": 100.0, "name": "Gen 1"},
                {"generator_id": "G2", "bus": "B1", "p_mw": 100.0, "name": "Gen 2"},
            ],
            "loads": [],
        }
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = n1_security_scan(
                network_state,
                datetime.now(),
                critical_elements=[
                    {"type": "generator", "id": "G1"},
                    {"type": "generator", "id": "G2"},
                ],
                stop_on_first_violation=True,
            )
        assert not result.passed
        assert len(result.contingencies) == 1
        assert result.violated_contingencies == ("generator_G1",)

    def test_n1_reuses_single_pandapower_network(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0, "is_slack": True}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "bus": "B1", "p_mw": 10.0, "name": "G1"},
                {"generator_id": "G2", "bus": "B1", "p_mw": 10.0, "name": "G2"},
            ],
            "loads": [],
        }
        from athenaai.physics.engine import _build_pandapower_net as real_build

        with patch("athenaai.physics.engine._build_pandapower_net") as build_net:
            build_net.side_effect = real_build
            n1_security_scan(
                network_state,
                datetime.now(),
                critical_elements=[
                    {"type": "generator", "id": "G1"},
                    {"type": "generator", "id": "G2"},
                ],
            )
        assert build_net.call_count == 1

    def test_n1_uses_stable_ids_when_display_names_differ(self):
        network_state = {
            "buses": [
                {"bus_id": "B1", "name": "Display Bus 1", "vn_kv": 110.0, "is_slack": True},
                {"bus_id": "B2", "name": "Display Bus 2", "vn_kv": 110.0},
            ],
            "branches": [
                {
                    "branch_id": "BR1",
                    "name": "Display Branch",
                    "from_bus": "B1",
                    "to_bus": "B2",
                    "r_ohm_per_km": 0.1,
                    "x_ohm_per_km": 0.4,
                    "c_nf_per_km": 10.0,
                    "max_i_ka": 1.0,
                }
            ],
            "generators": [
                {"generator_id": "G1", "name": "Display Gen", "bus": "B1", "p_mw": 10.0},
            ],
            "loads": [],
        }
        result = n1_security_scan(
            network_state,
            datetime.now(),
            critical_elements=[{"type": "generator", "id": "G1"}, {"type": "branch", "id": "BR1"}],
        )
        assert "generator_G1" not in result.violated_contingencies
        assert "branch_BR1" not in result.violated_contingencies


class TestOPF:
    def test_opf_without_pandapower(self):
        network_state = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0}],
            "branches": [],
            "generators": [],
            "loads": [],
        }
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_opf(network_state, {}, datetime.now())
        assert result.status == PhysicsStatus.UNAVAILABLE
        assert not result.solved


class TestPandapowerBuilder:
    def test_builder_maps_string_bus_ids_to_internal_indices(self):
        class FakePandapower(ModuleType):
            def __init__(self) -> None:
                super().__init__("pandapower")
                self.fake_net = SimpleNamespace(
                    bus=[],
                    ext_grid=[],
                    line=[],
                    trafo=[],
                    gen=[],
                    load=[],
                )

            def create_empty_network(self):
                return self.fake_net

            def create_bus(self, net, name, vn_kv, type):
                net.bus.append({"name": name, "vn_kv": vn_kv, "type": type})
                return len(net.bus) - 1

            def create_line_from_parameters(self, net, from_bus, to_bus, **kwargs):
                net.line.append({"from_bus": from_bus, "to_bus": to_bus, **kwargs})

            def create_transformer_from_parameters(self, net, hv_bus, lv_bus, **kwargs):
                net.trafo.append({"hv_bus": hv_bus, "lv_bus": lv_bus, **kwargs})

            def create_ext_grid(self, net, bus, **kwargs):
                net.ext_grid.append({"bus": bus, **kwargs})

            def create_gen(self, net, bus, **kwargs):
                net.gen.append({"bus": bus, **kwargs})

            def create_load(self, net, bus, **kwargs):
                net.load.append({"bus": bus, **kwargs})

        fake = FakePandapower()
        original = sys.modules.get("pandapower")
        sys.modules["pandapower"] = fake
        try:
            net = _build_pandapower_net(
                {
                    "buses": [
                        {"bus_id": "bus_001", "name": "Bus 1", "is_slack": True},
                        {"bus_id": "bus_002", "name": "Bus 2"},
                    ],
                    "branches": [{"branch_id": "L1", "from_bus": "bus_001", "to_bus": "bus_002"}],
                    "generators": [{"generator_id": "G1", "bus": "bus_001"}],
                    "loads": [{"load_id": "LD1", "bus": "bus_002"}],
                }
            )
        finally:
            if original is None:
                sys.modules.pop("pandapower", None)
            else:
                sys.modules["pandapower"] = original
        assert net.line[0]["from_bus"] == 0
        assert net.line[0]["to_bus"] == 1
        assert net.ext_grid[0]["bus"] == 0
        assert net.gen[0]["bus"] == 0
        assert net.gen[0]["slack"] is False
        assert net.gen[0]["slack_weight"] == 0.0
        assert net.load[0]["bus"] == 1
