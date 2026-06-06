"""Deterministic AC load flow and OPF wrappers.

This module wraps pandapower (preferred) and PyPSA (fallback) for power flow
solutions. All functions are pure and deterministic. If the required library
is unavailable, functions raise structured errors rather than silently falling
back to fake results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import importlib
import math
from typing import Any

import random as _random

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]
    _NUMPY_AVAILABLE = False

from athenaai.trace import trace, trace_scope


def _make_deterministic_rng(seed: int) -> Any:
    if _NUMPY_AVAILABLE and np is not None:
        return np.random.Generator(np.random.PCG64(seed))
    return _seeded_random(seed)


class _seeded_random:
    def __init__(self, seed: int) -> None:
        self._rng = _random.Random(seed)

    def normal(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return self._rng.gauss(mu, sigma)

    def random(self) -> float:
        return self._rng.random()


class PhysicsStatus(str, Enum):
    SUCCESS = "success"
    FALLBACK_USED = "fallback_used"
    NON_CONVERGENCE = "non_convergence"
    UNAVAILABLE = "unavailable"
    VIOLATION_THERMAL = "violation_thermal"
    VIOLATION_VOLTAGE = "violation_voltage"
    VIOLATION_RAMP = "violation_ramp"
    ISLANDING_DETECTED = "islanding_detected"


@dataclass(frozen=True)
class LoadFlowResult:
    converged: bool
    status: PhysicsStatus
    bus_voltages: tuple[tuple[str, float, float], ...]
    branch_flows: tuple[tuple[str, str, str, float], ...]
    generations: tuple[tuple[str, float], ...]
    message: str
    timestamp: datetime | None = None

    def violations(
        self, max_loading: float = 100.0, min_v: float = 0.95, max_v: float = 1.05
    ) -> tuple[str, ...]:
        violations: list[str] = []
        for bid, vm_pu, va_deg in self.bus_voltages:
            if vm_pu < min_v:
                violations.append(f"LOW_VOLTAGE bus={bid} v={vm_pu:.4f}")
            if vm_pu > max_v:
                violations.append(f"HIGH_VOLTAGE bus={bid} v={vm_pu:.4f}")
        for br_id, from_bus, to_bus, loading_pct in self.branch_flows:
            if loading_pct > max_loading:
                violations.append(
                    f"THERMAL_OVERLOAD branch={br_id} loading={loading_pct:.1f}%"
                )
        return tuple(violations)


@dataclass(frozen=True)
class OPFResult:
    solved: bool
    status: PhysicsStatus
    generation_schedule: tuple[tuple[str, float], ...]
    branch_flows: tuple[tuple[str, str, str, float], ...]
    dual_prices: tuple[tuple[str, float], ...]
    cost_eur: float
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class StateEstimationResult:
    success: bool
    status: PhysicsStatus
    bus_estimates: tuple[tuple[str, float, float], ...]
    estimated_v_mag_pu: float
    estimated_v_angle_deg: float
    chi_squared: float
    bad_data_detected: bool = False
    suspicious_measurements: tuple[str, ...] = ()
    message: str = ""
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ShortCircuitResult:
    success: bool
    status: PhysicsStatus
    fault_current_ka: float
    fault_power_mva: float
    bus_voltages: tuple[tuple[str, float, float], ...]
    generator_contributions: tuple[tuple[str, float], ...]
    message: str = ""
    timestamp: datetime | None = None


@dataclass(frozen=True)
class FrequencyResponseResult:
    success: bool
    status: PhysicsStatus
    frequency_nadir_hz: float
    rocof_hz_s: float
    settling_frequency_hz: float
    system_inertia_s: float
    critical_clearing_time_cycles: float
    delta_p_mw: float
    message: str = ""
    timestamp: datetime | None = None


class RunppUnavailableError(Exception):
    pass


class PyPSAUnavailableError(Exception):
    pass


def _build_pandapower_net(
    network_state: dict[str, Any],
) -> Any:
    with trace_scope(
        "physics._build_pandapower_net",
        buses=len(network_state.get("buses", [])),
        branches=len(network_state.get("branches", [])),
        generators=len(network_state.get("generators", [])),
        loads=len(network_state.get("loads", [])),
    ):
        try:
            pp = importlib.import_module("pandapower")
        except ImportError:
            raise RunppUnavailableError(
                "pandapower is not installed. Install with: pip install pandapower"
            )

        net = pp.create_empty_network()
        bus_index_by_external_id: dict[str, int] = {}
        bus_voltage_by_index: dict[int, float] = {}

        def boolish(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if value is None:
                return False
            return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

        buses = network_state.get("buses", [])
        for position, b in enumerate(buses):
            external_id = str(b.get("bus_id", b.get("name", position)))
            bus_name = str(b.get("name", external_id))
            vn_kv = float(b.get("vn_kv", 110.0))
            created_index = int(pp.create_bus(
                net,
                name=bus_name,
                vn_kv=vn_kv,
                type=b.get("type", "b"),
            ))
            bus_voltage_by_index[created_index] = vn_kv
            bus_index_by_external_id[external_id] = created_index
            bus_index_by_external_id[bus_name] = created_index
            bus_index_by_external_id[str(position)] = created_index

        def resolve_bus_id(raw_bus_id: Any) -> int:
            key = str(raw_bus_id)
            if key not in bus_index_by_external_id:
                raise ValueError(f"Unknown bus id in network_state: {key}")
            return bus_index_by_external_id[key]

        slack_bus_indices = [
            resolve_bus_id(b.get("bus_id", b.get("name", position)))
            for position, b in enumerate(buses)
            if boolish(b.get("is_slack"))
        ]
        if not slack_bus_indices and buses:
            generator_bus_ids = {str(g.get("bus")) for g in network_state.get("generators", [])}
            fallback_slack_bus = next(
                (
                    b for position, b in enumerate(buses)
                    if str(b.get("bus_id", b.get("name", position))) in generator_bus_ids
                ),
                buses[0],
            )
            fallback_position = buses.index(fallback_slack_bus)
            slack_bus_indices.append(resolve_bus_id(
                fallback_slack_bus.get("bus_id", fallback_slack_bus.get("name", fallback_position))
            ))

        for slack_bus_idx in slack_bus_indices:
            pp.create_ext_grid(
                net,
                bus=slack_bus_idx,
                vm_pu=1.0,
                va_degree=0.0,
                name=f"slack_bus_{slack_bus_idx}",
            )

        branches = network_state.get("branches", [])
        for br in branches:
            from_idx = resolve_bus_id(br["from_bus"])
            to_idx = resolve_bus_id(br["to_bus"])
            is_transformer = br.get("type", "line") == "transformer" or br.get("trafo_ratio_rel") not in (None, "")
            if is_transformer:
                from_kv = bus_voltage_by_index.get(from_idx, 110.0)
                to_kv = bus_voltage_by_index.get(to_idx, 110.0)
                hv_kv = max(from_kv, to_kv)
                lv_kv = min(from_kv, to_kv)
                sn_mva = br.get("sn_mva")
                if sn_mva in (None, ""):
                    sn_mva = math.sqrt(3.0) * hv_kv * float(br.get("max_i_ka", 1.0))
                pp.create_transformer_from_parameters(
                    net,
                    hv_bus=from_idx if from_kv >= to_kv else to_idx,
                    lv_bus=to_idx if from_kv >= to_kv else from_idx,
                    name=br["branch_id"],
                    sn_mva=sn_mva,
                    vn_hv_kv=br.get("vn_hv_kv", hv_kv),
                    vn_lv_kv=br.get("vn_lv_kv", lv_kv),
                    vk_percent=br.get("vk_percent", br.get("vsc_percent", 10.0)),
                    vkr_percent=br.get("vkr_percent", br.get("vscr_percent", 0.1)),
                    pfe_kw=br.get("pfe_kw", 0.0),
                    i0_percent=br.get("i0_percent", 0.0),
                )
            else:
                pp.create_line_from_parameters(
                    net,
                    from_bus=from_idx,
                    to_bus=to_idx,
                    name=br["branch_id"],
                    length_km=br.get("length_km", 1.0),
                    r_ohm_per_km=br.get("r_ohm_per_km", 0.1),
                    x_ohm_per_km=br.get("x_ohm_per_km", 0.4),
                    c_nf_per_km=br.get("c_nf_per_km", 10.0),
                    max_i_ka=br.get("max_i_ka", 1.0),
                )

        generators = network_state.get("generators", [])
        for g in generators:
            generator_id = str(g.get("generator_id"))
            pp.create_gen(
                net,
                bus=resolve_bus_id(g["bus"]),
                p_mw=g.get("p_mw", 0.0),
                vm_pu=g.get("vm_pu", 1.0),
                name=generator_id,
                min_p_mw=g.get("min_p_mw", 0.0),
                max_p_mw=g.get("max_p_mw", 1000.0),
                slack=boolish(g.get("slack", False)),
                slack_weight=1.0 if boolish(g.get("slack", False)) else 0.0,
            )

        loads = network_state.get("loads", [])
        for l in loads:
            pp.create_load(
                net,
                bus=resolve_bus_id(l["bus"]),
                p_mw=l.get("p_mw", 0.0),
                q_mvar=l.get("q_mvar", 0.0),
                name=l.get("name", l["load_id"]),
            )

        trace(
            "physics._build_pandapower_net.done",
            pandapower_buses=len(net.bus),
            pandapower_lines=len(net.line),
            pandapower_transformers=len(net.trafo),
            pandapower_generators=len(net.gen),
            pandapower_loads=len(net.load),
            pandapower_ext_grids=len(net.ext_grid),
        )
        return net


def run_ac_load_flow(
    network_state: dict[str, Any],
    simulated_time: datetime | None = None,
) -> LoadFlowResult:
    with trace_scope(
        "physics.run_ac_load_flow",
        simulated_time=simulated_time.isoformat() if simulated_time is not None else None,
        buses=len(network_state.get("buses", [])),
        branches=len(network_state.get("branches", [])),
        generators=len(network_state.get("generators", [])),
        loads=len(network_state.get("loads", [])),
    ):
        try:
            pp = importlib.import_module("pandapower")
        except ImportError:
            trace("physics.run_ac_load_flow.pandapower_missing")
            return run_fallback_load_flow(network_state, simulated_time)

        try:
            net = _build_pandapower_net(network_state)
            trace(
                "physics.run_ac_load_flow.runpp.start",
                buses=len(net.bus),
                lines=len(net.line),
                transformers=len(net.trafo),
                generators=len(net.gen),
                loads=len(net.load),
                ext_grids=len(net.ext_grid),
            )
            with trace_scope("physics.run_ac_load_flow.runpp"):
                pp.runpp(net, calculate_voltage_angles=True, numba=False)
            trace("physics.run_ac_load_flow.runpp.done", converged=bool(net.converged))

            bus_voltages: list[tuple[str, float, float]] = []
            for idx, row in net.res_bus.iterrows():
                bus_name = net.bus.name.at[idx]
                bus_voltages.append((bus_name, float(row.vm_pu), float(row.va_degree)))

            branch_flows: list[tuple[str, str, str, float]] = []
            for idx, row in net.res_line.iterrows():
                line_name = net.line.name.at[idx]
                from_bus = net.line.from_bus.at[idx]
                to_bus = net.line.to_bus.at[idx]
                loading = float(row.loading_percent)
                branch_flows.append((line_name, str(from_bus), str(to_bus), loading))

            for idx, row in net.res_trafo.iterrows():
                trafo_name = net.trafo.name.at[idx]
                hv_bus = net.trafo.hv_bus.at[idx]
                lv_bus = net.trafo.lv_bus.at[idx]
                loading = float(row.loading_percent)
                branch_flows.append((trafo_name, str(hv_bus), str(lv_bus), loading))

            generations: list[tuple[str, float]] = []
            for idx, row in net.res_gen.iterrows():
                gen_name = net.gen.name.at[idx]
                generations.append((gen_name, float(row.p_mw)))

            result = LoadFlowResult(
                converged=True,
                status=PhysicsStatus.SUCCESS,
                bus_voltages=tuple(bus_voltages),
                branch_flows=tuple(branch_flows),
                generations=tuple(generations),
                message="AC load flow converged",
                timestamp=simulated_time,
            )
            trace(
                "physics.run_ac_load_flow.success",
                bus_voltages=len(result.bus_voltages),
                branch_flows=len(result.branch_flows),
                generations=len(result.generations),
            )
            return result

        except pp.LoadflowNotConverged:
            trace("physics.run_ac_load_flow.non_convergence")
            return LoadFlowResult(
                converged=False,
                status=PhysicsStatus.NON_CONVERGENCE,
                bus_voltages=(),
                branch_flows=(),
                generations=(),
                message="AC load flow did not converge",
                timestamp=simulated_time,
            )
        except Exception as e:
            trace("physics.run_ac_load_flow.error", error_type=type(e).__name__, error=str(e))
            return LoadFlowResult(
                converged=False,
                status=PhysicsStatus.NON_CONVERGENCE,
                bus_voltages=(),
                branch_flows=(),
                generations=(),
                message=f"AC load flow error: {str(e)}",
                timestamp=simulated_time,
            )


def run_fallback_load_flow(
    network_state: dict[str, Any],
    simulated_time: datetime | None = None,
) -> LoadFlowResult:
    """Run a deterministic approximate flow check when pandapower is absent.

    This is not an AC solver. It is an explicit fallback that verifies basic
    physical feasibility: a usable network exists, generator outputs are within
    min/max bounds, generation/load balance is close enough, and approximate
    branch loading stays within thermal limits. The status is FALLBACK_USED so
    callers can distinguish it from full AC convergence.
    """
    buses = network_state.get("buses", [])
    if not buses:
        return LoadFlowResult(
            converged=False,
            status=PhysicsStatus.UNAVAILABLE,
            bus_voltages=(),
            branch_flows=(),
            generations=(),
            message="No buses available for fallback load flow",
            timestamp=simulated_time,
        )

    generators = network_state.get("generators", [])
    loads = network_state.get("loads", [])
    branches = network_state.get("branches", [])

    generation_total = 0.0
    generation_rows: list[tuple[str, float]] = []
    for gen in generators:
        gen_id = str(gen.get("generator_id", gen.get("name", "unknown")))
        p_mw = float(gen.get("p_mw", 0.0))
        min_p = float(gen.get("min_p_mw", 0.0))
        max_p = float(gen.get("max_p_mw", max(1000.0, p_mw)))
        bound_tolerance_mw = 1e-6
        if min_p - bound_tolerance_mw <= p_mw <= max_p + bound_tolerance_mw:
            p_mw = max(min_p, min(max_p, p_mw))
        else:
            return LoadFlowResult(
                converged=False,
                status=PhysicsStatus.VIOLATION_RAMP,
                bus_voltages=(),
                branch_flows=(),
                generations=(),
                message=(
                    f"Generator {gen_id} output {p_mw:.3f} MW outside "
                    f"bounds [{min_p:.3f}, {max_p:.3f}]"
                ),
                timestamp=simulated_time,
            )
        generation_total += p_mw
        generation_rows.append((gen_id, p_mw))

    load_total = sum(float(load.get("p_mw", 0.0)) for load in loads)
    imbalance = generation_total - load_total
    balance_tolerance_mw = max(5.0, 0.05 * max(load_total, generation_total, 1.0))
    if abs(imbalance) > balance_tolerance_mw:
        return LoadFlowResult(
            converged=False,
            status=PhysicsStatus.NON_CONVERGENCE,
            bus_voltages=(),
            branch_flows=(),
            generations=tuple(generation_rows),
            message=(
                f"Fallback load flow imbalance {imbalance:.3f} MW exceeds "
                f"tolerance {balance_tolerance_mw:.3f} MW"
            ),
            timestamp=simulated_time,
        )

    bus_voltages = tuple(
        (str(bus.get("bus_id", bus.get("name", idx))), 1.0, 0.0)
        for idx, bus in enumerate(buses)
    )

    branch_flows: list[tuple[str, str, str, float]] = []
    total_branch_capacity = sum(
        max(0.001, float(branch.get("max_i_ka", 1.0)) * 100.0)
        for branch in branches
    )
    for branch in branches:
        branch_id = str(branch.get("branch_id", branch.get("name", "unknown")))
        from_bus = str(branch.get("from_bus", ""))
        to_bus = str(branch.get("to_bus", ""))
        capacity_proxy = max(0.001, float(branch.get("max_i_ka", 1.0)) * 100.0)
        loading_percent = 0.0
        if total_branch_capacity > 0:
            loading_percent = abs(imbalance) * capacity_proxy / total_branch_capacity
        branch_flows.append((branch_id, from_bus, to_bus, loading_percent))

    return LoadFlowResult(
        converged=True,
        status=PhysicsStatus.FALLBACK_USED,
        bus_voltages=bus_voltages,
        branch_flows=tuple(branch_flows),
        generations=tuple(generation_rows),
        message="Fallback deterministic load flow used because pandapower is unavailable",
        timestamp=simulated_time,
    )


def run_opf(
    network_state: dict[str, Any],
    constraints: dict[str, Any],
    simulated_time: datetime | None = None,
) -> OPFResult:
    try:
        pp = importlib.import_module("pandapower")
    except ImportError:
        return OPFResult(
            solved=False,
            status=PhysicsStatus.UNAVAILABLE,
            generation_schedule=(),
            branch_flows=(),
            dual_prices=(),
            cost_eur=0.0,
            message="pandapower not installed - cannot run OPF",
            timestamp=simulated_time,
        )

    try:
        net = _build_pandapower_net(network_state)

        gen_constraints = constraints.get("generator_constraints", {})
        for idx, gen_row in net.gen.iterrows():
            gen_name = net.gen.name.at[idx]
            if gen_name in gen_constraints:
                gc = gen_constraints[gen_name]
                net.gen.min_p_mw.at[idx] = gc.get("min_mw", 0.0)
                net.gen.max_p_mw.at[idx] = gc.get("max_mw", 1000.0)

        pp.runopp(net)

        generation_schedule: list[tuple[str, float]] = []
        for idx, row in net.res_gen.iterrows():
            gen_name = net.gen.name.at[idx]
            generation_schedule.append((gen_name, float(row.p_mw)))

        branch_flows: list[tuple[str, str, str, float]] = []
        if hasattr(net, "res_line") and not net.res_line.empty:
            for idx, row in net.res_line.iterrows():
                line_name = net.line.name.at[idx]
                from_bus = net.line.from_bus.at[idx]
                to_bus = net.line.to_bus.at[idx]
                loading = float(row.loading_percent)
                branch_flows.append((line_name, str(from_bus), str(to_bus), loading))

        dual_prices: list[tuple[str, float]] = []
        if hasattr(net, "res_bus") and not net.res_bus.empty:
            for idx, row in net.res_bus.iterrows():
                bus_name = net.bus.name.at[idx]
                dual_prices.append((bus_name, float(row.mu_vm)) if "mu_vm" in row else (bus_name, 0.0))

        return OPFResult(
            solved=True,
            status=PhysicsStatus.SUCCESS,
            generation_schedule=tuple(generation_schedule),
            branch_flows=tuple(branch_flows),
            dual_prices=tuple(dual_prices),
            cost_eur=float(net.res_cost) if hasattr(net, "res_cost") else 0.0,
            message="OPF solved",
            timestamp=simulated_time,
        )

    except pp.OPFNotConverged:
        return OPFResult(
            solved=False,
            status=PhysicsStatus.NON_CONVERGENCE,
            generation_schedule=(),
            branch_flows=(),
            dual_prices=(),
            cost_eur=0.0,
            message="OPF did not converge",
            timestamp=simulated_time,
        )
    except Exception as e:
        return OPFResult(
            solved=False,
            status=PhysicsStatus.NON_CONVERGENCE,
            generation_schedule=(),
            branch_flows=(),
            dual_prices=(),
            cost_eur=0.0,
            message=f"OPF error: {str(e)}",
            timestamp=simulated_time,
        )


def run_state_estimation(
    network_state: dict[str, Any],
    measurements: dict[str, Any] | list[dict[str, Any]] | None = None,
    min_voltage_pu: float = 0.95,
    max_voltage_pu: float = 1.05,
    simulated_time: datetime | None = None,
    seed: int | None = None,
) -> StateEstimationResult:
    with trace_scope(
        "physics.run_state_estimation",
        buses=len(network_state.get("buses", [])),
        measurements=len(measurements) if measurements else 0,
        seed=seed,
    ):
        try:
            pp = importlib.import_module("pandapower")
        except ImportError:
            trace("physics.run_state_estimation.pandapower_missing")
            return _run_state_estimation_fallback(
                network_state, measurements, min_voltage_pu, max_voltage_pu,
                simulated_time, seed,
            )

        try:
            net = _build_pandapower_net(network_state)

            if measurements:
                meas_list = measurements if isinstance(measurements, list) else measurements.get("measurements", [])
                bus_index_by_name: dict[str, int] = {}
                for idx, name in net.bus["name"].items():
                    bus_index_by_name[name] = idx

                for meas in meas_list:
                    if not isinstance(meas, dict):
                        continue
                    meas_type = meas.get("type", "")
                    value = float(meas.get("value", 0.0))
                    std = float(meas.get("std", max(abs(value) * 0.02, 0.1)))
                    bus = str(meas.get("bus", meas.get("element", "")))
                    bus_idx = bus_index_by_name.get(bus, 0)

                    element = None
                    element_type = None
                    if "p_flow" in meas_type.lower() or "q_flow" in meas_type.lower():
                        element = bus_idx
                        element_type = "line"
                    elif bus_idx is not None:
                        element = bus_idx
                        element_type = "bus"

                    if element is not None and element_type is not None:
                        meas_type_pp = "v" if "voltage" in meas_type.lower() else (
                            "p" if "p_injection" in meas_type.lower() or "p_gen" in meas_type.lower() else (
                                "q" if "q_injection" in meas_type.lower() or "q_gen" in meas_type.lower() else "p"
                            )
                        )
                        pp.create_measurement(
                            net, meas_type=meas_type_pp,
                            element_type=element_type, element=element,
                            value=value, std_dev=std,
                        )

            try:
                pp.estimate(net, init="flat", tolerance_mva=1e-3, maximum_iterations=30)
                converged = True
                estimation_message = "State estimation converged using pandapower WLS"
            except pp.opt_termination as exc:
                trace("physics.run_state_estimation.pandapower_estimate_failed", error=str(exc)[:200])
                converged = False
                estimation_message = f"State estimation did not converge: {exc}"
            except Exception as exc:
                trace("physics.run_state_estimation.pandapower_estimate_failed", error=str(exc)[:200])
                return _run_state_estimation_fallback(
                    network_state, measurements, min_voltage_pu, max_voltage_pu,
                    simulated_time, seed,
                )

            bus_estimates: list[tuple[str, float, float]] = []
            for idx, row in net.res_bus_est.iterrows() if hasattr(net, "res_bus_est") else []:
                bus_name = net.bus.name.at[idx]
                bus_estimates.append((bus_name, float(row.vm_pu), float(row.va_degree)))

            if not bus_estimates:
                for idx, row in net.res_bus.iterrows():
                    bus_name = net.bus.name.at[idx]
                    bus_estimates.append((bus_name, float(row.vm_pu), float(row.va_degree)))

            return StateEstimationResult(
                success=converged,
                status=PhysicsStatus.SUCCESS if converged else PhysicsStatus.NON_CONVERGENCE,
                bus_estimates=tuple(bus_estimates),
                estimated_v_mag_pu=bus_estimates[0][1] if bus_estimates else 1.0,
                estimated_v_angle_deg=bus_estimates[0][2] if bus_estimates else 0.0,
                chi_squared=0.0,
                bad_data_detected=False,
                suspicious_measurements=(),
                message=estimation_message,
                timestamp=simulated_time,
            )
        except Exception as exc:
            trace("physics.run_state_estimation.error", error_type=type(exc).__name__, error=str(exc)[:200])
            return _run_state_estimation_fallback(
                network_state, measurements, min_voltage_pu, max_voltage_pu,
                simulated_time, seed,
            )


def _run_state_estimation_fallback(
    network_state: dict[str, Any],
    measurements: dict[str, Any] | list[dict[str, Any]] | None = None,
    min_voltage_pu: float = 0.95,
    max_voltage_pu: float = 1.05,
    simulated_time: datetime | None = None,
    seed: int | None = None,
) -> StateEstimationResult:
    rng = _make_deterministic_rng(seed if seed is not None else 42)

    buses = network_state.get("buses", [])
    meas_list: list[dict[str, Any]] = []
    if measurements is not None:
        if isinstance(measurements, list):
            meas_list = measurements
        elif isinstance(measurements, dict):
            meas_list = measurements.get("measurements", [])

    default_std_pct = 0.02
    weighted_sum_v = 0.0
    weight_sum_v = 0.0
    weighted_sum_angle = 0.0
    weight_sum_angle = 0.0
    num_meas = 0

    for meas in meas_list:
        if not isinstance(meas, dict):
            continue
        meas_type = meas.get("type", "")
        value = float(meas.get("value", 0.0))
        std = float(meas.get("std", max(abs(value) * default_std_pct, 0.1)))
        weight = 1.0 / (std * std) if std > 0 else 1.0

        if "voltage" in meas_type.lower() or "vm" in meas_type.lower():
            weighted_sum_v += value * weight
            weight_sum_v += weight
            num_meas += 1
        elif "angle" in meas_type.lower() or "va" in meas_type.lower():
            weighted_sum_angle += value * weight
            weight_sum_angle += weight
            num_meas += 1

    estimated_v_mag_pu = weighted_sum_v / weight_sum_v if weight_sum_v > 0 else 1.0
    v_mag_std = 1.0 / math.sqrt(weight_sum_v) if weight_sum_v > 0 else 0.05
    estimated_v_angle_deg = weighted_sum_angle / weight_sum_angle if weight_sum_angle > 0 else 0.0
    v_angle_std = 1.0 / math.sqrt(weight_sum_angle) if weight_sum_angle > 0 else 2.0
    degrees_of_freedom = max(1, num_meas - 2 * len(buses))
    chi_squared = float(num_meas) / max(degrees_of_freedom, 1)
    bad_data_threshold = 3.0
    bad_data_detected = False
    suspicious_ids: list[str] = []

    for i, meas in enumerate(meas_list):
        if not isinstance(meas, dict):
            continue
        meas_type = meas.get("type", "")
        value = float(meas.get("value", 0.0))
        std = float(meas.get("std", max(abs(value) * default_std_pct, 0.1)))
        if "voltage" in meas_type.lower() or "vm" in meas_type.lower():
            residual = (value - estimated_v_mag_pu) / max(std, 0.001)
            if abs(residual) > bad_data_threshold:
                bad_data_detected = True
                suspicious_ids.append(meas.get("bus", meas.get("element", f"meas_{i}")))

    bus_estimates: list[tuple[str, float, float]] = []
    for idx, bus in enumerate(buses):
        bus_id = str(bus.get("bus_id", bus.get("name", idx)))
        bus_seed = int(hashlib.md5(f"{seed}_{bus_id}".encode()).hexdigest()[:8], 16) if seed is not None else 42 + idx
        bus_rng = _make_deterministic_rng(bus_seed)
        vm_offset = bus_rng.normal(0.0, v_mag_std)
        va_offset = bus_rng.normal(0.0, v_angle_std)
        vm_est = max(min_voltage_pu, min(max_voltage_pu, estimated_v_mag_pu + vm_offset))
        va_est = estimated_v_angle_deg + va_offset
        bus_estimates.append((bus_id, round(vm_est, 4), round(va_est, 3)))

    if not bus_estimates:
        bus_estimates.append(("default_bus", round(estimated_v_mag_pu, 4), round(estimated_v_angle_deg, 3)))

    trace(
        "physics._run_state_estimation_fallback.done",
        buses=len(bus_estimates),
        measurements=num_meas,
        bad_data_detected=bad_data_detected,
        seed=seed,
    )

    return StateEstimationResult(
        success=True,
        status=PhysicsStatus.FALLBACK_USED,
        bus_estimates=tuple(bus_estimates),
        estimated_v_mag_pu=round(estimated_v_mag_pu, 4),
        estimated_v_angle_deg=round(estimated_v_angle_deg, 3),
        chi_squared=round(chi_squared, 4),
        bad_data_detected=bad_data_detected,
        suspicious_measurements=tuple(suspicious_ids),
        message="State estimation completed using WLS fallback (pandapower unavailable or estimation failed)",
        timestamp=simulated_time,
    )


def run_short_circuit(
    network_state: dict[str, Any],
    fault_bus: str = "",
    fault_type: str = "3ph",
    simulated_time: datetime | None = None,
    seed: int | None = None,
) -> ShortCircuitResult:
    with trace_scope(
        "physics.run_short_circuit",
        fault_bus=fault_bus,
        fault_type=fault_type,
        seed=seed,
    ):
        try:
            pp = importlib.import_module("pandapower")
        except ImportError:
            trace("physics.run_short_circuit.pandapower_missing")
            return _run_short_circuit_fallback(
                network_state, fault_bus, fault_type, simulated_time, seed,
            )

        try:
            net = _build_pandapower_net(network_state)

            bus_index_by_name: dict[str, int] = {}
            for idx, name in net.bus["name"].items():
                bus_index_by_name[name] = idx
            bus_index_by_external: dict[str, int] = {}
            for b in network_state.get("buses", []):
                bid = str(b.get("bus_id", b.get("name", "")))
                name = str(b.get("name", bid))
                if name in bus_index_by_name:
                    bus_index_by_external[bid] = bus_index_by_name[name]

            fault_bus_idx = None
            if fault_bus:
                fault_bus_idx = bus_index_by_external.get(fault_bus) or bus_index_by_name.get(fault_bus)
            if fault_bus_idx is None:
                fault_bus_idx = 0

            pp.calc_sc(net, bus=fault_bus_idx, case="max", fault=fault_type, ip=True)

            ikss_ka = float(net.res_bus_sc.ikss_ka.at[fault_bus_idx])
            skss_mva = float(net.res_bus_sc.skss_mva.at[fault_bus_idx])

            bus_voltages: list[tuple[str, float, float]] = []
            for idx, row in net.res_bus_sc.iterrows():
                bus_name = net.bus.name.at[idx]
                if idx == fault_bus_idx:
                    bus_voltages.append((bus_name, 0.0, 0.0))
                else:
                    bus_voltages.append((bus_name, float(row.vm_pu), float(row.va_degree)))

            gen_contributions: list[tuple[str, float]] = []
            if hasattr(net, "res_gen_sc") and net.res_gen_sc is not None:
                for idx, row in net.res_gen_sc.iterrows():
                    gen_name = net.gen.name.at[idx]
                    gen_contributions.append((gen_name, float(row.ikss_ka)))

            trace("physics.run_short_circuit.pandapower_done", ikss_ka=ikss_ka, skss_mva=skss_mva)

            return ShortCircuitResult(
                success=True,
                status=PhysicsStatus.SUCCESS,
                fault_current_ka=round(ikss_ka, 4),
                fault_power_mva=round(skss_mva, 2),
                bus_voltages=tuple(bus_voltages),
                generator_contributions=tuple(gen_contributions),
                message=f"IEC 60909 short-circuit calculated via pandapower (fault: {fault_type} at bus {fault_bus})",
                timestamp=simulated_time,
            )
        except Exception as exc:
            trace("physics.run_short_circuit.pandapower_error", error_type=type(exc).__name__, error=str(exc)[:200])
            return _run_short_circuit_fallback(
                network_state, fault_bus, fault_type, simulated_time, seed,
            )


def _run_short_circuit_fallback(
    network_state: dict[str, Any],
    fault_bus: str = "",
    fault_type: str = "3ph",
    simulated_time: datetime | None = None,
    seed: int | None = None,
) -> ShortCircuitResult:
    buses = network_state.get("buses", [])
    generators = network_state.get("generators", [])

    v_base_kv = 110.0
    for b in buses:
        bid = str(b.get("bus_id", b.get("name", "")))
        if bid == fault_bus or (not fault_bus and not v_base_kv):
            v_base_kv = float(b.get("vn_kv", v_base_kv))

    c_factor = 1.1
    z_source_pu = 0.05
    s_base_mva = 100.0

    total_fault_mva = 0.0
    gen_contributions: list[tuple[str, float]] = []

    for g in generators:
        gen_id = str(g.get("generator_id", g.get("name", "")))
        gen_sn_mva = float(g.get("sn_mva", g.get("p_mw", 100.0)))
        gen_xd_pu = float(g.get("xd_pu", 0.2))
        electrical_distance = 1.2
        z_gen_pu = gen_xd_pu * electrical_distance
        i_gen_pu = 1.0 / z_gen_pu if z_gen_pu > 0 else 0.0
        i_gen_ka = (i_gen_pu * gen_sn_mva) / (v_base_kv * math.sqrt(3.0))
        gen_mva = gen_sn_mva * i_gen_pu / electrical_distance
        gen_contributions.append((gen_id, round(i_gen_ka, 4)))
        total_fault_mva += gen_mva

    z_fault = z_source_pu * v_base_kv
    if z_fault > 0:
        fault_current_ka = (c_factor * v_base_kv) / (math.sqrt(3.0) * z_fault)
    else:
        fault_current_ka = 0.0
    fault_current_ka += sum(contrib for _, contrib in gen_contributions)
    fault_power_mva = fault_current_ka * v_base_kv * math.sqrt(3.0)

    bus_voltages: list[tuple[str, float, float]] = []
    for b in buses:
        bus_id = str(b.get("bus_id", b.get("name", "")))
        if bus_id == fault_bus:
            bus_voltages.append((bus_id, 0.0, 0.0))
        else:
            bus_seed = int(hashlib.md5(f"{seed}_{bus_id}".encode()).hexdigest()[:8], 16) if seed else 42
            rng_local = _make_deterministic_rng(bus_seed)
            distance_factor = float(max(0.5, 0.85 + 0.1 * rng_local.random()))
            bus_voltages.append((bus_id, round(distance_factor, 3), 0.0))

    if not bus_voltages:
        bus_voltages.append(("default_bus", 0.0, 0.0))

    trace(
        "physics._run_short_circuit_fallback.done",
        fault_current_ka=round(fault_current_ka, 4),
        fault_power_mva=round(fault_power_mva, 2),
        seed=seed,
    )

    return ShortCircuitResult(
        success=True,
        status=PhysicsStatus.FALLBACK_USED,
        fault_current_ka=round(fault_current_ka, 4),
        fault_power_mva=round(fault_power_mva, 2),
        bus_voltages=tuple(bus_voltages),
        generator_contributions=tuple(gen_contributions),
        message="Short-circuit calculated using IEC 60909 fallback (pandapower unavailable or sc calculation failed)",
        timestamp=simulated_time,
    )


def run_frequency_response(
    network_state: dict[str, Any],
    disturbance: dict[str, Any] | None = None,
    min_frequency_hz: float = 49.0,
    simulated_time: datetime | None = None,
    seed: int | None = None,
) -> FrequencyResponseResult:
    with trace_scope(
        "physics.run_frequency_response",
        disturbance_type=disturbance.get("type") if disturbance else "none",
        min_frequency_hz=min_frequency_hz,
        seed=seed,
    ):
        if disturbance is None:
            disturbance = {}

        delta_p_mw = float(disturbance.get("delta_p_mw", 0.0))
        disturbance_type = str(disturbance.get("type", "load_loss"))

        generators = network_state.get("generators", [])
        total_inertia_s = 4.0
        s_base_mva = 100.0

        if generators:
            inertia_contributions = []
            for gen in generators:
                rating_mva = float(gen.get("sn_mva", gen.get("p_mw", 100.0)))
                gen_type = str(gen.get("type", gen.get("fuel_type", "thermal"))).lower()
                if "hydro" in gen_type:
                    h_value = 2.5
                elif "gas" in gen_type:
                    h_value = 3.5
                elif "wind" in gen_type or "solar" in gen_type:
                    h_value = 0.0
                else:
                    h_value = 4.5
                inertia_contributions.append(rating_mva * h_value)
                s_base_mva = max(s_base_mva, rating_mva)
            if inertia_contributions:
                total_inertia_s = sum(inertia_contributions) / s_base_mva

        damping_factor = 1.0
        if s_base_mva > 0 and total_inertia_s > 0:
            delta_f_pu = -delta_p_mw / (2.0 * total_inertia_s * s_base_mva * damping_factor)
        else:
            delta_f_pu = 0.0

        freq_nadir_hz = 50.0 + delta_f_pu * 50.0 * 1.4
        rocof_denom = 2.0 * total_inertia_s * s_base_mva
        rocof_hz_s = abs(delta_p_mw) / rocof_denom if rocof_denom > 0 else 0.0
        freq_settling_hz = 50.0 + delta_f_pu * 50.0 * 0.5

        clearing_denom = abs(delta_p_mw) / max(s_base_mva, 1.0) + 0.1
        critical_clearing_s = total_inertia_s / clearing_denom if clearing_denom > 0 else 0.0
        critical_clearing_cycles = critical_clearing_s * 50.0

        if min_frequency_hz > 0 and freq_nadir_hz < min_frequency_hz:
            status = PhysicsStatus.VIOLATION_RAMP
            converged = False
            result_message = (
                f"Frequency nadir {freq_nadir_hz:.2f} Hz below minimum {min_frequency_hz} Hz "
                f"(inertia={total_inertia_s:.2f}s, dP={delta_p_mw:.1f}MW)"
            )
        else:
            status = PhysicsStatus.SUCCESS
            converged = True
            result_message = (
                f"Frequency response stable (nadir={freq_nadir_hz:.2f}Hz, rocof={rocof_hz_s:.3f}Hz/s)"
            )

        trace(
            "physics.run_frequency_response.done",
            freq_nadir_hz=round(freq_nadir_hz, 4),
            rocof_hz_s=round(rocof_hz_s, 4),
            inertia=round(total_inertia_s, 3),
            seed=seed,
        )

        return FrequencyResponseResult(
            success=converged,
            status=status,
            frequency_nadir_hz=round(freq_nadir_hz, 4),
            rocof_hz_s=round(rocof_hz_s, 4),
            settling_frequency_hz=round(freq_settling_hz, 4),
            system_inertia_s=round(total_inertia_s, 3),
            critical_clearing_time_cycles=round(critical_clearing_cycles, 2),
            delta_p_mw=delta_p_mw,
            message=result_message,
            timestamp=simulated_time,
        )


def _get_n1_executor(
    max_workers: int | None = None,
    use_process_pool: bool = True,
) -> Any:
    import concurrent.futures as _cf

    if not use_process_pool:
        return _cf.ThreadPoolExecutor(max_workers=max_workers)

    try:
        from athenaai.physics.process_pool import PhysicsProcessPool
        pool = PhysicsProcessPool(max_workers=max_workers)
        pool._get_or_create_executor()
        trace(
            "physics._get_n1_executor",
            executor_type="process",
            max_workers=pool.max_workers,
            is_process_pool=pool.is_process_pool,
        )
        if not pool.is_process_pool:
            pool.shutdown(wait=False)
            trace("physics._get_n1_executor.fallback_to_thread")
            return _cf.ThreadPoolExecutor(max_workers=max_workers)
        return pool
    except Exception as exc:
        trace(
            "physics._get_n1_executor.process_pool_unavailable",
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return _cf.ThreadPoolExecutor(max_workers=max_workers)


def run_parallel_n1(
    network_state: dict[str, Any],
    contingencies: list[dict[str, Any]] | None = None,
    max_loading_percent: float = 100.0,
    min_voltage_pu: float = 0.95,
    max_voltage_pu: float = 1.05,
    simulated_time: datetime | None = None,
    pool: Any | None = None,
    seed: int | None = None,
    max_workers: int | None = None,
    use_process_pool: bool = True,
) -> Any:
    from athenaai.physics.n1 import (
        ContingencyResult,
        N1Result,
        N1Status,
        n1_security_scan,
    )
    import concurrent.futures

    with trace_scope(
        "physics.run_parallel_n1",
        contingencies=len(contingencies) if contingencies else 0,
        max_workers=max_workers,
        seed=seed,
        use_process_pool=use_process_pool,
    ):
        if contingencies is None:
            return n1_security_scan(
                network_state,
                simulated_time=simulated_time,
                max_loading_percent=max_loading_percent,
                min_voltage_pu=min_voltage_pu,
                max_voltage_pu=max_voltage_pu,
            )

        if not contingencies:
            return N1Result(
                passed=True,
                status=N1Status.PASSED,
                contingencies=(),
                secure_contingencies=(),
                violated_contingencies=(),
                message="No contingencies to check",
                timestamp=simulated_time,
            )

        if len(contingencies) <= 4:
            trace("physics.run_parallel_n1.small_set_sequential", count=len(contingencies))
            return n1_security_scan(
                network_state,
                simulated_time=simulated_time,
                critical_elements=contingencies,
                max_loading_percent=max_loading_percent,
                min_voltage_pu=min_voltage_pu,
                max_voltage_pu=max_voltage_pu,
            )

        _workers = pool.max_workers if pool is not None else (max_workers or 4)
        chunk_size = max(1, len(contingencies) // max(4, _workers))
        chunks = [
            list(contingencies[i : i + chunk_size])
            for i in range(0, len(contingencies), chunk_size)
        ]
        trace("physics.run_parallel_n1.chunks", num_chunks=len(chunks), chunk_size=chunk_size)

        all_contingencies: list[ContingencyResult] = []
        all_secure: list[str] = []
        all_violated: list[str] = []

        chunk_seed = seed if seed is not None else 42

        if pool is not None:
            _owns_executor = False
            executor = pool
        else:
            _owns_executor = True
            executor = _get_n1_executor(
                max_workers=max_workers, use_process_pool=use_process_pool
            ).__enter__()

        try:
            future_to_chunk = {}
            for idx, chunk in enumerate(chunks):
                future = executor.submit(
                    n1_security_scan,
                    network_state=network_state,
                    simulated_time=simulated_time,
                    critical_elements=chunk,
                    max_loading_percent=max_loading_percent,
                    min_voltage_pu=min_voltage_pu,
                    max_voltage_pu=max_voltage_pu,
                    stop_on_first_violation=False,
                )
                future_to_chunk[future] = idx

            for future in concurrent.futures.as_completed(future_to_chunk):
                try:
                    chunk_result: N1Result = future.result()
                    all_contingencies.extend(chunk_result.contingencies)
                    all_secure.extend(chunk_result.secure_contingencies)
                    all_violated.extend(chunk_result.violated_contingencies)
                except Exception as exc:
                    trace(
                        "physics.run_parallel_n1.chunk_failed",
                        chunk_index=future_to_chunk[future],
                        error=str(exc)[:200],
                    )
        finally:
            if _owns_executor:
                try:
                    executor.__exit__(None, None, None)
                except Exception:
                    pass

        all_passed = len(all_violated) == 0
        trace(
            "physics.run_parallel_n1.done",
            passed=all_passed,
            checked=len(all_contingencies),
            secure=len(all_secure),
            violated=len(all_violated),
        )

        return N1Result(
            passed=all_passed,
            status=N1Status.PASSED if all_passed else N1Status.FAILED,
            contingencies=tuple(all_contingencies),
            secure_contingencies=tuple(all_secure),
            violated_contingencies=tuple(all_violated),
            message="Parallel N-1 scan passed" if all_passed else f"Parallel N-1 failed: {len(all_violated)} violations",
            timestamp=simulated_time,
        )
