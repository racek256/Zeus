"""Test deterministic tools module."""

from datetime import datetime

from athenaai.tools.physics import (
    ac_load_flow,
    optimal_power_flow,
    n1_contingency_scan,
    frequency_response,
    short_circuit,
    state_estimation,
    merit_order_dispatch,
    redispatch_cost_calculation,
    balancing_group_check,
    interconnect_schedule,
    reserve_adequacy_check,
    imbalance_pricing,
    load_forecast_15min,
    wind_nowcast,
    solar_nowcast,
    ramp_event_detector,
    day_ahead_schedule_optimization,
    temperature_to_demand,
    ev_flexible_load_model,
)


class TestPhysicsTools:
    def test_ac_load_flow_returns_structured_result(self):
        result = ac_load_flow({"buses": []}, datetime(2026, 1, 1, 0, 0, 0))
        assert "status" in result
        assert "simulated_time" in result
        assert "inputs_summary" in result
        assert "results" in result
        assert "converged" in result["results"]

    def test_optimal_power_flow_returns_structured_result(self):
        result = optimal_power_flow({"buses": []}, {}, datetime(2026, 1, 1, 0, 0, 0))
        assert "status" in result
        assert "simulated_time" in result
        assert "results" in result
        assert "generation_schedule" in result["results"]

    def test_n1_contingency_scan_returns_passed_field(self):
        result = n1_contingency_scan({"buses": []}, [{"type": "line_trip"}], datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "passed" in result["results"]
        assert "secure" in result["results"]

    def test_frequency_response_fails_when_andes_unavailable(self):
        result = frequency_response({}, {"disturbance_mw": 100}, datetime(2026, 1, 1, 0, 0, 0))
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "ANDES_UNAVAILABLE"
        assert result["results"]["required_dependency"] == "andes"

    def test_short_circuit_fails_when_wrapper_unavailable(self):
        result = short_circuit({"buses": []}, "bus1", "3ph", datetime(2026, 1, 1, 0, 0, 0))
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "PANDAPOWER_SHORTCIRCUIT_WRAPPER_UNAVAILABLE"

    def test_state_estimation_fails_when_wrapper_unavailable(self):
        result = state_estimation({}, {"num_buses": 10}, datetime(2026, 1, 1, 0, 0, 0))
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "PANDAPOWER_STATE_ESTIMATION_WRAPPER_UNAVAILABLE"


class TestMarketTools:
    def test_merit_order_dispatch_returns_dispatch_order(self):
        result = merit_order_dispatch([], {"total_load_mw": 1000}, {}, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "dispatch_order" in result["results"]

    def test_redispatch_cost_calculation_returns_costs(self):
        result = redispatch_cost_calculation([], [], datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "upward_cost_eur" in result["results"]
        assert "downward_cost_eur" in result["results"]

    def test_balancing_group_check_returns_deviation(self):
        result = balancing_group_check({"name": "test-group"}, "hourly", datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "deviation_mw" in result["results"]

    def test_interconnect_schedule_returns_flows(self):
        result = interconnect_schedule(["DE", "AT"], {}, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "scheduled_flows" in result["results"]

    def test_reserve_adequacy_check_returns_adequate_flag(self):
        result = reserve_adequacy_check({"mw": 500}, {}, 0.1, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "adequate" in result["results"]

    def test_imbalance_pricing_returns_price(self):
        result = imbalance_pricing([], {}, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "imbalance_price_eur_mwh" in result["results"]


class TestForecastTools:
    def test_load_forecast_15min_returns_quantiles(self):
        result = load_forecast_15min([], 15.0, {}, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "TIMESFM_UNAVAILABLE"
        assert result["results"]["required_dependency"] == "timesfm"

    def test_wind_nowcast_returns_capacity_factor(self):
        result = wind_nowcast({"horizon_h": 1, "wind_speed_ms": 10}, None, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "TIMESFM_UNAVAILABLE"

    def test_solar_nowcast_returns_capacity_factor(self):
        result = solar_nowcast({"horizon_h": 1, "irradiance_wm2": 500}, None, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "TIMESFM_UNAVAILABLE"

    def test_ramp_event_detector_returns_direction(self):
        result = ramp_event_detector(
            [
                {"hour_index": 0, "generation_mw": 100.0},
                {"hour_index": 2, "generation_mw": 360.0},
            ],
            100.0,
            datetime(2026, 1, 1, 0, 0, 0),
        )
        assert result["status"]["success"] is True
        assert "results" in result
        assert result["results"]["ramp_detected"] is True
        assert result["results"]["ramp_direction"] == "up"

    def test_day_ahead_schedule_optimization_returns_hourly_schedule(self):
        result = day_ahead_schedule_optimization({}, [], {}, datetime(2026, 1, 1, 0, 0, 0))
        assert "results" in result
        assert "hourly_schedule" in result["results"]

    def test_temperature_to_demand_returns_sensitivity(self):
        result = temperature_to_demand(15.0, "bohemia-west", "weekday", 12, datetime(2026, 1, 1, 0, 0, 0))
        assert result["status"]["success"] is True
        assert "results" in result
        assert result["results"]["demand_mw"] > 900.0
        assert result["results"]["temperature_sensitivity_mw_per_c"] == -18.0

    def test_ev_flexible_load_model_returns_flexible_capacity(self):
        result = ev_flexible_load_model(1000, 0.8, {"average_kw_per_point": 7.4}, datetime(2026, 1, 1, 0, 0, 0))
        assert result["status"]["success"] is True
        assert "results" in result
        assert result["results"]["flexible_capacity_mw"] == 5.92


class TestToolsDeterminism:
    def test_same_inputs_produce_same_outputs(self):
        network_state = {"buses": []}
        time = datetime(2026, 1, 1, 0, 0, 0)
        result1 = ac_load_flow(network_state, time)
        result2 = ac_load_flow(network_state, time)
        assert result1["results"] == result2["results"]
        assert result1["status"] == result2["status"]

    def test_tools_do_not_mutate_inputs(self):
        network_state = {"buses": [], "key": "original"}
        time = datetime(2026, 1, 1, 0, 0, 0)
        ac_load_flow(network_state, time)
        assert network_state["key"] == "original"


class TestToolsInputsSummary:
    def test_all_tools_include_inputs_in_summary(self):
        tools_with_time = [
            (ac_load_flow, [{"buses": []}, datetime(2026, 1, 1)]),
            (optimal_power_flow, [{"buses": []}, {}, datetime(2026, 1, 1)]),
            (n1_contingency_scan, [{"buses": []}, [], datetime(2026, 1, 1)]),
        ]
        for tool, args in tools_with_time:
            result = tool(*args)
            assert "inputs_summary" in result
