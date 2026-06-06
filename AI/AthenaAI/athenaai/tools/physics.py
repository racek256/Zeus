"""Deterministic tool APIs for AthenaAI.

Phase 2.2: These now delegate to real implementations in athenaai.physics,
athenaai.market, and athenaai.forecast. The _make_result wrapper preserves
the Phase 2.1 interface for existing code.
"""

from __future__ import annotations

import math
import warnings
from datetime import datetime
from typing import Any

try:
    import pandapower as pp
    import pandapower.networks as pn
    PANDAPOWER_AVAILABLE = True
except ImportError:
    PANDAPOWER_AVAILABLE = False

from athenaai.market.advisory import (
    calculate_balancing_group,
    calculate_imbalance_pricing,
    calculate_interconnect_schedule,
    calculate_redispatch_costs,
    calculate_reserve_adequacy,
    merit_order_dispatch as market_merit_order_dispatch,
)
from athenaai.physics.engine import (
    PhysicsStatus,
    run_ac_load_flow as _run_ac_load_flow,
    run_frequency_response as _run_frequency_response,
    run_opf as _run_opf,
    run_short_circuit as _run_short_circuit,
    run_state_estimation as _run_state_estimation,
)
from athenaai.physics.n1 import n1_security_scan as _n1_scan

try:
    from athenaai.forecast.timesfm import (
        PowerGridLoadForecaster,
        SolarNowcaster,
        WindNowcaster,
        _check_timesfm_available,
    )
    _TIMESFM_AVAILABLE = _check_timesfm_available()
except ImportError:
    _TIMESFM_AVAILABLE = False


def _make_result(
    success: bool,
    message: str,
    inputs: dict[str, Any],
    simulated_time: datetime | None = None,
    uncertainty: dict[str, float] | None = None,
    results: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    status = {"success": success, "message": message, "error_code": error_code}
    return {
        "status": status,
        "simulated_time": simulated_time.isoformat() if simulated_time else None,
        "inputs_summary": inputs,
        "uncertainty": uncertainty,
        "results": results or {},
    }


def _unavailable_result(
    *,
    tool_name: str,
    required_dependency: str,
    inputs: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    return _make_result(
        success=False,
        message=f"{tool_name} requires {required_dependency} and is not available in this runtime",
        inputs=inputs,
        simulated_time=simulated_time,
        results={"required_dependency": required_dependency},
        error_code=f"{required_dependency.upper().replace('-', '_')}_UNAVAILABLE",
    )


def ac_load_flow(
    network_state: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "network_state": network_state,
        "method": "Newton-Raphson",
    }
    result = _run_ac_load_flow(network_state, simulated_time)
    bus_voltages = {
        bid: {"vm_pu": vm, "va_deg": va}
        for bid, vm, va in result.bus_voltages
    }
    branch_flows = {
        br_id: {"from": fb, "to": tb, "loading_pct": loading}
        for br_id, fb, tb, loading in result.branch_flows
    }
    generations = {gid: mw for gid, mw in result.generations}
    violations = result.violations()
    return _make_result(
        success=result.converged and len(violations) == 0,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "bus_voltages": bus_voltages,
            "branch_flows": branch_flows,
            "generations": generations,
            "converged": result.converged,
            "status": result.status.value,
            "violations": violations,
        },
        error_code=None if result.converged else result.status.value,
    )


def optimal_power_flow(
    network_state: dict[str, Any],
    constraints: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "network_state": network_state,
        "constraints": constraints,
        "method": "pandapower OPF",
    }
    result = _run_opf(network_state, constraints, simulated_time)
    return _make_result(
        success=result.solved,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "generation_schedule": {gid: mw for gid, mw in result.generation_schedule},
            "line_flows": {br_id: {"from": fb, "to": tb, "loading": loading} for br_id, fb, tb, loading in result.branch_flows},
            "dual_prices": {bid: price for bid, price in result.dual_prices},
            "cost": result.cost_eur,
            "status": result.status.value,
        },
        error_code=None if result.solved else result.status.value,
    )


def n1_contingency_scan(
    network_state: dict[str, Any],
    contingencies: list[dict[str, Any]],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "network_state": network_state,
        "num_contingencies": len(contingencies),
        "contingency_types": list(set(c.get("type") for c in contingencies)),
    }
    result = _n1_scan(
        network_state,
        simulated_time=simulated_time,
        critical_elements=contingencies,
    )
    return _make_result(
        success=result.passed,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "passed": result.passed,
            "violated_contingencies": result.violated_contingencies,
            "secure": result.passed,
            "status": result.status.value,
        },
        error_code=None if result.passed else result.status.value,
    )


def frequency_response(
    network_state: dict[str, Any],
    disturbance: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "network_state": network_state,
        "disturbance": disturbance,
        "method": "simplified swing equation",
    }

    result = _run_frequency_response(network_state, disturbance, simulated_time=simulated_time)

    uncertainty = {
        "freq_nadir_std_hz": 0.15,
        "rocof_std_hz_s": 0.05,
        "settling_freq_std_hz": 0.08,
    }

    if result.status in (PhysicsStatus.FALLBACK_USED,):
        warnings.warn(
            "frequency_response using simplified swing equation fallback. "
            "Install 'andes' for accurate transient stability analysis.",
            RuntimeWarning,
        )

    return _make_result(
        success=result.success,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "frequency_nadir_hz": result.frequency_nadir_hz,
            "rocof_hz_s": result.rocof_hz_s,
            "settling_frequency_hz": result.settling_frequency_hz,
            "system_inertia_s": result.system_inertia_s,
            "critical_clearing_time_cycles": result.critical_clearing_time_cycles,
            "delta_p_mw": result.delta_p_mw,
            "disturbance_type": disturbance.get("type", "load_loss"),
            "method_used": "engine_run_frequency_response",
        },
    )


def short_circuit(
    network_state: dict[str, Any],
    fault_bus: str,
    fault_type: str = "3ph",
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "network_state": network_state,
        "fault_bus": fault_bus,
        "fault_type": fault_type,
        "method": "IEC 60909",
    }

    result = _run_short_circuit(
        network_state,
        fault_bus=fault_bus,
        fault_type=fault_type,
        simulated_time=simulated_time,
    )

    fault_power_mva = result.fault_power_mva
    fault_current_ka = result.fault_current_ka

    bus_voltages: dict[str, dict[str, float]] = {}
    for bus_id, vm_pu, va_deg in result.bus_voltages:
        bus_voltages[bus_id] = {"vm_pu": vm_pu, "va_deg": va_deg}

    generator_contributions: dict[str, dict[str, float]] = {}
    for gen_id, ikss_ka in result.generator_contributions:
        generator_contributions[gen_id] = {
            "current_ka": ikss_ka,
            "power_mva": round(ikss_ka * 110.0 * 1.732, 2),
        }

    uncertainty = {
        "fault_current_std_ka": round(fault_current_ka * 0.15, 3),
        "voltage_std_pu": 0.05,
    }

    if result.status in (PhysicsStatus.FALLBACK_USED,):
        warnings.warn(
            "short_circuit using simplified IEC 60909 fallback. "
            "Install 'pandapower' for full IEC 60909 compliance.",
            RuntimeWarning,
        )

    return _make_result(
        success=result.success,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "fault_current_ka": fault_current_ka,
            "fault_power_mva": fault_power_mva,
            "voltage_at_fault_pu": 0.0,
            "bus_voltages": bus_voltages,
            "generator_contributions": generator_contributions,
            "v_base_kv": 110.0,
            "c_factor": 1.1,
            "method_used": "engine_run_short_circuit",
        },
    )


def state_estimation(
    measurements: dict[str, Any],
    network_topology: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "num_measurements": len(measurements) if isinstance(measurements, dict) else len(measurements) if isinstance(measurements, list) else 0,
        "num_buses": network_topology.get("num_buses", 0),
        "method": "weighted least squares",
    }

    # Build network_state from topology for engine compatibility
    buses_list = network_topology.get("buses", [])
    if isinstance(buses_list, dict):
        buses_list = [
            {"bus_id": bid, "name": bdata.get("name", bid), "vn_kv": bdata.get("vn_kv", 110.0)}
            for bid, bdata in buses_list.items()
        ]
    network_state = {
        "buses": buses_list,
        "branches": [],
        "generators": [],
        "loads": [],
    }

    result = _run_state_estimation(
        network_state,
        measurements=measurements,
        simulated_time=simulated_time,
    )

    bus_estimates: dict[str, dict[str, float]] = {}
    for bus_id, vm_pu, va_deg in result.bus_estimates:
        bus_estimates[bus_id] = {"vm_pu": vm_pu, "va_deg": va_deg}

    uncertainty = {
        "voltage_magnitude_std_pu": 0.05,
        "voltage_angle_std_deg": 2.0,
        "degrees_of_freedom": max(1, len(measurements) - 2 * len(buses_list)),
        "condition_number": 1.0,
    }

    if result.status in (PhysicsStatus.FALLBACK_USED,):
        warnings.warn(
            "state_estimation using weighted least squares fallback. "
            "Install 'pandapower' for full state estimation capabilities.",
            RuntimeWarning,
        )

    return _make_result(
        success=result.success,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "bus_estimates": bus_estimates,
            "estimated_v_mag_pu": result.estimated_v_mag_pu,
            "estimated_v_angle_deg": result.estimated_v_angle_deg,
            "num_measurements_used": len(measurements) if isinstance(measurements, list) else len(measurements.get("measurements", [])) if isinstance(measurements, dict) else 0,
            "bad_data_detected": result.bad_data_detected,
            "suspicious_measurements": list(result.suspicious_measurements),
            "method_used": "engine_run_state_estimation",
        },
    )


def merit_order_dispatch(
    generator_data: list[dict[str, Any]],
    load_forecast: dict[str, Any],
    fuel_prices: dict[str, Any],
    simulated_time: datetime | None = None,
    cost_calculator: Any | None = None,
) -> dict[str, Any]:
    inputs = {
        "num_generators": len(generator_data),
        "total_load_mw": load_forecast.get("total_load_mw", 0),
        "fuel_price_source": (
            "csv+cost_curves" if cost_calculator else "Fuel prices 2024.csv"
        ),
    }
    result = market_merit_order_dispatch(
        generator_data,
        load_forecast.get("total_load_mw", 0.0),
        fuel_prices,
        simulated_time,
        cost_calculator=cost_calculator,
    )
    return _make_result(
        success=True,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "dispatch_order": list(result.dispatch_order),
            "marginal_price_eur_mwh": result.marginal_price_eur_mwh,
            "total_generation_mw": result.total_generation_mw,
        },
    )


def redispatch_cost_calculation(
    upward_adjustments: list[dict[str, Any]],
    downward_adjustments: list[dict[str, Any]],
    simulated_time: datetime | None = None,
    day_ahead_prices: dict[int, float] | None = None,
    current_hour: int = 0,
) -> dict[str, Any]:
    inputs = {
        "num_upward": len(upward_adjustments),
        "num_downward": len(downward_adjustments),
        "use_real_prices": day_ahead_prices is not None,
    }
    fuel_prices = {"default": 50.0}
    result = calculate_redispatch_costs(
        upward_adjustments,
        downward_adjustments,
        fuel_prices,
        simulated_time,
        day_ahead_prices=day_ahead_prices,
        current_hour=current_hour,
    )
    return _make_result(
        success=True,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "upward_cost_eur": result.upward_cost_eur,
            "downward_cost_eur": result.downward_cost_eur,
            "total_cost_eur": result.total_cost_eur,
        },
    )


def balancing_group_check(
    balancing_group_data: dict[str, Any],
    settlement_interval: str,
    simulated_time: datetime | None = None,
    imbalance_prices: dict[str, float] | None = None,
) -> dict[str, Any]:
    inputs = {
        "balancing_group": balancing_group_data.get("name", "unknown"),
        "settlement_interval": settlement_interval,
        "use_real_imbalance": imbalance_prices is not None,
    }
    result = calculate_balancing_group(
        balancing_group_data.get("scheduled", {}),
        balancing_group_data.get("actual", {}),
        settlement_interval,
        simulated_time,
        imbalance_prices=imbalance_prices,
    )
    return _make_result(
        success=True,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "deviation_mw": result.deviation_mw,
            "imbalance_eur": result.imbalance_eur,
            "per_region_deviations": list(result.per_region_deviations),
        },
    )


def interconnect_schedule(
    borders: list[str],
    atc_constraints: dict[str, Any],
    simulated_time: datetime | None = None,
    crossborder_schedules: dict[str, float] | None = None,
) -> dict[str, Any]:
    inputs = {
        "borders": borders,
        "num_atc_constraints": len(atc_constraints),
        "method": "crossborder_schedules" if crossborder_schedules else "simplified ATC/flow",
        "use_real_schedules": crossborder_schedules is not None,
    }
    result = calculate_interconnect_schedule(
        borders,
        atc_constraints,
        None,
        simulated_time,
        crossborder_schedules=crossborder_schedules,
    )
    return _make_result(
        success=True,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "scheduled_flows": dict(result.scheduled_flows),
            "atc_values": dict(result.atc_values),
        },
    )


def reserve_adequacy_check(
    largest_contingency: dict[str, Any],
    available_headroom: dict[str, Any],
    reserve_margin_target: float,
    simulated_time: datetime | None = None,
    reserve_status: dict[str, float] | None = None,
) -> dict[str, Any]:
    inputs = {
        "largest_contingency_mw": largest_contingency.get("mw", 0),
        "reserve_margin_target": reserve_margin_target,
        "method": "reserve_status" if reserve_status else "largest contingency check",
        "use_real_reserves": reserve_status is not None,
    }
    result = calculate_reserve_adequacy(
        available_headroom,
        largest_contingency.get("mw", 0.0),
        reserve_margin_target,
        simulated_time,
        reserve_status=reserve_status,
    )
    return _make_result(
        success=True,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "available_reserve_mw": result.available_reserve_mw,
            "required_reserve_mw": result.required_reserve_mw,
            "adequate": result.adequate,
        },
    )


def imbalance_pricing(
    activated_balancing: list[dict[str, Any]],
    marginal_prices: dict[str, Any],
    simulated_time: datetime | None = None,
    imbalance_prices: dict[str, float] | None = None,
) -> dict[str, Any]:
    inputs = {
        "num_activated": len(activated_balancing),
        "pricing_method": "real_imbalance" if imbalance_prices else "EU/Czech-style activated balancing cost",
        "use_real_imbalance": imbalance_prices is not None,
    }
    result = calculate_imbalance_pricing(
        activated_balancing,
        sum(a.get("mw", 0) for a in activated_balancing),
        marginal_prices,
        simulated_time,
        imbalance_prices=imbalance_prices,
    )
    return _make_result(
        success=True,
        message=result.message,
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "system_imbalance_mw": result.system_imbalance_mw,
            "imbalance_price_eur_mwh": result.imbalance_price_eur_mwh,
        },
    )


def load_forecast_15min(
    historical_load: list[dict[str, Any]],
    temperature: float,
    calendar_features: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Deterministic 15-minute load forecast — statistical fallback.

    This is a DETERMINISTIC fallback tool. For forward-looking operational decisions,
    prefer the MCP forecast tool ``forecast_load`` (via the ``athenaai-forecast`` MCP
    server), which provides TimesFM 2.5 probabilistic forecasts with 80% and 90%
    prediction intervals.

    When to use THIS tool:
    - MCP server is unavailable or unresponsive
    - Quick validation of MCP forecast outputs
    - When only deterministic, non-probabilistic output is acceptable

    When to use MCP forecast_load instead:
    - Day-ahead scheduling decisions
    - Reserve sizing (use prediction intervals)
    - Forward-looking operational planning
    - Any decision where uncertainty awareness matters

    Returns results with uncertainty bounds (either TimesFM 80/90% intervals or
    95% confidence from the statistical exponential smoothing fallback).
    """
    inputs = {
        "num_historical_points": len(historical_load),
        "temperature_c": temperature,
        "calendar_features": calendar_features,
    }

    # Extract load values from historical data
    load_values = []
    for point in historical_load:
        if isinstance(point, dict):
            load_values.append(float(point.get("load_mw", point.get("mw", 0.0))))
        else:
            load_values.append(float(point))

    hour = calendar_features.get("hour", 12)
    day_type = calendar_features.get("day_type", "weekday")
    day_of_week = 0
    dow_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6}
    if isinstance(day_type, str):
        day_of_week = dow_map.get(day_type.lower(), 0)

    # --- Try TimesFM first ---
    if _TIMESFM_AVAILABLE and load_values:
        try:
            import numpy as np
            forecaster = PowerGridLoadForecaster()
            output = forecaster.forecast(
                historical_load=np.array(load_values, dtype=np.float64),
                horizon_steps=1,
                temperature=temperature,
                hour_of_day=int(hour),
                day_of_week=day_of_week,
            )
            if output.points:
                pt = output.points[0]
                return _make_result(
                    success=True,
                    message=f"Load forecast generated using {output.model}.",
                    inputs=inputs,
                    simulated_time=simulated_time,
                    uncertainty={
                        "std_mw": round((pt.upper_80 - pt.lower_80) / 2.564, 2),
                        "confidence_80_pct": 80.0,
                        "confidence_90_pct": 90.0,
                    },
                    results={
                        "forecast_load_mw": round(pt.mean, 2),
                        "base_load_mw": round(pt.mean, 2),
                        "forecast_horizon_h": pt.horizon_h,
                        "lower_bound_80_mw": round(pt.lower_80, 2),
                        "upper_bound_80_mw": round(pt.upper_80, 2),
                        "lower_bound_90_mw": round(pt.lower_90, 2),
                        "upper_bound_90_mw": round(pt.upper_90, 2),
                        "method_used": output.model,
                        "metadata": output.metadata,
                    },
                )
        except Exception:
            pass  # Fall through to statistical baseline

    # --- Statistical fallback ---
    alpha = 0.3  # Smoothing factor

    if load_values:
        weights = [alpha * ((1 - alpha) ** (len(load_values) - 1 - i)) for i in range(len(load_values))]
        weight_sum = sum(weights)
        normalized_weights = [w / weight_sum for w in weights]
        smoothed_load = sum(l * w for l, w in zip(load_values, normalized_weights))

        mean_load = sum(load_values) / len(load_values)
        variance = sum((l - mean_load) ** 2 for l in load_values) / len(load_values)
        load_std = math.sqrt(variance) if variance > 0 else smoothed_load * 0.05
    else:
        smoothed_load = 1000.0
        load_std = 100.0

    temp_coefficient = 0.015
    reference_temp = 20.0
    temp_diff = temperature - reference_temp
    temp_correction = 1.0 + temp_coefficient * temp_diff

    is_holiday = calendar_features.get("is_holiday", False)

    hour_multiplier = 1.0
    if 7 <= hour <= 9 or 17 <= hour <= 21:
        hour_multiplier = 1.1
    elif 0 <= hour <= 5:
        hour_multiplier = 0.7
    elif 10 <= hour <= 16:
        hour_multiplier = 0.95

    day_multiplier = 1.0
    if day_type.lower() in {"weekend", "saturday", "sunday"} or is_holiday:
        day_multiplier = 0.85

    corrected_load = smoothed_load * temp_correction * hour_multiplier * day_multiplier

    horizon_h = 0.25
    uncertainty_growth = 1.0 + horizon_h * 0.5
    forecast_std = load_std * temp_correction * uncertainty_growth

    warnings.warn(
        "load_forecast_15min using exponential smoothing fallback. "
        "Install 'timesfm' for accurate ML-based load forecasting.",
        RuntimeWarning,
    )

    return _make_result(
        success=True,
        message="Load forecast calculated using exponential smoothing fallback. "
        "Install 'timesfm' for accurate ML-based forecasting.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty={"std_mw": round(forecast_std, 2), "confidence_pct": 95.0},
        results={
            "forecast_load_mw": round(corrected_load, 2),
            "base_load_mw": round(smoothed_load, 2),
            "temperature_correction": round(temp_correction, 4),
            "hour_multiplier": round(hour_multiplier, 3),
            "day_multiplier": round(day_multiplier, 3),
            "forecast_horizon_h": horizon_h,
            "lower_bound_mw": round(corrected_load - 1.96 * forecast_std, 2),
            "upper_bound_mw": round(corrected_load + 1.96 * forecast_std, 2),
            "method_used": "exponential_smoothing_fallback",
        },
    )


def wind_nowcast(
    wind_forecast: dict[str, Any],
    actual_wind_speed: float | None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Deterministic wind power nowcast — persistence model fallback.

    This is a DETERMINISTIC fallback tool. For operational renewable forecasting,
    prefer the MCP tool ``forecast_wind`` (via ``athenaai-forecast`` MCP server),
    which uses TimesFM 2.5 with IEC 61400 power curve conversion and provides
    80%/90% prediction intervals.

    Use THIS tool only when:
    - MCP server is unavailable
    - Quick validation of MCP wind forecast outputs
    - Deterministic output is explicitly required

    For intraday renewable planning, dispatch decisions, and reserve sizing,
    use the MCP forecast_wind tool — it provides uncertainty-aware predictions
    that enable conservative dispatch when prediction intervals are wide.

    Returns power output in MW with uncertainty bounds (std and confidence intervals).
    """
    horizon_h = wind_forecast.get("horizon_h", 0.25)
    forecast_wind_ms = float(wind_forecast.get("wind_speed_ms", 5.0))
    forecast_direction_deg = float(wind_forecast.get("direction_deg", 180.0))

    inputs = {
        "forecast_horizon_h": horizon_h,
        "wind_speed_ms": forecast_wind_ms,
        "actual_available": actual_wind_speed is not None,
    }

    v_cut_in = 3.0
    v_rated = 12.0
    v_cut_out = 25.0
    rated_power_mw = float(wind_forecast.get("rated_power_mw", 2.0))

    effective_wind = actual_wind_speed if actual_wind_speed is not None else forecast_wind_ms

    # --- Try TimesFM first ---
    if _TIMESFM_AVAILABLE:
        try:
            import numpy as np
            nowcaster = WindNowcaster()
            output = nowcaster.forecast(
                historical_wind_speed=np.array([effective_wind], dtype=np.float64),
                horizon_steps=1,
                rated_power_mw=rated_power_mw,
                v_cut_in=v_cut_in,
                v_rated=v_rated,
                v_cut_out=v_cut_out,
            )
            if output.points:
                pt = output.points[0]
                wind_pts = output.metadata.get("wind_speed_points", [])
                ws = wind_pts[0]["wind_speed_ms"] if wind_pts else effective_wind
                return _make_result(
                    success=True,
                    message=f"Wind nowcast generated using {output.model}.",
                    inputs=inputs,
                    simulated_time=simulated_time,
                    uncertainty={
                        "wind_speed_std_ms": round(abs(pt.upper_80 - pt.lower_80) / 2.564, 3),
                        "power_std_mw": round(abs(pt.upper_80 - pt.lower_80) / 2.564, 3),
                        "confidence_80_pct": 80.0,
                        "confidence_90_pct": 90.0,
                    },
                    results={
                        "wind_speed_ms": round(ws, 3),
                        "wind_direction_deg": round(forecast_direction_deg, 1),
                        "power_output_mw": round(pt.mean, 4),
                        "cut_in_ms": v_cut_in,
                        "rated_ms": v_rated,
                        "cut_out_ms": v_cut_out,
                        "lower_bound_80_mw": round(pt.lower_80, 4),
                        "upper_bound_80_mw": round(pt.upper_80, 4),
                        "lower_bound_90_mw": round(pt.lower_90, 4),
                        "upper_bound_90_mw": round(pt.upper_90, 4),
                        "source": "timesfm",
                        "method_used": output.model,
                    },
                )
        except Exception:
            pass

    # --- Statistical fallback ---
    if actual_wind_speed is not None:
        persistence_weight = 0.7
        estimated_wind_ms = actual_wind_speed * persistence_weight + forecast_wind_ms * (1 - persistence_weight)
        source = "blended_actual_forecast"
    else:
        estimated_wind_ms = forecast_wind_ms
        source = "forecast_persistence"

    if estimated_wind_ms < v_cut_in or estimated_wind_ms >= v_cut_out:
        power_output_mw = 0.0
    elif estimated_wind_ms >= v_rated:
        power_output_mw = rated_power_mw
    else:
        v_range = v_rated - v_cut_in
        v_position = (estimated_wind_ms - v_cut_in) / v_range
        power_output_mw = rated_power_mw * (v_position ** 3)

    base_std_ms = 0.5 if actual_wind_speed else 1.0
    horizon_factor = 1.0 + horizon_h * 2.0
    wind_std_ms = base_std_ms * horizon_factor

    power_std_mw = rated_power_mw * 0.15 * horizon_factor

    warnings.warn(
        "wind_nowcast using persistence model fallback. "
        "Install 'timesfm' for accurate wind forecasting.",
        RuntimeWarning,
    )

    return _make_result(
        success=True,
        message="Wind nowcast calculated using persistence model fallback. "
        "Install 'timesfm' for accurate wind forecasting.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty={
            "wind_speed_std_ms": round(wind_std_ms, 3),
            "power_std_mw": round(power_std_mw, 3),
            "confidence_pct": 95.0,
        },
        results={
            "wind_speed_ms": round(estimated_wind_ms, 3),
            "wind_direction_deg": round(forecast_direction_deg, 1),
            "power_output_mw": round(power_output_mw, 4),
            "cut_in_ms": v_cut_in,
            "rated_ms": v_rated,
            "cut_out_ms": v_cut_out,
            "lower_bound_ms": round(estimated_wind_ms - 1.96 * wind_std_ms, 3),
            "upper_bound_ms": round(estimated_wind_ms + 1.96 * wind_std_ms, 3),
            "source": source,
            "method_used": "persistence_fallback",
        },
    )


def solar_nowcast(
    solar_forecast: dict[str, Any],
    actual_irradiance: float | None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Deterministic solar power nowcast — clear-sky model fallback.

    This is a DETERMINISTIC fallback tool. For operational solar forecasting,
    prefer the MCP tool ``forecast_solar`` (via ``athenaai-forecast`` MCP server),
    which uses TimesFM 2.5 with PV conversion model and provides 80%/90% prediction
    intervals accounting for cloud cover uncertainty.

    Use THIS tool only when:
    - MCP server is unavailable
    - Quick validation of MCP solar forecast outputs
    - Deterministic output is explicitly required

    For renewable dispatch planning, reserve sizing, and intraday solar-aware
    scheduling, use the MCP forecast_solar tool — it accounts for cloud
    uncertainty that the clear-sky fallback cannot capture.

    Returns power output in MW with uncertainty bounds.
    """
    horizon_h = solar_forecast.get("horizon_h", 0.25)
    forecast_irradiance = float(solar_forecast.get("irradiance_wm2", 800.0))
    cloud_cover_okta = float(solar_forecast.get("cloud_cover_okta", 3.0))
    latitude = float(solar_forecast.get("latitude", 50.0))
    panel_tilt_deg = float(solar_forecast.get("panel_tilt", 35.0))
    rated_power_mw = float(solar_forecast.get("rated_power_mw", 1.0))
    panel_efficiency = 0.18
    system_loss_factor = 0.85

    inputs = {
        "forecast_horizon_h": horizon_h,
        "irradiance_wm2": forecast_irradiance,
        "actual_available": actual_irradiance is not None,
    }

    effective_irr = actual_irradiance if actual_irradiance is not None else forecast_irradiance

    # --- Try TimesFM first ---
    if _TIMESFM_AVAILABLE:
        try:
            import numpy as np
            nowcaster = SolarNowcaster()
            output = nowcaster.forecast(
                historical_irradiance=np.array([effective_irr], dtype=np.float64),
                horizon_steps=1,
                rated_power_mw=rated_power_mw,
                panel_efficiency=panel_efficiency,
                system_loss_factor=system_loss_factor,
                cloud_cover_okta=cloud_cover_okta,
            )
            if output.points:
                pt = output.points[0]
                irr_pts = output.metadata.get("irradiance_points", [])
                irr = irr_pts[0]["irradiance_wm2"] if irr_pts else effective_irr
                return _make_result(
                    success=True,
                    message=f"Solar nowcast generated using {output.model}.",
                    inputs=inputs,
                    simulated_time=simulated_time,
                    uncertainty={
                        "irradiance_std_wm2": round(abs(pt.upper_80 - pt.lower_80) / 2.564, 1),
                        "power_std_mw": round(abs(pt.upper_80 - pt.lower_80) / 2.564, 4),
                        "confidence_80_pct": 80.0,
                        "confidence_90_pct": 90.0,
                    },
                    results={
                        "irradiance_wm2": round(irr, 1),
                        "clear_sky_irradiance_wm2": round(irr, 1),
                        "cloud_cover_factor": round(1.0 - (cloud_cover_okta / 8.0) * 0.75, 3),
                        "power_output_mw": round(pt.mean, 4),
                        "panel_efficiency": panel_efficiency,
                        "lower_bound_80_mw": round(pt.lower_80, 4),
                        "upper_bound_80_mw": round(pt.upper_80, 4),
                        "lower_bound_90_mw": round(pt.lower_90, 4),
                        "upper_bound_90_mw": round(pt.upper_90, 4),
                        "source": "timesfm",
                        "method_used": output.model,
                    },
                )
        except Exception:
            pass

    # --- Statistical fallback ---
    solar_noon_irradiance = 950.0

    if actual_irradiance is not None:
        effective_irradiance = actual_irradiance * 0.8 + forecast_irradiance * 0.2
        source = "blended_actual_forecast"
    else:
        effective_irradiance = forecast_irradiance
        source = "forecast_clear_sky"

    cloud_factor = 1.0 - (cloud_cover_okta / 8.0) * 0.75

    clear_sky_irradiance = solar_noon_irradiance * cloud_factor
    effective_irradiance = min(effective_irradiance, clear_sky_irradiance * 1.1)

    total_efficiency = panel_efficiency * system_loss_factor

    ghi_wm2 = effective_irradiance
    power_density_wm2 = ghi_wm2 * total_efficiency
    area_required_m2 = (rated_power_mw * 1e6) / (panel_efficiency * 1000)

    power_output_mw = (ghi_wm2 / 1000.0) * (rated_power_mw / 1.0) * cloud_factor
    power_output_mw = max(0.0, min(rated_power_mw, power_output_mw))

    base_std_wm2 = 50.0 if actual_irradiance else 100.0
    horizon_factor = 1.0 + horizon_h * 1.5
    irradiance_std_wm2 = base_std_wm2 * horizon_factor * (1.0 + cloud_cover_okta / 8.0)
    power_std_mw = rated_power_mw * 0.15 * horizon_factor

    warnings.warn(
        "solar_nowcast using clear-sky model fallback. "
        "Install 'timesfm' for accurate solar forecasting.",
        RuntimeWarning,
    )

    return _make_result(
        success=True,
        message="Solar nowcast calculated using clear-sky model fallback. "
        "Install 'timesfm' for accurate solar forecasting.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty={
            "irradiance_std_wm2": round(irradiance_std_wm2, 1),
            "power_std_mw": round(power_std_mw, 4),
            "confidence_pct": 95.0,
        },
        results={
            "irradiance_wm2": round(effective_irradiance, 1),
            "clear_sky_irradiance_wm2": round(clear_sky_irradiance, 1),
            "cloud_cover_factor": round(cloud_factor, 3),
            "power_output_mw": round(power_output_mw, 4),
            "panel_efficiency": panel_efficiency,
            "lower_bound_mw": round(max(0.0, power_output_mw - 1.96 * power_std_mw), 4),
            "upper_bound_mw": round(min(rated_power_mw, power_output_mw + 1.96 * power_std_mw), 4),
            "source": source,
            "method_used": "clear_sky_fallback",
        },
    )


def ramp_event_detector(
    recent_generation: list[dict[str, Any]],
    threshold_mw_per_h: float,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "num_points": len(recent_generation),
        "threshold_mw_per_h": threshold_mw_per_h,
    }
    ordered_points = sorted(
        recent_generation,
        key=lambda point: str(point.get("timestamp", "")),
    )
    ramp_mw_per_h = 0.0
    if len(ordered_points) >= 2:
        first = ordered_points[0]
        last = ordered_points[-1]
        first_mw = float(first.get("generation_mw", first.get("mw", 0.0)))
        last_mw = float(last.get("generation_mw", last.get("mw", 0.0)))
        elapsed_hours = max(
            1.0,
            float(last.get("hour_index", len(ordered_points) - 1))
            - float(first.get("hour_index", 0.0)),
        )
        ramp_mw_per_h = (last_mw - first_mw) / elapsed_hours

    ramp_detected = abs(ramp_mw_per_h) >= threshold_mw_per_h
    if ramp_mw_per_h > 0:
        direction = "up"
    elif ramp_mw_per_h < 0:
        direction = "down"
    else:
        direction = "none"

    return _make_result(
        success=True,
        message="Ramp event detection completed using deterministic endpoint slope",
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "ramp_detected": ramp_detected,
            "ramp_mw_per_h": round(ramp_mw_per_h, 3),
            "ramp_direction": direction,
        },
    )


def day_ahead_schedule_optimization(
    load_forecasts: dict[str, Any],
    generator_availabilities: list[dict[str, Any]],
    reserve_requirements: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "num_generators": len(generator_availabilities),
        "forecast_horizon_h": 24,
        "reserve_requirements": reserve_requirements,
    }
    hourly_forecasts = load_forecasts.get("hourly_load_mw", {})
    if isinstance(hourly_forecasts, list):
        load_by_hour = {hour: float(load_mw) for hour, load_mw in enumerate(hourly_forecasts[:24])}
    elif isinstance(hourly_forecasts, dict):
        load_by_hour = {int(hour): float(load_mw) for hour, load_mw in hourly_forecasts.items()}
    else:
        load_by_hour = {}
    default_load_mw = float(load_forecasts.get("total_load_mw", 0.0))
    reserve_margin = float(reserve_requirements.get("margin_mw", reserve_requirements.get("mw", 0.0)))
    generators = sorted(
        generator_availabilities,
        key=lambda gen: float(gen.get("marginal_cost_eur_mwh", gen.get("cost_eur_mwh", 0.0))),
    )
    hourly_schedule: dict[int, dict[str, float]] = {}
    expected_cost_eur = 0.0
    reserve_allocated: dict[int, float] = {}

    for hour in range(24):
        remaining_mw = load_by_hour.get(hour, default_load_mw) + reserve_margin
        hour_schedule: dict[str, float] = {}
        for gen in generators:
            generator_id = str(gen.get("generator_id", gen.get("name", "unknown")))
            available_mw = max(0.0, float(gen.get("available_mw", gen.get("max_p_mw", 0.0))))
            dispatch_mw = min(remaining_mw, available_mw)
            if dispatch_mw <= 0:
                continue
            hour_schedule[generator_id] = round(dispatch_mw, 3)
            expected_cost_eur += dispatch_mw * float(gen.get("marginal_cost_eur_mwh", gen.get("cost_eur_mwh", 0.0)))
            remaining_mw -= dispatch_mw
            if remaining_mw <= 0:
                break
        hourly_schedule[hour] = hour_schedule
        reserve_allocated[hour] = max(0.0, reserve_margin - max(0.0, remaining_mw))

    return _make_result(
        success=all(sum(schedule.values()) >= load_by_hour.get(hour, default_load_mw) for hour, schedule in hourly_schedule.items()),
        message="Day-ahead schedule optimized using deterministic merit-order dispatch",
        inputs=inputs,
        simulated_time=simulated_time,
        results={
            "hourly_schedule": hourly_schedule,
            "expected_cost_eur": round(expected_cost_eur, 3),
            "reserve_allocated": reserve_allocated,
        },
        error_code=None,
    )


def temperature_to_demand(
    temperature_c: float,
    region: str,
    day_type: str,
    hour: int,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "temperature_c": temperature_c,
        "region": region,
        "day_type": day_type,
        "hour": hour,
    }
    base_demand_by_region = {
        "bohemia-west": 900.0,
        "bohemia-east": 1200.0,
        "moravia": 850.0,
        "silesia": 1000.0,
    }
    base_demand_mw = base_demand_by_region.get(region, 950.0)
    heating_component = max(0.0, 18.0 - temperature_c) * 18.0
    cooling_component = max(0.0, temperature_c - 22.0) * 12.0
    peak_multiplier = 1.12 if hour in {7, 8, 17, 18, 19} else 1.0
    day_multiplier = 0.92 if day_type.lower() in {"weekend", "holiday"} else 1.0
    demand_mw = (base_demand_mw + heating_component + cooling_component) * peak_multiplier * day_multiplier
    sensitivity = -18.0 if temperature_c < 18.0 else 12.0 if temperature_c > 22.0 else 0.0

    return _make_result(
        success=True,
        message="Temperature-to-demand model applied using deterministic regional sensitivity curve",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty={"std_mw": round(max(25.0, demand_mw * 0.05), 3)},
        results={
            "demand_mw": round(demand_mw, 3),
            "temperature_sensitivity_mw_per_c": sensitivity,
        },
    )


def ev_flexible_load_model(
    ev_charge_points: int,
    availability_probability: float,
    grid_constraints: dict[str, Any],
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    inputs = {
        "ev_charge_points": ev_charge_points,
        "availability_probability": availability_probability,
        "num_grid_constraints": len(grid_constraints),
    }
    bounded_availability = max(0.0, min(1.0, availability_probability))
    average_kw_per_point = float(grid_constraints.get("average_kw_per_point", 7.4))
    max_flexible_capacity_mw = ev_charge_points * average_kw_per_point / 1000.0 * bounded_availability
    congestion_derate = 0.5 if grid_constraints.get("congested", False) else 1.0
    flexible_capacity_mw = max_flexible_capacity_mw * congestion_derate

    return _make_result(
        success=True,
        message="EV flexible load model applied using deterministic charger availability estimate",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty={"flexible_capacity_mw": round(flexible_capacity_mw * 0.2, 3)},
        results={
            "flexible_capacity_mw": round(flexible_capacity_mw, 3),
            "peak_flex_mw": round(flexible_capacity_mw * 0.6, 3),
            "valley_flex_mw": round(flexible_capacity_mw, 3),
        },
    )


# ---------------------------------------------------------------------------
# CO2 emission factors (gCO2/kWh) per fuel type — European grid averages
# See also: athenaai.market.cost_curves._GENERATOR_DEFAULTS co2 factors
# ---------------------------------------------------------------------------
_CO2_INTENSITY_G_PER_KWH: dict[str, float] = {
    "lignite": 1100.0,
    "coal": 850.0,
    "steam_coal": 850.0,
    "brown_coal": 950.0,
    "natural_gas": 400.0,
    "gas": 450.0,
    "ccgt": 350.0,
    "oil": 750.0,
    "biomass": 0.0,
    "uranium": 0.0,
    "nuclear": 0.0,
    "hydro": 0.0,
    "wind": 0.0,
    "solar": 0.0,
    "geo": 0.0,
}

# Generator types that can perform black start (restore grid from total blackout)
_BLACK_START_CAPABLE: set[str] = {
    "hydro",
    "ccgt",
    "gas",
    "natural_gas",
}

# Nominal transmission capacity per line type (MVA)
_TRANSMISSION_LINE_RATINGS: dict[str, float] = {
    "110kv": 150.0,
    "220kv": 350.0,
    "400kv": 1500.0,
    "400KV": 1500.0,
    "overhead": 350.0,
    "double": 700.0,
}


def carbon_intensity_calculation(
    generation_mix: dict[str, float],
    total_demand_mw: float,
    carbon_price_eur_t: float | None = None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Calculate carbon intensity and total emissions for current generation mix.

    Uses fuel-type CO2 factors from European grid averages. Optionally factors
    in EU ETS carbon price for emission cost calculation.

    Args:
        generation_mix: Dict mapping fuel_type to generation in MW
        total_demand_mw: Total system demand in MW (for intensity calculation)
        carbon_price_eur_t: EU ETS carbon price in EUR/tonne (optional)
        simulated_time: Simulation timestamp

    Returns:
        Structured result with total_emissions_ton, intensity_g_co2_kwh,
        generation_mix with per-fuel emissions, and emission_cost_eur if applicable.
    """
    inputs = {
        "num_fuel_types": len(generation_mix),
        "total_demand_mw": total_demand_mw,
        "carbon_price_eur_t": carbon_price_eur_t,
    }

    if not generation_mix:
        return _make_result(
            success=False,
            message="No generation mix provided",
            inputs=inputs,
            simulated_time=simulated_time,
            results={},
            error_code="EMPTY_GENERATION_MIX",
        )

    per_fuel_breakdown: dict[str, dict[str, float]] = {}
    total_emissions_t_h = 0.0
    total_generation_mw = 0.0

    for fuel_type, mw in generation_mix.items():
        if mw <= 0:
            continue
        co2_factor_g_kwh = _CO2_INTENSITY_G_PER_KWH.get(fuel_type.lower(), 500.0)
        emissions_t_h = mw * co2_factor_g_kwh / 1000.0
        total_emissions_t_h += emissions_t_h
        total_generation_mw += mw
        per_fuel_breakdown[fuel_type] = {
            "generation_mw": round(mw, 2),
            "co2_factor_g_kwh": co2_factor_g_kwh,
            "emissions_t_h": round(emissions_t_h, 4),
            "emissions_share_pct": 0.0,
        }

    # Calculate shares
    if total_emissions_t_h > 0:
        for ft, data in per_fuel_breakdown.items():
            data["emissions_share_pct"] = round(
                data["emissions_t_h"] / total_emissions_t_h * 100.0, 2
            )

    intensity_g_co2_kwh = (
        round(total_emissions_t_h * 1_000_000.0 / total_demand_mw / 1000.0, 2)
        if total_demand_mw > 0
        else 0.0
    )

    results: dict[str, Any] = {
        "total_emissions_t_h": round(total_emissions_t_h, 4),
        "intensity_g_co2_kwh": intensity_g_co2_kwh,
        "generation_mix": per_fuel_breakdown,
        "total_generation_mw": round(total_generation_mw, 2),
    }

    if carbon_price_eur_t is not None:
        emission_cost_eur_h = total_emissions_t_h * carbon_price_eur_t
        results["emission_cost_eur_h"] = round(emission_cost_eur_h, 2)
        results["carbon_price_eur_t"] = carbon_price_eur_t

    uncertainty = {
        "co2_factor_std_g_kwh": 50.0,
        "intensity_std_g_kwh": round(intensity_g_co2_kwh * 0.15, 2),
    }

    return _make_result(
        success=True,
        message=f"Carbon intensity calculated: {intensity_g_co2_kwh} gCO2/kWh, "
        f"{total_emissions_t_h:.2f} t/h total emissions.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results=results,
    )


def renewable_curtailment_analysis(
    available_renewable: dict[str, float],
    dispatched_renewable: dict[str, float],
    grid_constraints: dict[str, Any] | None = None,
    market_price_eur_mwh: float | None = None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Analyze how much renewable generation is being curtailed due to constraints.

    Compares available renewable capacity (weather-based potential) against
    actually dispatched renewable output. Identifies curtailment reasons
    (congestion, oversupply, voltage, frequency) and estimates revenue loss.

    Args:
        available_renewable: Dict mapping source (wind/solar) to available MW
        dispatched_renewable: Dict mapping source to actually dispatched MW
        grid_constraints: Optional dict with congestion, voltage, frequency flags
        market_price_eur_mwh: Market price for revenue loss estimation
        simulated_time: Simulation timestamp

    Returns:
        Structured result with curtailment volumes, percent, reasons, and revenue loss.
    """
    inputs = {
        "renewable_sources": list(available_renewable.keys()),
        "dispatched_sources": list(dispatched_renewable.keys()),
        "market_price_available": market_price_eur_mwh is not None,
    }

    if not available_renewable:
        return _make_result(
            success=False,
            message="No available renewable data provided",
            inputs=inputs,
            simulated_time=simulated_time,
            results={},
            error_code="EMPTY_RENEWABLE_DATA",
        )

    total_available = sum(available_renewable.values())
    total_dispatched = sum(
        dispatched_renewable.get(src, 0.0) for src in available_renewable
    )
    total_curtailed = max(0.0, total_available - total_dispatched)
    curtailment_pct = (
        round(total_curtailed / total_available * 100.0, 2)
        if total_available > 0
        else 0.0
    )

    reasons: list[str] = []
    if grid_constraints:
        if grid_constraints.get("congested", False):
            reasons.append("transmission_congestion")
        if grid_constraints.get("voltage_violation", False):
            reasons.append("voltage_constraint")
        if grid_constraints.get("frequency_event", False):
            reasons.append("frequency_response")
        if grid_constraints.get("oversupply", False):
            reasons.append("generation_oversupply")
    if not reasons:
        reasons.append("economic_dispatch")
        if total_curtailed == 0:
            reasons = []

    per_source: dict[str, dict[str, float]] = {}
    for src in available_renewable:
        avail = available_renewable.get(src, 0.0)
        disp = dispatched_renewable.get(src, 0.0)
        curtail = max(0.0, avail - disp)
        curtail_pct = round(curtail / avail * 100.0, 2) if avail > 0 else 0.0
        per_source[src] = {
            "available_mw": round(avail, 2),
            "dispatched_mw": round(disp, 2),
            "curtailed_mw": round(curtail, 2),
            "curtailment_pct": curtail_pct,
        }

    potential_revenue_loss_eur_h = None
    if market_price_eur_mwh is not None and total_curtailed > 0:
        potential_revenue_loss_eur_h = round(total_curtailed * market_price_eur_mwh, 2)

    uncertainty = {
        "available_std_mw": round(total_available * 0.10, 2),
        "curtailment_std_mw": round(total_curtailed * 0.15, 2),
    }

    results: dict[str, Any] = {
        "total_available_mw": round(total_available, 2),
        "total_dispatched_mw": round(total_dispatched, 2),
        "total_curtailed_mw": round(total_curtailed, 2),
        "curtailment_percent": curtailment_pct,
        "reasons": reasons,
        "per_source": per_source,
    }
    if potential_revenue_loss_eur_h is not None:
        results["potential_revenue_loss_eur_h"] = potential_revenue_loss_eur_h

    return _make_result(
        success=True,
        message=f"Renewable curtailment: {total_curtailed:.1f} MW ({curtailment_pct:.1f}%) "
        f"curtailed due to: {', '.join(reasons) if reasons else 'none'}.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results=results,
    )


def transmission_congestion_monitor(
    network_state: dict[str, Any],
    branch_flows: dict[str, dict[str, float]] | None = None,
    loading_threshold_pct: float = 80.0,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Monitor transmission lines for congestion and available transfer capacity.

    Analyzes branch loading percentages against thresholds to identify
    congested or at-risk lines. Computes available transfer capacity (ATC)
    margins and severity classifications.

    Args:
        network_state: Network state with branch metadata
        branch_flows: Optional dict from AC load flow results (branch_id -> loading info)
        loading_threshold_pct: Loading percentage above which a line is considered congested
        simulated_time: Simulation timestamp

    Returns:
        Structured result with congested_lines, loading statistics, ATC values.
    """
    inputs = {
        "num_branches": len(network_state.get("branches", [])),
        "has_flow_data": branch_flows is not None,
        "loading_threshold_pct": loading_threshold_pct,
    }

    branches = network_state.get("branches", [])
    if not branches and not branch_flows:
        return _make_result(
            success=False,
            message="No branch data available for congestion monitoring",
            inputs=inputs,
            simulated_time=simulated_time,
            results={},
            error_code="NO_BRANCH_DATA",
        )

    congested_lines: list[dict[str, Any]] = []
    max_loading = 0.0
    total_loading_sum = 0.0
    num_with_loading = 0

    # Use provided branch_flows if available, otherwise extract from network_state
    if branch_flows:
        for br_id, flow_data in branch_flows.items():
            loading_pct = float(flow_data.get("loading_pct", flow_data.get("loading", 0.0)))
            max_loading = max(max_loading, loading_pct)
            total_loading_sum += loading_pct
            num_with_loading += 1

            if loading_pct >= loading_threshold_pct:
                from_bus = flow_data.get("from", "unknown")
                to_bus = flow_data.get("to", "unknown")
                line_rating = _TRANSMISSION_LINE_RATINGS.get("overhead", 350.0)

                if loading_pct >= 100.0:
                    severity = "critical"
                elif loading_pct >= 90.0:
                    severity = "severe"
                elif loading_pct >= loading_threshold_pct:
                    severity = "moderate"
                else:
                    severity = "normal"

                available_atc = max(0.0, line_rating * (1.0 - loading_pct / 100.0))

                congested_lines.append({
                    "branch_id": br_id,
                    "from_bus": from_bus,
                    "to_bus": to_bus,
                    "loading_percent": round(loading_pct, 2),
                    "line_rating_mva": line_rating,
                    "available_atc_mva": round(available_atc, 2),
                    "severity": severity,
                })
    else:
        # Estimate from branch metadata
        for i, branch in enumerate(branches):
            if isinstance(branch, dict):
                rating = float(branch.get("rating_mva", branch.get("rate_a", 350.0)))
                flow = float(branch.get("p_mw", branch.get("flow_mw", rating * 0.5)))
                line_id = branch.get("branch_id", f"branch_{i}")
                loading_pct = round(flow / rating * 100.0, 2) if rating > 0 else 0.0
                max_loading = max(max_loading, loading_pct)
                total_loading_sum += loading_pct
                num_with_loading += 1

                if loading_pct >= loading_threshold_pct:
                    severity = "critical" if loading_pct >= 100.0 else "severe" if loading_pct >= 90.0 else "moderate"
                    congested_lines.append({
                        "branch_id": line_id,
                        "from_bus": branch.get("from_bus", "unknown"),
                        "to_bus": branch.get("to_bus", "unknown"),
                        "loading_percent": loading_pct,
                        "line_rating_mva": rating,
                        "available_atc_mva": round(max(0.0, rating * (1.0 - loading_pct / 100.0)), 2),
                        "severity": severity,
                    })

    # Sort by severity and loading
    severity_order = {"critical": 0, "severe": 1, "moderate": 2, "normal": 3}
    congested_lines.sort(key=lambda l: (severity_order.get(l["severity"], 99), -l["loading_percent"]))

    avg_loading = round(total_loading_sum / num_with_loading, 2) if num_with_loading > 0 else 0.0

    uncertainty = {
        "loading_std_pct": 5.0,
        "atc_std_mva": 10.0,
    }

    return _make_result(
        success=True,
        message=f"Congestion monitor: {len(congested_lines)} line(s) at or above "
        f"{loading_threshold_pct}% loading, max loading {max_loading:.1f}%, "
        f"average {avg_loading:.1f}%.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "congested_lines": congested_lines,
            "total_branches": len(branches) or len(branch_flows or {}),
            "num_congested": len(congested_lines),
            "max_loading_percent": round(max_loading, 2),
            "average_loading_percent": avg_loading,
            "severity_summary": {
                "critical": sum(1 for l in congested_lines if l["severity"] == "critical"),
                "severe": sum(1 for l in congested_lines if l["severity"] == "severe"),
                "moderate": sum(1 for l in congested_lines if l["severity"] == "moderate"),
            },
        },
    )


def voltage_stability_margin(
    network_state: dict[str, Any],
    reactive_reserves: dict[str, float] | None = None,
    bus_voltages: dict[str, dict[str, float]] | None = None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Calculate voltage stability margin using PV curve nose point approximation.

    Estimates the distance from the current operating point to the voltage
    collapse point (PV curve nose). Uses reactive power reserves and current
    bus voltage profiles to compute stability index.

    Args:
        network_state: Network state with bus and generator metadata
        reactive_reserves: Dict mapping generator_id to available reactive power (Mvar)
        bus_voltages: Dict from AC load flow (bus_id -> {vm_pu, va_deg})
        simulated_time: Simulation timestamp

    Returns:
        Structured result with margin_pu, critical_voltage, reactive_reserve_mvar, stability_index.
    """
    inputs = {
        "num_buses": len(network_state.get("buses", [])),
        "num_generators": len(network_state.get("generators", [])),
        "reactive_reserves_available": reactive_reserves is not None,
        "bus_voltages_available": bus_voltages is not None,
    }

    buses = network_state.get("buses", [])

    # Calculate total reactive reserve
    total_q_reserve_mvar = 0.0
    if reactive_reserves:
        total_q_reserve_mvar = sum(reactive_reserves.values())
    else:
        # Estimate from generators
        for gen in network_state.get("generators", []):
            if isinstance(gen, dict):
                total_q_reserve_mvar += float(gen.get("max_q_mvar", gen.get("qmax", 50.0)))

    # Find minimum voltage bus
    min_voltage_pu = float("inf")
    min_voltage_bus = "unknown"
    if bus_voltages:
        for bus_id, v in bus_voltages.items():
            vm = float(v.get("vm_pu", 1.0))
            if vm < min_voltage_pu:
                min_voltage_pu = vm
                min_voltage_bus = bus_id
    elif buses:
        for bus in buses:
            if isinstance(bus, dict):
                vm = float(bus.get("vm_pu", bus.get("vn_kv", 110.0) / 110.0))
                if vm < min_voltage_pu:
                    min_voltage_pu = vm
                    min_voltage_bus = bus.get("bus_id", bus.get("name", "unknown"))

    # P-V curve margin approximation
    # Using conservative estimate: critical = 0.80 pu for most systems
    critical_voltage_pu = 0.80
    if min_voltage_pu == float("inf"):
        min_voltage_pu = 1.0
    margin_pu = round(max(0.0, min_voltage_pu - critical_voltage_pu), 4)

    # Reactive power margin index (higher = more stable)
    total_load_mw = sum(
        float(l.get("p_mw", l.get("mw", 0.0)))
        for l in network_state.get("loads", [])
        if isinstance(l, dict)
    )
    if total_load_mw <= 0:
        total_load_mw = 1000.0  # default estimate
    q_margin_mvar = total_q_reserve_mvar - total_load_mw * 0.4  # typical Q demand ~40% of P

    # Stability index: higher is more stable
    # > 0.3: stable, 0.15-0.3: alert, < 0.15: critical
    stability_index = round(max(0.0, min(1.0, (margin_pu / critical_voltage_pu) * (1.0 if q_margin_mvar > 0 else 0.5))), 4)

    if stability_index > 0.3:
        stability_level = "stable"
    elif stability_index > 0.15:
        stability_level = "alert"
    else:
        stability_level = "critical"

    uncertainty = {
        "margin_std_pu": 0.02,
        "stability_index_std": 0.05,
    }

    return _make_result(
        success=True,
        message=f"Voltage stability: margin={margin_pu:.4f} pu, "
        f"stability_index={stability_index:.4f} ({stability_level}).",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "margin_pu": margin_pu,
            "critical_voltage_pu": critical_voltage_pu,
            "min_voltage_pu": round(min_voltage_pu, 4),
            "min_voltage_bus": min_voltage_bus,
            "reactive_reserve_mvar": round(total_q_reserve_mvar, 2),
            "q_margin_mvar": round(q_margin_mvar, 2),
            "stability_index": stability_index,
            "stability_level": stability_level,
        },
    )


def demand_response_potential(
    industrial_loads: list[dict[str, Any]] | None = None,
    ev_flexible_capacity_mw: float = 0.0,
    region: str = "all",
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Calculate available demand response potential from industrial and EV loads.

    Aggregates industrial sheddable loads and EV flexible charging capacity
    to compute total demand response potential. Includes response time
    estimates and cost curves.

    Args:
        industrial_loads: List of dicts with industrial load info (mw, sheddable_mw, response_time_min, cost_eur_mw)
        ev_flexible_capacity_mw: EV flexible charging capacity in MW (from ev_flexible_load_model)
        region: Region filter for industrial loads
        simulated_time: Simulation timestamp

    Returns:
        Structured result with total_potential_mw, categories, response times, costs.
    """
    inputs = {
        "num_industrial_loads": len(industrial_loads) if industrial_loads else 0,
        "ev_flexible_capacity_mw": ev_flexible_capacity_mw,
        "region": region,
    }

    industrial_potential_mw = 0.0
    industrial_response_min = 0.0
    industrial_cost = 0.0
    load_categories: list[dict[str, Any]] = []

    if industrial_loads:
        for load in industrial_loads:
            if not isinstance(load, dict):
                continue
            load_region = load.get("region", "all")
            if region != "all" and load_region != region:
                continue
            sheddable_mw = float(load.get("sheddable_mw", load.get("mw", 0.0) * 0.3))
            resp_time = float(load.get("response_time_min", 15.0))
            cost = float(load.get("cost_eur_mw", 100.0))
            industrial_potential_mw += sheddable_mw
            industrial_response_min = max(industrial_response_min, resp_time)
            industrial_cost += sheddable_mw * cost
            load_categories.append({
                "load_id": load.get("load_id", load.get("name", "unknown")),
                "sheddable_mw": round(sheddable_mw, 2),
                "response_time_min": resp_time,
                "cost_eur_mw": cost,
                "type": load.get("type", "industrial"),
            })

    # EV contribution: typically available in 5-15 minutes
    ev_response_min = 10.0 if ev_flexible_capacity_mw > 0 else 0.0
    ev_cost_per_mw = 80.0  # EUR/MW for EV load shifting

    total_potential_mw = industrial_potential_mw + ev_flexible_capacity_mw
    weighted_response_min = (
        (industrial_potential_mw * industrial_response_min + ev_flexible_capacity_mw * ev_response_min)
        / total_potential_mw
        if total_potential_mw > 0
        else 0.0
    )
    avg_cost_per_mw = (
        (industrial_cost + ev_flexible_capacity_mw * ev_cost_per_mw) / total_potential_mw
        if total_potential_mw > 0
        else 0.0
    )

    # Duration estimate: EVs 2h, industrial 4h average
    duration_max_h = 3.0 if ev_flexible_capacity_mw > 0 and industrial_potential_mw > 0 else 2.0

    if total_potential_mw > 0:
        load_categories.append({
            "load_id": "ev_flexible",
            "sheddable_mw": round(ev_flexible_capacity_mw, 2),
            "response_time_min": ev_response_min,
            "cost_eur_mw": ev_cost_per_mw,
            "type": "ev",
        })

    uncertainty = {
        "potential_std_mw": round(total_potential_mw * 0.20, 2),
        "response_time_std_min": 5.0,
    }

    return _make_result(
        success=True,
        message=f"Demand response potential: {total_potential_mw:.1f} MW total, "
        f"response time ~{weighted_response_min:.0f} min, "
        f"avg cost {avg_cost_per_mw:.0f} EUR/MW.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "total_potential_mw": round(total_potential_mw, 2),
            "industrial_potential_mw": round(industrial_potential_mw, 2),
            "ev_potential_mw": round(ev_flexible_capacity_mw, 2),
            "response_time_min": round(weighted_response_min, 1),
            "cost_per_mw_eur": round(avg_cost_per_mw, 2),
            "duration_max_h": duration_max_h,
            "load_categories": load_categories,
        },
    )


def black_start_capability(
    generators: list[dict[str, Any]],
    network_topology: dict[str, Any] | None = None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Identify generators capable of black-starting the grid after total blackout.

    Black-start capable generators include hydro units (with local auxiliary power),
    gas turbines, and some CCGT plants. Analyzes generator fleet for restoration
    sequencing and estimates restoration time.

    Args:
        generators: List of generator dicts with type, capacity, black_start_capable flag
        network_topology: Optional grid topology for path planning
        simulated_time: Simulation timestamp

    Returns:
        Structured result with capable_generators, restoration_time, sequence.
    """
    inputs = {
        "num_generators": len(generators),
        "topology_available": network_topology is not None,
    }

    if not generators:
        return _make_result(
            success=False,
            message="No generator data provided",
            inputs=inputs,
            simulated_time=simulated_time,
            results={},
            error_code="NO_GENERATOR_DATA",
        )

    capable: list[dict[str, Any]] = []
    total_black_start_capacity_mw = 0.0

    for gen in generators:
        if not isinstance(gen, dict):
            continue
        gen_id = gen.get("generator_id", gen.get("name", gen.get("id", "unknown")))
        fuel_type = str(gen.get("fuel_type", gen.get("type", ""))).lower()
        capacity_mw = float(gen.get("p_mw", gen.get("max_p_mw", gen.get("capacity_mw", 0.0))))

        # Check explicit flag first, then infer from fuel type
        black_start_raw = gen.get("black_start_capable", gen.get("black_start", None))
        explicit_flag = black_start_raw is not None

        if explicit_flag:
            black_start = bool(black_start_raw)
        else:
            black_start = fuel_type in _BLACK_START_CAPABLE

        if not black_start:
            continue

        # Determine start time: fuel-type based, or default if explicit flag
        start_time_min = 15.0
        if fuel_type == "hydro":
            start_time_min = 5.0
        elif fuel_type in ("gas", "natural_gas"):
            start_time_min = 10.0
        elif fuel_type == "ccgt":
            start_time_min = 20.0
        elif "biomass" in fuel_type:
            start_time_min = 30.0
        elif not explicit_flag:
            black_start = False
            continue

        capable.append({
            "generator_id": gen_id,
            "fuel_type": fuel_type,
            "capacity_mw": round(capacity_mw, 2),
            "start_time_min": start_time_min,
            "location": gen.get("bus_id", gen.get("bus", "unknown")),
        })
        total_black_start_capacity_mw += capacity_mw

    # Sort by start time (fastest first) for restoration sequence
    capable.sort(key=lambda g: g["start_time_min"])

    # Build restoration sequence recommendation
    sequence: list[dict[str, Any]] = []
    for i, gen in enumerate(capable, 1):
        sequence.append({
            "step": i,
            "generator_id": gen["generator_id"],
            "action": f"Start {gen['generator_id']} ({gen['fuel_type']}, {gen['capacity_mw']} MW)",
            "estimated_time_min": gen["start_time_min"],
        })

    # Estimate total restoration time
    if sequence:
        restoration_time_min = sequence[-1]["estimated_time_min"] + len(sequence) * 5
    else:
        restoration_time_min = 0.0

    total_grid_capacity_mw = sum(
        float(g.get("p_mw", g.get("max_p_mw", g.get("capacity_mw", 0.0))))
        for g in generators if isinstance(g, dict)
    )

    uncertainty = {
        "start_time_std_min": 5.0,
        "restoration_time_std_min": 15.0,
    }

    return _make_result(
        success=True,
        message=f"Black start analysis: {len(capable)} generators capable ({total_black_start_capacity_mw:.0f} MW), "
        f"estimated restoration time ~{restoration_time_min:.0f} min.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "capable_generators": capable,
            "total_black_start_capacity_mw": round(total_black_start_capacity_mw, 2),
            "total_grid_capacity_mw": round(total_grid_capacity_mw, 2),
            "black_start_ratio_pct": round(
                total_black_start_capacity_mw / total_grid_capacity_mw * 100.0, 2
            ) if total_grid_capacity_mw > 0 else 0.0,
            "restoration_time_estimate_min": round(restoration_time_min, 1),
            "sequence_recommendation": sequence,
        },
    )


def synchrophasor_monitor(
    bus_voltages: dict[str, dict[str, float]] | None = None,
    network_topology: dict[str, Any] | None = None,
    pmu_locations: list[str] | None = None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Simulate PMU (synchrophasor) data quality and grid observability metrics.

    Analyzes voltage angle differences between buses to detect potential
    islanding conditions and assesses PMU coverage quality.

    Args:
        bus_voltages: Dict from state_estimation or AC load flow (bus_id -> {vm_pu, va_deg})
        network_topology: Network topology for connectivity analysis
        pmu_locations: List of bus IDs where PMUs are installed (optional)
        simulated_time: Simulation timestamp

    Returns:
        Structured result with pmu_count, coverage, angle_differences, islanding_risk.
    """
    inputs = {
        "num_buses_with_voltage": len(bus_voltages) if bus_voltages else 0,
        "topology_available": network_topology is not None,
        "num_pmu_locations": len(pmu_locations) if pmu_locations else 0,
    }

    if not bus_voltages:
        return _make_result(
            success=False,
            message="No bus voltage data available for synchrophasor monitoring",
            inputs=inputs,
            simulated_time=simulated_time,
            results={},
            error_code="NO_VOLTAGE_DATA",
        )

    total_buses = len(bus_voltages)
    pmu_buses = pmu_locations if pmu_locations else list(bus_voltages.keys())[:max(1, total_buses // 3)]

    pmu_count = len(pmu_buses)
    coverage_percent = round(pmu_count / total_buses * 100.0, 2) if total_buses > 0 else 0.0

    # Calculate angle differences between neighboring buses
    bus_ids = list(bus_voltages.keys())
    angle_differences: list[dict[str, Any]] = []
    max_angle_diff = 0.0
    min_angle_diff = 360.0

    for i in range(len(bus_ids)):
        for j in range(i + 1, min(i + 5, len(bus_ids))):  # Check nearby buses
            va_i = float(bus_voltages[bus_ids[i]].get("va_deg", 0.0))
            va_j = float(bus_voltages[bus_ids[j]].get("va_deg", 0.0))
            diff = abs(va_i - va_j)
            if diff > 180.0:
                diff = 360.0 - diff
            if diff < min_angle_diff and i != j:
                min_angle_diff = diff
            if diff > max_angle_diff:
                max_angle_diff = diff
                angle_differences.append({
                    "bus_a": bus_ids[i],
                    "bus_b": bus_ids[j],
                    "angle_diff_deg": round(diff, 3),
                })

    # Sort by descending angle difference (largest first = most concerning)
    angle_differences.sort(key=lambda d: d["angle_diff_deg"], reverse=True)
    angle_differences = angle_differences[:20]  # Top 20

    # Islanding risk assessment based on angle spread
    # Large angle differences (>30°) suggest potential islanding
    # Normal operation: < 10°, Alert: 10-30°, Critical: > 30°
    if max_angle_diff > 30.0:
        islanding_risk = "high"
    elif max_angle_diff > 10.0:
        islanding_risk = "moderate"
    else:
        islanding_risk = "low"

    # PMU data quality metrics
    frequency_estimate_hz = 50.0 + (sum(
        float(bus_voltages[bid].get("va_deg", 0.0))
        for bid in bus_ids
    ) / total_buses) * 0.001  # Approximate frequency from angle drift
    frequency_estimate_hz = round(max(49.5, min(50.5, frequency_estimate_hz)), 3)

    uncertainty = {
        "angle_measurement_std_deg": 0.5,
        "frequency_std_hz": 0.005,
    }

    return _make_result(
        success=True,
        message=f"Synchrophasor monitor: {pmu_count} PMUs covering {coverage_percent:.1f}% "
        f"of buses, max angle diff {max_angle_diff:.1f}°, islanding risk: {islanding_risk}.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "pmu_count": pmu_count,
            "total_buses": total_buses,
            "coverage_percent": coverage_percent,
            "frequency_estimate_hz": frequency_estimate_hz,
            "max_angle_difference_deg": round(max_angle_diff, 3),
            "islanding_risk": islanding_risk,
            "angle_differences": angle_differences,
            "observable_buses": pmu_buses[:20],
        },
    )


def weather_impact_assessment(
    temperature_c: float,
    wind_speed_ms: float,
    solar_irradiance_wm2: float,
    region: str = "all",
    grid_constraints: dict[str, Any] | None = None,
    simulated_time: datetime | None = None,
) -> dict[str, Any]:
    """Assess how weather conditions affect grid operations.

    Combines temperature-to-demand effects, wind/solar generation impacts,
    and transmission line thermal ratings to produce a holistic weather
    impact assessment with risk classification.

    Args:
        temperature_c: Current temperature in Celsius
        wind_speed_ms: Current wind speed in m/s
        solar_irradiance_wm2: Current solar irradiance in W/m²
        region: Region to assess
        grid_constraints: Optional grid constraint flags
        simulated_time: Simulation timestamp

    Returns:
        Structured result with demand_impact, generation_impact, line_rating_impact, risk_level.
    """
    inputs = {
        "temperature_c": temperature_c,
        "wind_speed_ms": wind_speed_ms,
        "solar_irradiance_wm2": solar_irradiance_wm2,
        "region": region,
    }

    # --- Demand impact from temperature ---
    base_demand_by_region: dict[str, float] = {
        "bohemia-west": 900.0,
        "bohemia-east": 1200.0,
        "moravia": 850.0,
        "silesia": 1000.0,
        "all": 3950.0,
    }
    base_demand = base_demand_by_region.get(region, 950.0)

    if temperature_c < 18.0:
        heating_mw = (18.0 - temperature_c) * 18.0
        cooling_mw = 0.0
    elif temperature_c > 22.0:
        heating_mw = 0.0
        cooling_mw = (temperature_c - 22.0) * 12.0
    else:
        heating_mw = 0.0
        cooling_mw = 0.0

    demand_impact_mw = heating_mw + cooling_mw
    demand_impact_pct = round(demand_impact_mw / base_demand * 100.0, 2) if base_demand > 0 else 0.0

    # Demand impact direction
    if demand_impact_mw > 0:
        demand_direction = "increase"
    elif demand_impact_mw < 0:
        demand_direction = "decrease"
    else:
        demand_direction = "neutral"

    # --- Generation impact from wind/solar ---
    # Wind: rated at ~2MW per turbine at 12 m/s
    wind_capacity_factor = min(1.0, max(0.0, (wind_speed_ms - 3.0) / 9.0)) if wind_speed_ms >= 3.0 else 0.0
    wind_generation_mw = 500.0 * wind_capacity_factor  # Approx 500 MW installed wind
    wind_generation_pct = round(wind_capacity_factor * 100.0, 1)

    # Solar: irradiance-based estimate
    solar_efficiency = 0.18
    solar_capacity_mw = 450.0  # Approx 450 MW installed solar
    solar_generation_mw = solar_capacity_mw * (solar_irradiance_wm2 / 1000.0) * solar_efficiency
    solar_generation_mw = max(0.0, min(solar_capacity_mw, solar_generation_mw))

    generation_impact_mw = wind_generation_mw + solar_generation_mw
    generation_impact_pct = round(generation_impact_mw / base_demand * 100.0, 2) if base_demand > 0 else 0.0

    # --- Transmission line rating impact ---
    # Higher temperature = lower line rating (thermal limit)
    line_rating_reference_c = 25.0
    line_rating_derate_factor = 1.0 - max(0.0, (temperature_c - line_rating_reference_c) * 0.01)
    line_rating_derate_factor = max(0.7, min(1.0, line_rating_derate_factor))
    line_rating_impact_pct = round((1.0 - line_rating_derate_factor) * -100.0, 1)

    # Wind can increase line cooling (dynamic line rating)
    if wind_speed_ms > 5.0:
        line_cooling_boost = min(0.10, (wind_speed_ms - 5.0) * 0.02)
        line_rating_derate_factor += line_cooling_boost

    # Storm risk
    storm_risk = "none"
    if wind_speed_ms > 25.0:
        storm_risk = "severe"
    elif wind_speed_ms > 18.0:
        storm_risk = "elevated"
    elif wind_speed_ms > 12.0:
        storm_risk = "moderate"

    # Ice/snow risk
    icing_risk = "none"
    if temperature_c < 0 and wind_speed_ms > 5.0:
        icing_risk = "moderate"
    elif temperature_c < 2 and wind_speed_ms > 8.0:
        icing_risk = "elevated"

    # --- Overall risk level ---
    risk_score = 0.0
    if abs(demand_impact_pct) > 10.0:
        risk_score += 2
    if wind_capacity_factor < 0.1 or wind_capacity_factor > 0.9:
        risk_score += 1
    if line_rating_derate_factor < 0.85:
        risk_score += 2
    if storm_risk in ("severe", "elevated"):
        risk_score += 3
    if icing_risk in ("moderate", "elevated"):
        risk_score += 2
    if grid_constraints:
        if grid_constraints.get("congested", False):
            risk_score += 1

    if risk_score >= 6:
        overall_risk = "critical"
    elif risk_score >= 3:
        overall_risk = "elevated"
    else:
        overall_risk = "normal"

    uncertainty = {
        "demand_impact_std_mw": round(abs(demand_impact_mw) * 0.20, 2),
        "generation_impact_std_mw": round(generation_impact_mw * 0.25, 2),
        "line_rating_std_pct": 3.0,
    }

    return _make_result(
        success=True,
        message=f"Weather impact: demand {demand_direction} by {abs(demand_impact_mw):.0f} MW, "
        f"renewable gen {generation_impact_mw:.0f} MW, "
        f"line rating {line_rating_impact_pct:+.1f}%, overall risk: {overall_risk}.",
        inputs=inputs,
        simulated_time=simulated_time,
        uncertainty=uncertainty,
        results={
            "demand_impact_mw": round(demand_impact_mw, 2),
            "demand_impact_pct": demand_impact_pct,
            "demand_direction": demand_direction,
            "generation_impact_mw": round(generation_impact_mw, 2),
            "generation_impact_pct": generation_impact_pct,
            "wind_generation_mw": round(wind_generation_mw, 2),
            "wind_capacity_factor_pct": wind_generation_pct,
            "solar_generation_mw": round(solar_generation_mw, 2),
            "line_rating_impact_pct": line_rating_impact_pct,
            "line_rating_factor": round(line_rating_derate_factor, 3),
            "storm_risk": storm_risk,
            "icing_risk": icing_risk,
            "overall_risk_level": overall_risk,
        },
    )
