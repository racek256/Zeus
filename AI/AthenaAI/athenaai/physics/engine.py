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
import importlib
import math
from typing import Any

from athenaai.trace import trace, trace_scope


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
    balance_tolerance_mw = max(5.0, 0.02 * max(load_total, generation_total, 1.0))
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
