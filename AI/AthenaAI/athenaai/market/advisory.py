"""Advisory market layer - EU/Czech market approximations.

All functions are pure/deterministic. They return recommendations/costs
but never mutate physics state. Coordinator must validate through physics tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


_FUEL_PRIORITY: dict[str, int] = {
    "lignite": 0,
    "coal": 0,
    "steam_coal": 0,
    "uranium": 1,
    "nuclear": 1,
    "biomass": 2,
    "natural_gas": 3,
    "gas": 3,
    "oil": 4,
}


@dataclass(frozen=True)
class MeritOrderResult:
    dispatch_order: tuple[str, ...]
    marginal_price_eur_mwh: float
    total_generation_mw: float
    unit_dispatch: tuple[tuple[str, float], ...]
    unit_marginal_costs: tuple[tuple[str, float], ...]
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class RedispatchCostResult:
    upward_cost_eur: float
    downward_cost_eur: float
    total_cost_eur: float
    upward_volumes: tuple[tuple[str, float], ...]
    downward_volumes: tuple[tuple[str, float], ...]
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class BalancingGroupResult:
    deviation_mw: float
    imbalance_eur: float
    per_region_deviations: tuple[tuple[str, float], ...]
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class InterconnectScheduleResult:
    scheduled_flows: tuple[tuple[str, float], ...]
    atc_values: tuple[tuple[str, float], ...]
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ReserveAdequacyResult:
    available_reserve_mw: float
    required_reserve_mw: float
    adequate: bool
    largest_contingency_mw: float
    headroom_by_region: tuple[tuple[str, float], ...]
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ImbalancePricingResult:
    system_imbalance_mw: float
    imbalance_price_eur_mwh: float
    activated_balancing: tuple[tuple[str, float], ...]
    message: str
    timestamp: datetime | None = None


def _estimate_marginal_cost(
    generator: dict[str, Any], fuel_prices: dict[str, float]
) -> float:
    fuel_type = generator.get("fuel_type", "unknown")
    efficiency = generator.get("efficiency_percent", 40.0) / 100.0
    fuel_price = fuel_prices.get(fuel_type, 50.0)
    if efficiency <= 0:
        efficiency = 0.4
    return fuel_price / efficiency


def merit_order_dispatch(
    generator_data: list[dict[str, Any]],
    load_forecast_mw: float,
    fuel_prices: dict[str, Any],
    simulated_time: datetime | None = None,
) -> MeritOrderResult:
    fuel_price_map: dict[str, float] = {
        k: float(v) for k, v in fuel_prices.items()
    }

    units_with_cost: list[tuple[str, float, float, int]] = []
    for g in generator_data:
        gid = g.get("generator_id", g.get("name", "unknown"))
        capacity = g.get("capacity_mw", g.get("max_p_mw", 100.0))
        marginal_cost = _estimate_marginal_cost(g, fuel_price_map)
        fuel_type = str(g.get("fuel_type", "unknown"))
        priority = _FUEL_PRIORITY.get(fuel_type, 99)
        units_with_cost.append((gid, marginal_cost, capacity, priority))

    units_with_cost.sort(key=lambda x: (x[3], x[1], x[0]))

    dispatch_order: list[str] = [gid for gid, _mc, _capacity, _priority in units_with_cost]
    unit_dispatch: list[tuple[str, float]] = []
    unit_marginal_costs: list[tuple[str, float]] = []
    total_generation = 0.0
    marginal_price = 0.0

    remaining_load = load_forecast_mw
    for gid, mc, capacity, _priority in units_with_cost:
        unit_marginal_costs.append((gid, mc))
        dispatched = min(capacity, remaining_load)
        unit_dispatch.append((gid, dispatched))
        total_generation += dispatched
        if dispatched > 0:
            marginal_price = mc
        remaining_load -= dispatched
        if remaining_load <= 0:
            remaining_load = 0.0

    return MeritOrderResult(
        dispatch_order=tuple(dispatch_order),
        marginal_price_eur_mwh=marginal_price,
        total_generation_mw=total_generation,
        unit_dispatch=tuple(unit_dispatch),
        unit_marginal_costs=tuple(unit_marginal_costs),
        message=f"Merit order dispatch: {len(dispatch_order)} units, marginal price {marginal_price:.2f}",
        timestamp=simulated_time,
    )


def calculate_redispatch_costs(
    upward_adjustments: list[dict[str, Any]],
    downward_adjustments: list[dict[str, Any]],
    fuel_prices: dict[str, Any],
    simulated_time: datetime | None = None,
) -> RedispatchCostResult:
    fuel_price_map: dict[str, float] = {
        k: float(v) for k, v in fuel_prices.items()
    }

    upward_cost = 0.0
    upward_volumes: list[tuple[str, float]] = []
    for adj in upward_adjustments:
        gid = adj.get("generator_id", "unknown")
        mw = adj.get("mw", 0.0)
        marginal_cost = adj.get("marginal_cost", 50.0)
        upward_cost += mw * marginal_cost
        upward_volumes.append((gid, mw))

    downward_cost = 0.0
    downward_volumes: list[tuple[str, float]] = []
    for adj in downward_adjustments:
        gid = adj.get("generator_id", "unknown")
        mw = adj.get("mw", 0.0)
        marginal_cost = adj.get("marginal_cost", 50.0)
        downward_cost += mw * marginal_cost
        downward_volumes.append((gid, mw))

    return RedispatchCostResult(
        upward_cost_eur=upward_cost,
        downward_cost_eur=downward_cost,
        total_cost_eur=upward_cost + downward_cost,
        upward_volumes=tuple(upward_volumes),
        downward_volumes=tuple(downward_volumes),
        message=f"Redispatch cost: upward {upward_cost:.2f}, downward {downward_cost:.2f}",
        timestamp=simulated_time,
    )


def calculate_balancing_group(
    scheduled_generation: dict[str, float],
    actual_generation: dict[str, float],
    settlement_interval: str,
    simulated_time: datetime | None = None,
) -> BalancingGroupResult:
    total_deviation = 0.0
    per_region: list[tuple[str, float]] = []

    for gid in scheduled_generation:
        sched = scheduled_generation.get(gid, 0.0)
        actual = actual_generation.get(gid, 0.0)
        dev = actual - sched
        total_deviation += dev
        per_region.append((gid, dev))

    imbalance_price = 55.0
    imbalance_eur = abs(total_deviation) * imbalance_price

    return BalancingGroupResult(
        deviation_mw=total_deviation,
        imbalance_eur=imbalance_eur,
        per_region_deviations=tuple(per_region),
        message=f"Balancing group deviation: {total_deviation:.1f}MW, cost {imbalance_eur:.2f}",
        timestamp=simulated_time,
    )


def calculate_interconnect_schedule(
    borders: list[str],
    atc_constraints: dict[str, float],
    current_flows: dict[str, float] | None = None,
    simulated_time: datetime | None = None,
) -> InterconnectScheduleResult:
    flows: list[tuple[str, float]] = []
    atc_vals: list[tuple[str, float]] = []

    for border in borders:
        atc = atc_constraints.get(border, 0.0)
        flow = current_flows.get(border, 0.0) if current_flows else 0.0
        flows.append((border, flow))
        atc_vals.append((border, atc))

    return InterconnectScheduleResult(
        scheduled_flows=tuple(flows),
        atc_values=tuple(atc_vals),
        message=f"Interconnect schedule for {len(borders)} borders",
        timestamp=simulated_time,
    )


def calculate_reserve_adequacy(
    available_headroom: dict[str, float],
    largest_contingency_mw: float,
    reserve_margin_target: float,
    simulated_time: datetime | None = None,
) -> ReserveAdequacyResult:
    total_available = sum(available_headroom.values())
    required = max(largest_contingency_mw, reserve_margin_target)
    adequate = total_available >= required

    headroom_by_region: list[tuple[str, float]] = [
        (region, mw) for region, mw in available_headroom.items()
    ]

    return ReserveAdequacyResult(
        available_reserve_mw=total_available,
        required_reserve_mw=required,
        adequate=adequate,
        largest_contingency_mw=largest_contingency_mw,
        headroom_by_region=tuple(headroom_by_region),
        message=f"Reserve adequacy: available {total_available:.1f}MW, required {required:.1f}MW",
        timestamp=simulated_time,
    )


def calculate_imbalance_pricing(
    activated_balancing: list[dict[str, Any]],
    system_imbalance_mw: float,
    marginal_prices: dict[str, float] | None = None,
    simulated_time: datetime | None = None,
) -> ImbalancePricingResult:
    activated: list[tuple[str, float]] = []
    total_cost = 0.0

    for ab in activated_balancing:
        gid = ab.get("generator_id", "unknown")
        mw = ab.get("mw", 0.0)
        price = ab.get("price", 55.0)
        activated.append((gid, mw))
        total_cost += mw * price

    imbalance_price = 55.0
    if marginal_prices:
        imbalance_price = marginal_prices.get("system", 55.0)

    return ImbalancePricingResult(
        system_imbalance_mw=system_imbalance_mw,
        imbalance_price_eur_mwh=imbalance_price,
        activated_balancing=tuple(activated),
        message=f"Imbalance pricing: {system_imbalance_mw:.1f}MW at {imbalance_price:.2f}",
        timestamp=simulated_time,
    )
