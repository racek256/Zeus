"""Tests for new AthenaAI tools added in Phase 2.x.

Tests cover: carbon_intensity_calculation, renewable_curtailment_analysis,
transmission_congestion_monitor, voltage_stability_margin, demand_response_potential,
black_start_capability, synchrophasor_monitor, weather_impact_assessment.
"""

from datetime import datetime

from athenaai.tools.physics import (
    black_start_capability,
    carbon_intensity_calculation,
    demand_response_potential,
    renewable_curtailment_analysis,
    synchrophasor_monitor,
    transmission_congestion_monitor,
    voltage_stability_margin,
    weather_impact_assessment,
)

_SIM_TIME = datetime(2026, 6, 6, 12, 0, 0)


class TestCarbonIntensity:
    def test_returns_structured_result(self):
        result = carbon_intensity_calculation(
            {"coal": 500.0, "nuclear": 1000.0, "wind": 200.0},
            total_demand_mw=1700.0,
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True
        assert "total_emissions_t_h" in result["results"]
        assert "intensity_g_co2_kwh" in result["results"]
        assert "generation_mix" in result["results"]

    def test_zero_emission_energy_has_no_emissions(self):
        result = carbon_intensity_calculation(
            {"nuclear": 1000.0, "wind": 500.0, "solar": 300.0},
            total_demand_mw=1800.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["total_emissions_t_h"] == 0.0
        assert result["results"]["intensity_g_co2_kwh"] == 0.0

    def test_coal_generates_high_emissions(self):
        result = carbon_intensity_calculation(
            {"coal": 1000.0},
            total_demand_mw=1000.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["total_emissions_t_h"] > 0.0
        assert result["results"]["intensity_g_co2_kwh"] > 500.0

    def test_with_carbon_price_returns_cost(self):
        result = carbon_intensity_calculation(
            {"natural_gas": 500.0},
            total_demand_mw=500.0,
            carbon_price_eur_t=80.0,
            simulated_time=_SIM_TIME,
        )
        assert "emission_cost_eur_h" in result["results"]
        assert "carbon_price_eur_t" in result["results"]

    def test_empty_generation_mix_fails(self):
        result = carbon_intensity_calculation(
            {},
            total_demand_mw=1000.0,
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "EMPTY_GENERATION_MIX"

    def test_uncertainty_included(self):
        result = carbon_intensity_calculation(
            {"coal": 500.0},
            total_demand_mw=500.0,
            simulated_time=_SIM_TIME,
        )
        assert "uncertainty" in result
        assert "co2_factor_std_g_kwh" in result["uncertainty"]


class TestRenewableCurtailment:
    def test_returns_structured_result(self):
        result = renewable_curtailment_analysis(
            {"wind": 300.0, "solar": 200.0},
            {"wind": 200.0, "solar": 150.0},
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True
        assert "total_available_mw" in result["results"]
        assert "total_curtailed_mw" in result["results"]
        assert "curtailment_percent" in result["results"]

    def test_no_curtailment_when_full_dispatch(self):
        result = renewable_curtailment_analysis(
            {"wind": 300.0, "solar": 200.0},
            {"wind": 300.0, "solar": 200.0},
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["total_curtailed_mw"] == 0.0
        assert result["results"]["curtailment_percent"] == 0.0

    def test_partial_curtailment(self):
        result = renewable_curtailment_analysis(
            {"wind": 400.0},
            {"wind": 250.0},
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["total_curtailed_mw"] == 150.0
        assert result["results"]["curtailment_percent"] == 37.5

    def test_with_market_price_returns_revenue_loss(self):
        result = renewable_curtailment_analysis(
            {"wind": 400.0},
            {"wind": 300.0},
            market_price_eur_mwh=100.0,
            simulated_time=_SIM_TIME,
        )
        assert "potential_revenue_loss_eur_h" in result["results"]
        assert result["results"]["potential_revenue_loss_eur_h"] == 10000.0

    def test_with_grid_constraints_identifies_reasons(self):
        result = renewable_curtailment_analysis(
            {"wind": 400.0},
            {"wind": 300.0},
            grid_constraints={"congested": True, "voltage_violation": False},
            simulated_time=_SIM_TIME,
        )
        assert "transmission_congestion" in result["results"]["reasons"]

    def test_empty_data_fails(self):
        result = renewable_curtailment_analysis(
            {},
            {},
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "EMPTY_RENEWABLE_DATA"


class TestTransmissionCongestion:
    def test_returns_structured_result_with_branch_flows(self):
        branch_flows = {
            "line_1": {"from": "bus_a", "to": "bus_b", "loading_pct": 95.0},
            "line_2": {"from": "bus_b", "to": "bus_c", "loading_pct": 45.0},
            "line_3": {"from": "bus_c", "to": "bus_d", "loading_pct": 105.0},
        }
        result = transmission_congestion_monitor(
            {"buses": [], "branches": []},
            branch_flows=branch_flows,
            loading_threshold_pct=80.0,
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True
        assert "congested_lines" in result["results"]
        assert result["results"]["num_congested"] == 2
        assert "severity_summary" in result["results"]

    def test_critical_lines_detected(self):
        branch_flows = {
            "line_1": {"from": "a", "to": "b", "loading_pct": 110.0},
        }
        result = transmission_congestion_monitor(
            {"buses": [], "branches": []},
            branch_flows=branch_flows,
            loading_threshold_pct=80.0,
            simulated_time=_SIM_TIME,
        )
        congested = result["results"]["congested_lines"]
        assert len(congested) == 1
        assert congested[0]["severity"] == "critical"
        assert result["results"]["severity_summary"]["critical"] == 1

    def test_no_congestion_when_below_threshold(self):
        branch_flows = {
            "line_1": {"from": "a", "to": "b", "loading_pct": 50.0},
        }
        result = transmission_congestion_monitor(
            {"buses": [], "branches": []},
            branch_flows=branch_flows,
            loading_threshold_pct=80.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["num_congested"] == 0

    def test_estimates_from_branch_metadata(self):
        network_state = {
            "buses": [],
            "branches": [
                {
                    "branch_id": "l1",
                    "from_bus": "a",
                    "to_bus": "b",
                    "p_mw": 90.0,
                    "rating_mva": 100.0,
                },
            ],
        }
        result = transmission_congestion_monitor(
            network_state,
            loading_threshold_pct=80.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["num_congested"] == 1

    def test_no_branch_data_fails(self):
        result = transmission_congestion_monitor(
            {"buses": []},
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "NO_BRANCH_DATA"


class TestVoltageStability:
    def test_returns_structured_result(self):
        result = voltage_stability_margin(
            {"buses": [{"bus_id": "b1", "vn_kv": 110.0}], "generators": [], "loads": []},
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True
        assert "margin_pu" in result["results"]
        assert "stability_index" in result["results"]
        assert "stability_level" in result["results"]

    def test_with_reactive_reserves(self):
        reactive_reserves = {"gen_1": 50.0, "gen_2": 30.0}
        result = voltage_stability_margin(
            {"buses": [], "generators": [], "loads": []},
            reactive_reserves=reactive_reserves,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["reactive_reserve_mvar"] == 80.0

    def test_with_bus_voltages_finds_minimum(self):
        bus_voltages = {
            "bus_a": {"vm_pu": 1.02, "va_deg": 5.0},
            "bus_b": {"vm_pu": 0.88, "va_deg": -2.0},
            "bus_c": {"vm_pu": 0.95, "va_deg": 1.0},
        }
        result = voltage_stability_margin(
            {"buses": [], "generators": [], "loads": [{"p_mw": 500.0}]},
            bus_voltages=bus_voltages,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["min_voltage_pu"] == 0.88
        assert result["results"]["min_voltage_bus"] == "bus_b"

    def test_stable_system_high_margin(self):
        bus_voltages = {
            "bus_a": {"vm_pu": 1.10, "va_deg": 3.0},
            "bus_b": {"vm_pu": 1.08, "va_deg": 2.0},
        }
        result = voltage_stability_margin(
            {"buses": [], "generators": [], "loads": [{"p_mw": 100.0}]},
            bus_voltages=bus_voltages,
            reactive_reserves={"g1": 500.0},
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["stability_level"] == "stable"


class TestDemandResponse:
    def test_returns_structured_result(self):
        result = demand_response_potential(
            industrial_loads=[
                {"load_id": "steel_mill_1", "sheddable_mw": 50.0, "response_time_min": 10.0, "cost_eur_mw": 120.0},
            ],
            ev_flexible_capacity_mw=20.0,
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True
        assert "total_potential_mw" in result["results"]
        assert "response_time_min" in result["results"]
        assert "cost_per_mw_eur" in result["results"]

    def test_ev_only(self):
        result = demand_response_potential(
            ev_flexible_capacity_mw=15.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["total_potential_mw"] == 15.0
        assert result["results"]["ev_potential_mw"] == 15.0

    def test_industrial_only(self):
        result = demand_response_potential(
            industrial_loads=[
                {"load_id": "factory_1", "sheddable_mw": 30.0, "response_time_min": 5.0, "cost_eur_mw": 80.0},
                {"load_id": "factory_2", "sheddable_mw": 40.0, "response_time_min": 15.0, "cost_eur_mw": 100.0},
            ],
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["total_potential_mw"] == 70.0
        assert result["results"]["industrial_potential_mw"] == 70.0

    def test_region_filter(self):
        result = demand_response_potential(
            industrial_loads=[
                {"load_id": "mill_a", "region": "bohemia-east", "sheddable_mw": 20.0, "response_time_min": 10.0, "cost_eur_mw": 100.0},
                {"load_id": "mill_b", "region": "moravia", "sheddable_mw": 30.0, "response_time_min": 10.0, "cost_eur_mw": 100.0},
            ],
            region="moravia",
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["industrial_potential_mw"] == 30.0

    def test_includes_ev_in_load_categories(self):
        result = demand_response_potential(
            industrial_loads=[
                {"load_id": "plant_1", "sheddable_mw": 10.0, "response_time_min": 5.0, "cost_eur_mw": 90.0},
            ],
            ev_flexible_capacity_mw=10.0,
            simulated_time=_SIM_TIME,
        )
        categories = result["results"]["load_categories"]
        assert len(categories) == 2
        types = {c["type"] for c in categories}
        assert types == {"industrial", "ev"}


class TestBlackStart:
    def test_returns_structured_result(self):
        generators = [
            {"generator_id": "hydro_1", "fuel_type": "hydro", "p_mw": 100.0},
            {"generator_id": "coal_1", "fuel_type": "coal", "p_mw": 200.0},
        ]
        result = black_start_capability(generators, simulated_time=_SIM_TIME)
        assert result["status"]["success"] is True
        assert "capable_generators" in result["results"]
        assert "sequence_recommendation" in result["results"]

    def test_hydro_is_black_start_capable(self):
        generators = [
            {"generator_id": "hydro_1", "fuel_type": "hydro", "p_mw": 100.0},
        ]
        result = black_start_capability(generators, simulated_time=_SIM_TIME)
        capable = result["results"]["capable_generators"]
        assert len(capable) == 1
        assert capable[0]["generator_id"] == "hydro_1"

    def test_coal_is_not_black_start_capable(self):
        generators = [
            {"generator_id": "coal_1", "fuel_type": "coal", "p_mw": 300.0},
        ]
        result = black_start_capability(generators, simulated_time=_SIM_TIME)
        assert len(result["results"]["capable_generators"]) == 0

    def test_gas_turbine_is_black_start_capable(self):
        generators = [
            {"generator_id": "gt_1", "fuel_type": "gas", "p_mw": 50.0},
        ]
        result = black_start_capability(generators, simulated_time=_SIM_TIME)
        assert len(result["results"]["capable_generators"]) == 1

    def test_explicit_black_start_flag_overrides_type(self):
        generators = [
            {"generator_id": "coal_bs", "fuel_type": "coal", "p_mw": 200.0, "black_start_capable": True},
        ]
        result = black_start_capability(generators, simulated_time=_SIM_TIME)
        assert len(result["results"]["capable_generators"]) == 1

    def test_hydro_fastest_start_time(self):
        generators = [
            {"generator_id": "hydro_1", "fuel_type": "hydro", "p_mw": 100.0},
            {"generator_id": "ccgt_1", "fuel_type": "ccgt", "p_mw": 200.0},
        ]
        result = black_start_capability(generators, simulated_time=_SIM_TIME)
        sequence = result["results"]["sequence_recommendation"]
        assert sequence[0]["generator_id"] == "hydro_1"  # hydro starts first (5 min vs 20 min)

    def test_empty_generators_fails(self):
        result = black_start_capability([], simulated_time=_SIM_TIME)
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "NO_GENERATOR_DATA"

    def test_black_start_ratio_calculated(self):
        generators = [
            {"generator_id": "hydro_1", "fuel_type": "hydro", "p_mw": 100.0},
            {"generator_id": "coal_1", "fuel_type": "coal", "p_mw": 400.0},
        ]
        result = black_start_capability(generators, simulated_time=_SIM_TIME)
        assert result["results"]["black_start_ratio_pct"] == 20.0


class TestSynchrophasor:
    def test_returns_structured_result(self):
        bus_voltages = {
            "bus_a": {"vm_pu": 1.02, "va_deg": 5.0},
            "bus_b": {"vm_pu": 1.01, "va_deg": 3.0},
            "bus_c": {"vm_pu": 0.99, "va_deg": 1.0},
        }
        result = synchrophasor_monitor(
            bus_voltages=bus_voltages,
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True
        assert "pmu_count" in result["results"]
        assert "islanding_risk" in result["results"]
        assert "angle_differences" in result["results"]

    def test_normal_angles_low_islanding_risk(self):
        bus_voltages = {
            "bus_a": {"vm_pu": 1.02, "va_deg": 5.0},
            "bus_b": {"vm_pu": 1.01, "va_deg": 3.0},
        }
        result = synchrophasor_monitor(
            bus_voltages=bus_voltages,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["islanding_risk"] == "low"

    def test_large_angle_difference_high_islanding_risk(self):
        bus_voltages = {
            "bus_a": {"vm_pu": 1.02, "va_deg": 40.0},
            "bus_b": {"vm_pu": 0.98, "va_deg": 5.0},
        }
        result = synchrophasor_monitor(
            bus_voltages=bus_voltages,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["islanding_risk"] == "high"

    def test_with_pmu_locations(self):
        bus_voltages = {
            f"bus_{i}": {"vm_pu": 1.0, "va_deg": float(i)} for i in range(10)
        }
        result = synchrophasor_monitor(
            bus_voltages=bus_voltages,
            pmu_locations=["bus_0", "bus_1", "bus_2"],
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["pmu_count"] == 3

    def test_no_voltage_data_fails(self):
        result = synchrophasor_monitor(
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is False
        assert result["status"]["error_code"] == "NO_VOLTAGE_DATA"


class TestWeatherImpact:
    def test_returns_structured_result(self):
        result = weather_impact_assessment(
            temperature_c=15.0,
            wind_speed_ms=8.0,
            solar_irradiance_wm2=600.0,
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True
        assert "demand_impact_mw" in result["results"]
        assert "generation_impact_mw" in result["results"]
        assert "overall_risk_level" in result["results"]

    def test_cold_temperature_increases_demand(self):
        result = weather_impact_assessment(
            temperature_c=0.0,
            wind_speed_ms=5.0,
            solar_irradiance_wm2=400.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["demand_impact_mw"] > 0
        assert result["results"]["demand_direction"] == "increase"

    def test_hot_temperature_increases_demand(self):
        result = weather_impact_assessment(
            temperature_c=35.0,
            wind_speed_ms=5.0,
            solar_irradiance_wm2=800.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["demand_impact_mw"] > 0
        assert result["results"]["demand_direction"] == "increase"

    def test_mild_temperature_neutral_demand(self):
        result = weather_impact_assessment(
            temperature_c=20.0,
            wind_speed_ms=5.0,
            solar_irradiance_wm2=500.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["demand_direction"] == "neutral"

    def test_high_wind_generates_power(self):
        result = weather_impact_assessment(
            temperature_c=20.0,
            wind_speed_ms=12.0,
            solar_irradiance_wm2=500.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["wind_capacity_factor_pct"] > 50.0

    def test_storm_risk_with_high_wind(self):
        result = weather_impact_assessment(
            temperature_c=20.0,
            wind_speed_ms=28.0,
            solar_irradiance_wm2=500.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["storm_risk"] == "severe"

    def test_icing_risk_with_cold_and_wind(self):
        result = weather_impact_assessment(
            temperature_c=-2.0,
            wind_speed_ms=10.0,
            solar_irradiance_wm2=300.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["icing_risk"] == "moderate"

    def test_high_temperature_derates_lines(self):
        result = weather_impact_assessment(
            temperature_c=40.0,
            wind_speed_ms=2.0,
            solar_irradiance_wm2=900.0,
            simulated_time=_SIM_TIME,
        )
        assert result["results"]["line_rating_impact_pct"] < 0  # derating = negative impact

    def test_region_specific_base_demand(self):
        result = weather_impact_assessment(
            temperature_c=15.0,
            wind_speed_ms=5.0,
            solar_irradiance_wm2=500.0,
            region="bohemia-east",
            simulated_time=_SIM_TIME,
        )
        assert result["status"]["success"] is True


class TestNewToolsDeterminism:
    def test_carbon_intensity_deterministic(self):
        args = ({"coal": 500.0}, 500.0, None, _SIM_TIME)
        r1 = carbon_intensity_calculation(*args)
        r2 = carbon_intensity_calculation(*args)
        assert r1["results"] == r2["results"]

    def test_weather_impact_deterministic(self):
        args = (15.0, 8.0, 600.0, "all", None, _SIM_TIME)
        r1 = weather_impact_assessment(*args)
        r2 = weather_impact_assessment(*args)
        assert r1["results"] == r2["results"]

    def test_voltage_stability_deterministic(self):
        args = ({"buses": [], "generators": [], "loads": []}, None, None, _SIM_TIME)
        r1 = voltage_stability_margin(*args)
        r2 = voltage_stability_margin(*args)
        assert r1["results"] == r2["results"]


class TestNewToolsInputsSummary:
    def test_all_new_tools_include_inputs_summary(self):
        tools_with_args = [
            (carbon_intensity_calculation, [{"coal": 100.0}, 100.0, None, _SIM_TIME]),
            (renewable_curtailment_analysis, [{"wind": 100.0}, {"wind": 80.0}, None, None, _SIM_TIME]),
            (transmission_congestion_monitor, [{"buses": [], "branches": []}, None, 80.0, _SIM_TIME]),
            (voltage_stability_margin, [{"buses": [], "generators": [], "loads": []}, None, None, _SIM_TIME]),
            (demand_response_potential, [[], 0.0, "all", _SIM_TIME]),
            (black_start_capability, [[{"generator_id": "h1", "fuel_type": "hydro", "p_mw": 50.0}], None, _SIM_TIME]),
            (weather_impact_assessment, [15.0, 5.0, 500.0, "all", None, _SIM_TIME]),
        ]
        for tool, args in tools_with_args:
            result = tool(*args)
            assert "inputs_summary" in result, f"{tool.__name__} missing inputs_summary"
            assert "status" in result
            assert "results" in result
