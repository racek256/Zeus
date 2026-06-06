"""Tests for market layer - merit order, redispatch, etc."""

from datetime import datetime

from athenaai.market import (
    calculate_balancing_group,
    calculate_imbalance_pricing,
    calculate_interconnect_schedule,
    calculate_redispatch_costs,
    calculate_reserve_adequacy,
    merit_order_dispatch,
)


class TestMeritOrder:
    def test_merit_order_empty(self):
        result = merit_order_dispatch([], 0.0, {}, datetime.now())
        assert result.marginal_price_eur_mwh == 0.0
        assert len(result.dispatch_order) == 0

    def test_merit_order_single_unit(self):
        generators = [
            {
                "generator_id": "G1",
                "fuel_type": "natural_gas",
                "capacity_mw": 100.0,
                "efficiency_percent": 50.0,
            }
        ]
        fuel_prices = {"natural_gas": 30.0}
        result = merit_order_dispatch(generators, 50.0, fuel_prices, datetime.now())
        assert len(result.dispatch_order) == 1
        assert result.dispatch_order[0] == "G1"
        assert result.total_generation_mw == 50.0
        assert result.marginal_price_eur_mwh == 60.0

    def test_merit_order_multiple_units_sorted_by_cost(self):
        generators = [
            {"generator_id": "G1", "fuel_type": "lignite", "capacity_mw": 200.0, "efficiency_percent": 35.0},
            {"generator_id": "G2", "fuel_type": "natural_gas", "capacity_mw": 100.0, "efficiency_percent": 50.0},
            {"generator_id": "G3", "fuel_type": "uranium", "capacity_mw": 1000.0, "efficiency_percent": 33.0},
        ]
        fuel_prices = {"lignite": 10.0, "natural_gas": 30.0, "uranium": 5.0}
        result = merit_order_dispatch(generators, 150.0, fuel_prices, datetime.now())
        assert len(result.dispatch_order) == 3
        assert result.dispatch_order[0] == "G1"
        assert result.dispatch_order[1] == "G3"
        assert result.dispatch_order[2] == "G2"


class TestRedispatchCosts:
    def test_redispatch_empty(self):
        result = calculate_redispatch_costs([], [], {}, datetime.now())
        assert result.total_cost_eur == 0.0

    def test_redispatch_upward_only(self):
        upward = [{"generator_id": "G1", "mw": 50.0, "marginal_cost": 60.0}]
        result = calculate_redispatch_costs(upward, [], {}, datetime.now())
        assert result.upward_cost_eur == 3000.0
        assert result.total_cost_eur == 3000.0


class TestBalancingGroup:
    def test_balancing_group_balanced(self):
        scheduled = {"G1": 100.0}
        actual = {"G1": 100.0}
        result = calculate_balancing_group(scheduled, actual, "hourly", datetime.now())
        assert abs(result.deviation_mw) < 0.01

    def test_balancing_group_imbalanced(self):
        scheduled = {"G1": 100.0}
        actual = {"G1": 110.0}
        result = calculate_balancing_group(scheduled, actual, "hourly", datetime.now())
        assert result.deviation_mw == 10.0
        assert result.imbalance_eur > 0


class TestInterconnectSchedule:
    def test_interconnect_basic(self):
        borders = ["DE", "SK", "AT"]
        atc = {"DE": 1500.0, "SK": 1000.0, "AT": 800.0}
        result = calculate_interconnect_schedule(borders, atc, None, datetime.now())
        assert len(result.scheduled_flows) == 3
        assert len(result.atc_values) == 3


class TestReserveAdequacy:
    def test_reserve_adequate(self):
        headroom = {"region1": 300.0, "region2": 200.0}
        result = calculate_reserve_adequacy(headroom, 400.0, 500.0, datetime.now())
        assert result.adequate
        assert result.available_reserve_mw == 500.0
        assert result.required_reserve_mw == 500.0

    def test_reserve_inadequate(self):
        headroom = {"region1": 100.0}
        result = calculate_reserve_adequacy(headroom, 400.0, 500.0, datetime.now())
        assert not result.adequate
