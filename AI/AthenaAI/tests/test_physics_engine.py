"""Tests for physics engine - state estimation, short-circuit, frequency response, parallel N-1, caching."""

import importlib
import time
from datetime import datetime
from unittest.mock import patch

from athenaai.physics import (
    FrequencyResponseResult,
    PhysicsStatus,
    ResultCache,
    ShortCircuitResult,
    StateEstimationResult,
    run_frequency_response,
    run_parallel_n1,
    run_short_circuit,
    run_state_estimation,
)
from athenaai.physics.n1 import N1Status, n1_parallel_scan, n1_security_scan


_REAL_IMPORT_MODULE = importlib.import_module


def import_without_pandapower(name, package=None):
    if name == "pandapower":
        raise ImportError("pandapower intentionally hidden for test")
    return _REAL_IMPORT_MODULE(name, package)


_SIMPLE_NETWORK = {
    "buses": [
        {"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0, "is_slack": True},
        {"bus_id": "B2", "name": "Bus 2", "vn_kv": 110.0},
    ],
    "branches": [],
    "generators": [
        {
            "generator_id": "G1",
            "name": "Gen 1",
            "bus": "B1",
            "p_mw": 50.0,
            "min_p_mw": 0.0,
            "max_p_mw": 100.0,
            "sn_mva": 120.0,
            "type": "thermal",
        },
    ],
    "loads": [
        {"load_id": "L1", "name": "Load 1", "bus": "B2", "p_mw": 40.0, "q_mvar": 10.0},
    ],
}


class TestStateEstimation:
    def test_state_estimation_fallback_succeeds(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_state_estimation(
                _SIMPLE_NETWORK,
                measurements=[
                    {"type": "voltage_mag", "bus": "Bus 1", "value": 1.02, "std": 0.01},
                    {"type": "voltage_mag", "bus": "Bus 2", "value": 0.98, "std": 0.01},
                    {"type": "voltage_angle", "bus": "Bus 1", "value": 0.0, "std": 0.5},
                ],
                seed=42,
            )
        assert result.success
        assert result.status == PhysicsStatus.FALLBACK_USED
        assert len(result.bus_estimates) >= 1
        assert result.estimated_v_mag_pu > 0.9

    def test_state_estimation_no_measurements(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_state_estimation(
                _SIMPLE_NETWORK,
                measurements=None,
                seed=42,
            )
        assert result.success
        assert result.status == PhysicsStatus.FALLBACK_USED

    def test_state_estimation_deterministic(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            measurements = [
                {"type": "voltage_mag", "bus": "Bus 1", "value": 1.02, "std": 0.01},
                {"type": "voltage_mag", "bus": "Bus 2", "value": 0.98, "std": 0.01},
            ]
            r1 = run_state_estimation(_SIMPLE_NETWORK, measurements=measurements, seed=123)
            r2 = run_state_estimation(_SIMPLE_NETWORK, measurements=measurements, seed=123)
        assert r1.bus_estimates == r2.bus_estimates
        assert r1.estimated_v_mag_pu == r2.estimated_v_mag_pu
        assert r1.estimated_v_angle_deg == r2.estimated_v_angle_deg

    def test_state_estimation_bad_data_detection(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_state_estimation(
                _SIMPLE_NETWORK,
                measurements=[
                    {"type": "voltage_mag", "bus": "Bus 1", "value": 1.02, "std": 0.01},
                    {"type": "voltage_mag", "bus": "Bus 1", "value": 2.5, "std": 0.01},
                ],
                seed=42,
            )
        assert result.success
        assert result.bad_data_detected
        assert len(result.suspicious_measurements) > 0

    def test_state_estimation_empty_network(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_state_estimation(
                {"buses": [], "branches": [], "generators": [], "loads": []},
                seed=42,
            )
        assert result.success
        assert len(result.bus_estimates) == 1
        assert result.bus_estimates[0][0] == "default_bus"


class TestShortCircuit:
    def test_short_circuit_fallback_succeeds(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_short_circuit(
                _SIMPLE_NETWORK,
                fault_bus="Bus 1",
                fault_type="3ph",
                seed=42,
            )
        assert result.success
        assert result.status == PhysicsStatus.FALLBACK_USED
        assert result.fault_current_ka > 0.0
        assert result.fault_power_mva > 0.0
        assert len(result.bus_voltages) > 0

    def test_short_circuit_zero_voltage_at_fault(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_short_circuit(
                _SIMPLE_NETWORK,
                fault_bus="Bus 1",
                fault_type="3ph",
                seed=42,
            )
        fault_voltage = None
        for bus_id, vm_pu, va_deg in result.bus_voltages:
            if bus_id == "Bus 1":
                fault_voltage = vm_pu
        assert fault_voltage is None or fault_voltage == 0.0

    def test_short_circuit_deterministic(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            r1 = run_short_circuit(_SIMPLE_NETWORK, fault_bus="Bus 1", seed=123)
            r2 = run_short_circuit(_SIMPLE_NETWORK, fault_bus="Bus 1", seed=123)
        assert r1.fault_current_ka == r2.fault_current_ka
        assert r1.fault_power_mva == r2.fault_power_mva
        assert r1.bus_voltages == r2.bus_voltages

    def test_short_circuit_different_fault_types(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            r3ph = run_short_circuit(_SIMPLE_NETWORK, fault_type="3ph", seed=42)
            r1ph = run_short_circuit(_SIMPLE_NETWORK, fault_type="1ph", seed=42)
        assert r3ph.success
        assert r1ph.success

    def test_short_circuit_empty_network(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_short_circuit(
                {"buses": [], "branches": [], "generators": [], "loads": []},
                seed=42,
            )
        assert result.success
        assert len(result.bus_voltages) == 1


class TestFrequencyResponse:
    def test_frequency_response_basic(self):
        disturbance = {"type": "load_loss", "delta_p_mw": 100.0}
        result = run_frequency_response(_SIMPLE_NETWORK, disturbance=disturbance)
        assert isinstance(result, FrequencyResponseResult)
        assert result.frequency_nadir_hz < 50.0
        assert result.rocof_hz_s > 0.0
        assert result.system_inertia_s > 0.0

    def test_frequency_response_deterministic(self):
        disturbance = {"type": "load_loss", "delta_p_mw": 80.0}
        r1 = run_frequency_response(_SIMPLE_NETWORK, disturbance=disturbance, seed=111)
        r2 = run_frequency_response(_SIMPLE_NETWORK, disturbance=disturbance, seed=111)
        assert r1.frequency_nadir_hz == r2.frequency_nadir_hz
        assert r1.rocof_hz_s == r2.rocof_hz_s
        assert r1.system_inertia_s == r2.system_inertia_s

    def test_frequency_response_no_disturbance(self):
        result = run_frequency_response(_SIMPLE_NETWORK, disturbance=None)
        assert result.success
        assert result.delta_p_mw == 0.0

    def test_frequency_response_below_min_frequency(self):
        disturbance = {"type": "load_loss", "delta_p_mw": 5000.0}
        result = run_frequency_response(
            _SIMPLE_NETWORK, disturbance=disturbance, min_frequency_hz=49.0
        )
        assert not result.success
        assert result.status == PhysicsStatus.VIOLATION_RAMP
        assert result.frequency_nadir_hz < 49.0

    def test_frequency_response_hydro_inertia(self):
        network = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0, "is_slack": True}],
            "branches": [],
            "generators": [
                {
                    "generator_id": "G1",
                    "bus": "B1",
                    "p_mw": 50.0,
                    "sn_mva": 100.0,
                    "type": "hydro",
                },
            ],
            "loads": [],
        }
        result = run_frequency_response(
            network, disturbance={"type": "load_loss", "delta_p_mw": 50.0}
        )
        assert result.system_inertia_s > 0.0

    def test_frequency_response_wind_no_inertia(self):
        network = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0, "is_slack": True}],
            "branches": [],
            "generators": [
                {
                    "generator_id": "G1",
                    "bus": "B1",
                    "p_mw": 50.0,
                    "sn_mva": 100.0,
                    "type": "wind",
                },
            ],
            "loads": [],
        }
        result = run_frequency_response(
            network, disturbance={"type": "load_loss", "delta_p_mw": 50.0}
        )
        assert result.frequency_nadir_hz <= 50.0
        assert result.system_inertia_s == 0.0


class TestParallelN1:
    def test_parallel_n1_empty_contingencies(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_parallel_n1(_SIMPLE_NETWORK, contingencies=[])
        assert result is not None
        assert isinstance(result.contingencies, tuple)
        assert len(result.contingencies) == 0

    def test_parallel_n1_small_set_sequential(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_parallel_n1(
                _SIMPLE_NETWORK,
                contingencies=[{"type": "generator", "id": "G1"}],
            )
        assert len(result.contingencies) == 1

    def test_parallel_n1_from_n1_module(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = n1_parallel_scan(
                _SIMPLE_NETWORK,
                critical_elements=[{"type": "generator", "id": "G1"}],
            )
        assert len(result.contingencies) == 1

    def test_parallel_n1_with_cache(self):
        network = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0, "is_slack": True}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "bus": "B1", "p_mw": 10.0, "name": "G1"},
                {"generator_id": "G2", "bus": "B1", "p_mw": 10.0, "name": "G2"},
                {"generator_id": "G3", "bus": "B1", "p_mw": 10.0, "name": "G3"},
                {"generator_id": "G4", "bus": "B1", "p_mw": 10.0, "name": "G4"},
                {"generator_id": "G5", "bus": "B1", "p_mw": 10.0, "name": "G5"},
            ],
            "loads": [],
        }
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result1 = n1_parallel_scan(network, use_cache=True, cache_ttl=60.0)
            result2 = n1_parallel_scan(network, use_cache=True, cache_ttl=60.0)
        assert result1.passed is not None
        assert result2.passed is not None


class TestResultCache:
    def test_cache_basic_operations(self):
        cache = ResultCache(max_size=10)
        key = "test_key"
        assert cache.get(key) is None
        cache.put(key, 42, ttl=60.0)
        assert cache.get(key) == 42
        assert cache.hits == 1

    def test_cache_key_generation(self):
        cache = ResultCache()
        network = {
            "buses": [{"bus_id": "B1", "name": "Bus 1", "vn_kv": 110.0}],
            "branches": [],
            "generators": [
                {"generator_id": "G1", "bus": "B1", "p_mw": 50.0},
            ],
            "loads": [{"load_id": "L1", "bus": "B1", "p_mw": 30.0}],
        }
        key1 = cache.make_key(network, operation="load_flow")
        key2 = cache.make_key(network, operation="load_flow")
        assert key1 == key2
        assert isinstance(key1, str)
        assert len(key1) == 64

    def test_cache_different_network_different_key(self):
        cache = ResultCache()
        net1 = {"buses": [{"bus_id": "B1"}], "branches": [], "generators": [], "loads": []}
        net2 = {"buses": [{"bus_id": "B2"}], "branches": [], "generators": [], "loads": []}
        key1 = cache.make_key(net1, operation="load_flow")
        key2 = cache.make_key(net2, operation="load_flow")
        assert key1 != key2

    def test_cache_same_operating_point_different_generation(self):
        cache = ResultCache()
        net1 = {
            "buses": [{"bus_id": "B1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "p_mw": 100.0}],
            "loads": [],
        }
        net2 = {
            "buses": [{"bus_id": "B1"}],
            "branches": [],
            "generators": [{"generator_id": "G1", "p_mw": 50.0}],
            "loads": [],
        }
        key1 = cache.make_key(net1, operation="load_flow")
        key2 = cache.make_key(net2, operation="load_flow")
        assert key1 != key2

    def test_cache_ttl_expiration(self):
        cache = ResultCache(max_size=10)
        key = "expiring_key"
        cache.put(key, "value", ttl=0.01)
        time.sleep(0.02)
        assert cache.get(key) is None
        assert cache.misses > 0

    def test_cache_max_size_eviction(self):
        cache = ResultCache(max_size=3)
        for i in range(5):
            cache.put(f"key_{i}", i, ttl=60.0)
        assert cache.size <= 3

    def test_cache_invalidate_single(self):
        cache = ResultCache()
        cache.put("key_a", 1, ttl=60.0)
        cache.put("key_b", 2, ttl=60.0)
        cache.invalidate("key_a")
        assert cache.get("key_a") is None
        assert cache.get("key_b") == 2

    def test_cache_invalidate_all(self):
        cache = ResultCache()
        cache.put("key_a", 1, ttl=60.0)
        cache.put("key_b", 2, ttl=60.0)
        cache.invalidate()
        assert cache.get("key_a") is None
        assert cache.get("key_b") is None
        assert cache.size == 0

    def test_cache_stats(self):
        cache = ResultCache(max_size=10)
        cache.put("k1", "v1", ttl=60.0)
        cache.get("k2")
        cache.get("k1")
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] >= 1
        assert "hit_rate" in stats


class TestErrorHandling:
    def test_frequency_response_handles_malformed_disturbance(self):
        result = run_frequency_response(
            _SIMPLE_NETWORK,
            disturbance={"bad_key": "no_delta_p"},
        )
        assert isinstance(result, FrequencyResponseResult)
        assert result.delta_p_mw == 0.0

    def test_short_circuit_handles_missing_fault_bus(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_short_circuit(
                _SIMPLE_NETWORK,
                fault_bus="NONEXISTENT",
                seed=42,
            )
        assert result.success
        assert isinstance(result, ShortCircuitResult)

    def test_state_estimation_handles_dict_measurements(self):
        with patch("importlib.import_module", side_effect=import_without_pandapower):
            result = run_state_estimation(
                _SIMPLE_NETWORK,
                measurements={"measurements": [
                    {"type": "voltage_mag", "bus": "Bus 1", "value": 1.0, "std": 0.01}
                ]},
                seed=42,
            )
        assert result.success
        assert isinstance(result, StateEstimationResult)
