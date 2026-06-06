"""Tests for schema validation - observation/action bundles."""

from datetime import datetime

from athenaai.schema import (
    ActionBundle,
    ActionValidationResult,
    BusReading,
    BranchReading,
    GeneratorReading,
    GeneratorSetpointChange,
    InterconnectFlowAdjustment,
    LoadForecastBundle,
    LoadReading,
    LoadSheddingFlag,
    MarketState,
    NetworkConstraints,
    ObservationBundle,
    RedispatchRequest,
    RenewablesForecastBundle,
    ScadaSnapshot,
    validate_action_bundle,
)


class TestObservationBundle:
    def test_scada_snapshot_basic(self):
        scada = ScadaSnapshot(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            buses=(BusReading(bus_id="B1", voltage_pu=1.0, voltage_angle_deg=0.0),),
            branches=(),
            generators=(),
            loads=(),
            total_generation_mw=0.0,
            total_load_mw=0.0,
        )
        assert scada.get_bus("B1") is not None
        assert scada.get_bus("B999") is None

    def test_observation_bundle_no_violations(self):
        constraints = NetworkConstraints()
        scada = ScadaSnapshot(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            buses=(BusReading(bus_id="B1", voltage_pu=1.0, voltage_angle_deg=0.0),),
            branches=(BranchReading(branch_id="L1", from_bus="B1", to_bus="B2", flow_mw=50.0, loading_percent=50.0),),
            generators=(),
            loads=(),
        )
        market = MarketState(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            system_marginal_price_eur_mwh=50.0,
            imbalance_price_eur_mwh=55.0,
            total_reserve_mw=500.0,
            reserve_requirement_mw=400.0,
        )
        obs = ObservationBundle(
            hour_index=0,
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            scada=scada,
            load_forecasts=(),
            renewables_forecasts=(),
            network_constraints=constraints,
            market_state=market,
        )
        assert not obs.has_violations()

    def test_observation_bundle_voltage_violation(self):
        constraints = NetworkConstraints(min_voltage_pu=0.95, max_voltage_pu=1.05)
        scada = ScadaSnapshot(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            buses=(BusReading(bus_id="B1", voltage_pu=0.90, voltage_angle_deg=0.0),),
            branches=(),
            generators=(),
            loads=(),
        )
        market = MarketState(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            system_marginal_price_eur_mwh=50.0,
            imbalance_price_eur_mwh=55.0,
            total_reserve_mw=500.0,
            reserve_requirement_mw=400.0,
        )
        obs = ObservationBundle(
            hour_index=0,
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            scada=scada,
            load_forecasts=(),
            renewables_forecasts=(),
            network_constraints=constraints,
            market_state=market,
        )
        assert obs.has_violations()


class TestActionValidation:
    def test_validate_empty_action(self):
        constraints = NetworkConstraints()
        scada = ScadaSnapshot(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            buses=(BusReading(bus_id="B1", voltage_pu=1.0, voltage_angle_deg=0.0),),
            branches=(),
            generators=(GeneratorReading(generator_id="G1", bus="B1", generation_mw=100.0, setpoint_mw=100.0),),
            loads=(LoadReading(load_id="L1", bus="B1", demand_mw=50.0),),
        )
        market = MarketState(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            system_marginal_price_eur_mwh=50.0,
            imbalance_price_eur_mwh=55.0,
            total_reserve_mw=500.0,
            reserve_requirement_mw=400.0,
            atc_values={"DE": 1500.0},
        )
        obs = ObservationBundle(
            hour_index=0,
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            scada=scada,
            load_forecasts=(),
            renewables_forecasts=(),
            network_constraints=constraints,
            market_state=market,
        )
        action = ActionBundle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            agent_id="coordinator",
        )
        result = validate_action_bundle(action, obs)
        assert result.valid
        assert len(result.errors) == 0

    def test_validate_unknown_generator(self):
        constraints = NetworkConstraints()
        scada = ScadaSnapshot(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            buses=(BusReading(bus_id="B1", voltage_pu=1.0, voltage_angle_deg=0.0),),
            branches=(),
            generators=(GeneratorReading(generator_id="G1", bus="B1", generation_mw=100.0, setpoint_mw=100.0),),
            loads=(),
        )
        market = MarketState(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            system_marginal_price_eur_mwh=50.0,
            imbalance_price_eur_mwh=55.0,
            total_reserve_mw=500.0,
            reserve_requirement_mw=400.0,
        )
        obs = ObservationBundle(
            hour_index=0,
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            scada=scada,
            load_forecasts=(),
            renewables_forecasts=(),
            network_constraints=constraints,
            market_state=market,
        )
        action = ActionBundle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            agent_id="coordinator",
            generator_setpoint_changes=(GeneratorSetpointChange(generator_id="G999", new_setpoint_mw=150.0),),
        )
        result = validate_action_bundle(action, obs)
        assert not result.valid
        assert any("Unknown generator" in e for e in result.errors)

    def test_validate_excessive_load_shed(self):
        constraints = NetworkConstraints()
        scada = ScadaSnapshot(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            buses=(BusReading(bus_id="B1", voltage_pu=1.0, voltage_angle_deg=0.0),),
            branches=(),
            generators=(),
            loads=(LoadReading(load_id="L1", bus="B1", demand_mw=50.0),),
        )
        market = MarketState(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            system_marginal_price_eur_mwh=50.0,
            imbalance_price_eur_mwh=55.0,
            total_reserve_mw=500.0,
            reserve_requirement_mw=400.0,
        )
        obs = ObservationBundle(
            hour_index=0,
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            scada=scada,
            load_forecasts=(),
            renewables_forecasts=(),
            network_constraints=constraints,
            market_state=market,
        )
        action = ActionBundle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            agent_id="coordinator",
            load_shedding_flags=(LoadSheddingFlag(load_id="L1", region="bohemia-west", shed_mw=100.0),),
        )
        result = validate_action_bundle(action, obs)
        assert not result.valid
        assert any("exceeds demand" in e for e in result.errors)

    def test_validate_interconnect_atc_violation(self):
        constraints = NetworkConstraints()
        scada = ScadaSnapshot(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            buses=(),
            branches=(),
            generators=(),
            loads=(),
        )
        market = MarketState(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            system_marginal_price_eur_mwh=50.0,
            imbalance_price_eur_mwh=55.0,
            total_reserve_mw=500.0,
            reserve_requirement_mw=400.0,
            atc_values={"DE": 100.0},
        )
        obs = ObservationBundle(
            hour_index=0,
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            scada=scada,
            load_forecasts=(),
            renewables_forecasts=(),
            network_constraints=constraints,
            market_state=market,
        )
        action = ActionBundle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            agent_id="coordinator",
            interconnect_flow_adjustments=(InterconnectFlowAdjustment(border="DE", target_flow_mw=200.0, current_flow_mw=0.0),),
        )
        result = validate_action_bundle(action, obs)
        assert not result.valid
        assert any("exceeds ATC" in e for e in result.errors)


class TestActionBundle:
    def test_action_bundle_is_empty(self):
        empty = ActionBundle(timestamp=datetime.now(), agent_id="test")
        assert empty.is_empty()

        non_empty = ActionBundle(
            timestamp=datetime.now(),
            agent_id="test",
            generator_setpoint_changes=(GeneratorSetpointChange(generator_id="G1", new_setpoint_mw=100.0),),
        )
        assert not non_empty.is_empty()
