"""N-1 security analysis engine.

This module performs deterministic N-1 contingency analysis: for each critical
element (generator, line, transformer), remove it from the network, solve load
flow, and check for violations. No LLM logic or heuristics inside this layer.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import importlib
from typing import Any

from athenaai.trace import trace, trace_scope

try:
    from athenaai.physics.cache import ResultCache as _ResultCache
except ImportError:
    _ResultCache = None  # type: ignore[assignment]


class N1Status(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ELEMENT_NOT_FOUND = "element_not_found"
    LOAD_FLOW_FAILED = "load_flow_failed"
    ISLANDING = "islanding"


@dataclass(frozen=True)
class ContingencyResult:
    contingency_id: str
    contingency_type: str
    element_id: str
    status: N1Status
    violations: tuple[str, ...] = field(default_factory=tuple)
    message: str = ""


@dataclass(frozen=True)
class N1Result:
    passed: bool
    status: N1Status
    contingencies: tuple[ContingencyResult, ...]
    secure_contingencies: tuple[str, ...]
    violated_contingencies: tuple[str, ...]
    message: str
    timestamp: datetime | None = None


def _build_network_copy(
    network_state: dict[str, Any],
    remove_element: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import copy
    ns = copy.deepcopy(network_state)

    if remove_element is None:
        return ns

    etype = remove_element.get("type")
    eid = remove_element.get("id")

    if etype == "generator":
        ns["generators"] = [
            g for g in ns.get("generators", []) if g.get("generator_id") != eid
        ]
    elif etype == "branch":
        ns["branches"] = [
            b for b in ns.get("branches", []) if b.get("branch_id") != eid
        ]
    elif etype == "bus":
        ns["buses"] = [b for b in ns.get("buses", []) if b.get("bus_id") != eid]
        ns["generators"] = [
            g for g in ns.get("generators", []) if g.get("bus") != eid
        ]
        ns["loads"] = [l for l in ns.get("loads", []) if l.get("bus") != eid]
        ns["branches"] = [
            b
            for b in ns.get("branches", [])
            if b.get("from_bus") != eid and b.get("to_bus") != eid
        ]

    return ns


def _load_flow_result_from_pandapower_net(
    net: Any,
    simulated_time: datetime | None,
) -> Any:
    from athenaai.physics.engine import LoadFlowResult, PhysicsStatus

    bus_voltages: list[tuple[str, float, float]] = []
    for idx, row in net.res_bus.iterrows():
        bus_name = net.bus.name.at[idx]
        bus_voltages.append((bus_name, float(row.vm_pu), float(row.va_degree)))

    branch_flows: list[tuple[str, str, str, float]] = []
    for idx, row in net.res_line.iterrows():
        line_name = net.line.name.at[idx]
        from_bus = net.line.from_bus.at[idx]
        to_bus = net.line.to_bus.at[idx]
        branch_flows.append((line_name, str(from_bus), str(to_bus), float(row.loading_percent)))

    for idx, row in net.res_trafo.iterrows():
        trafo_name = net.trafo.name.at[idx]
        hv_bus = net.trafo.hv_bus.at[idx]
        lv_bus = net.trafo.lv_bus.at[idx]
        branch_flows.append((trafo_name, str(hv_bus), str(lv_bus), float(row.loading_percent)))

    generations: list[tuple[str, float]] = []
    for idx, row in net.res_gen.iterrows():
        gen_name = net.gen.name.at[idx]
        generations.append((gen_name, float(row.p_mw)))

    return LoadFlowResult(
        converged=True,
        status=PhysicsStatus.SUCCESS,
        bus_voltages=tuple(bus_voltages),
        branch_flows=tuple(branch_flows),
        generations=tuple(generations),
        message="AC load flow converged",
        timestamp=simulated_time,
    )


def _find_named_index(table: Any, name: str) -> Any | None:
    matches = table.index[table["name"] == name]
    if len(matches) == 0:
        return None
    return matches[0]


def n1_security_scan(
    network_state: dict[str, Any],
    simulated_time: datetime | None = None,
    critical_elements: list[dict[str, Any]] | None = None,
    max_loading_percent: float = 100.0,
    min_voltage_pu: float = 0.95,
    max_voltage_pu: float = 1.05,
    stop_on_first_violation: bool = False,
) -> N1Result:
    from athenaai.physics.engine import LoadFlowResult, PhysicsStatus, _build_pandapower_net, run_ac_load_flow

    with trace_scope(
        "n1_security_scan",
        simulated_time=simulated_time.isoformat() if simulated_time is not None else None,
        stop_on_first_violation=stop_on_first_violation,
    ):
        if critical_elements is None:
            critical_elements = []

            for b in network_state.get("branches", []):
                critical_elements.append(
                    {"type": "branch", "id": b.get("branch_id"), "data": b}
                )

            for g in network_state.get("generators", []):
                critical_elements.append(
                    {"type": "generator", "id": g.get("generator_id"), "data": g}
                )

        trace("n1_security_scan.contingencies_built", count=len(critical_elements))

        contingencies: list[ContingencyResult] = []
        violated_ids: list[str] = []
        secure_ids: list[str] = []

        pp = None
        reusable_net = None
        try:
            pp = importlib.import_module("pandapower")
            reusable_net = _build_pandapower_net(network_state)
            trace(
                "n1_security_scan.reusable_pandapower_net.ready",
                buses=len(reusable_net.bus),
                lines=len(reusable_net.line),
                transformers=len(reusable_net.trafo),
                generators=len(reusable_net.gen),
                loads=len(reusable_net.load),
            )
        except ImportError:
            trace("n1_security_scan.reusable_pandapower_net.unavailable")
        except Exception as exc:
            trace(
                "n1_security_scan.reusable_pandapower_net.build_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:240],
            )
            pp = None
            reusable_net = None

        for index, elem in enumerate(critical_elements, start=1):
            eid = str(elem.get("id", "unknown"))
            etype = str(elem.get("type", "unknown"))

            contingency_id = f"{etype}_{eid}"
            trace(
                "n1_security_scan.contingency.start",
                index=index,
                total=len(critical_elements),
                contingency_id=contingency_id,
                contingency_type=etype,
                element_id=eid,
            )

            lf_result: LoadFlowResult | None = None
            if pp is not None and reusable_net is not None and etype in {"generator", "branch"}:
                table = None
                element_index = None
                if etype == "generator":
                    table = reusable_net.gen
                    element_index = _find_named_index(table, eid)
                elif etype == "branch":
                    table = reusable_net.line
                    element_index = _find_named_index(table, eid)
                    if element_index is None:
                        table = reusable_net.trafo
                        element_index = _find_named_index(table, eid)

                if table is None or element_index is None:
                    trace("n1_security_scan.contingency.element_not_found", contingency_id=contingency_id)
                    contingencies.append(
                        ContingencyResult(
                            contingency_id=contingency_id,
                            contingency_type=etype,
                            element_id=eid,
                            status=N1Status.ELEMENT_NOT_FOUND,
                            violations=("ELEMENT_NOT_FOUND",),
                            message="Contingency element not found in pandapower net",
                        )
                    )
                    violated_ids.append(contingency_id)
                    if stop_on_first_violation:
                        break
                    continue

                original_in_service = bool(table.at[element_index, "in_service"])
                try:
                    table.at[element_index, "in_service"] = False
                    with trace_scope(
                        "n1_security_scan.contingency.runpp_reused_net",
                        contingency_id=contingency_id,
                        table=getattr(table, "__class__", type(table)).__name__,
                    ):
                        pp.runpp(reusable_net, calculate_voltage_angles=True, numba=False)
                    lf_result = _load_flow_result_from_pandapower_net(reusable_net, simulated_time)
                except pp.LoadflowNotConverged:
                    trace("n1_security_scan.contingency.reused_net_non_convergence", contingency_id=contingency_id)
                    lf_result = LoadFlowResult(
                        converged=False,
                        status=PhysicsStatus.NON_CONVERGENCE,
                        bus_voltages=(),
                        branch_flows=(),
                        generations=(),
                        message="AC load flow did not converge after contingency",
                        timestamp=simulated_time,
                    )
                except Exception as exc:
                    trace(
                        "n1_security_scan.contingency.reused_net_error",
                        contingency_id=contingency_id,
                        error_type=type(exc).__name__,
                        error=str(exc)[:240],
                    )
                    lf_result = LoadFlowResult(
                        converged=False,
                        status=PhysicsStatus.NON_CONVERGENCE,
                        bus_voltages=(),
                        branch_flows=(),
                        generations=(),
                        message=f"AC load flow error after contingency: {exc}",
                        timestamp=simulated_time,
                    )
                finally:
                    table.at[element_index, "in_service"] = original_in_service

            if lf_result is None:
                modified_state = _build_network_copy(network_state, elem)
                with trace_scope("n1_security_scan.contingency.run_ac_load_flow", contingency_id=contingency_id):
                    lf_result = run_ac_load_flow(modified_state, simulated_time)

            if not lf_result.converged:
                trace(
                    "n1_security_scan.contingency.failed_non_convergence",
                    contingency_id=contingency_id,
                    status=getattr(lf_result.status, "value", str(lf_result.status)),
                )
                contingencies.append(
                    ContingencyResult(
                        contingency_id=contingency_id,
                        contingency_type=etype,
                        element_id=eid,
                        status=N1Status.LOAD_FLOW_FAILED,
                        violations=("NON_CONVERGENCE",),
                        message="Load flow failed after contingency",
                    )
                )
                violated_ids.append(contingency_id)
                if stop_on_first_violation:
                    break
                continue

            violations = lf_result.violations(max_loading_percent, min_voltage_pu, max_voltage_pu)

            if violations:
                trace(
                    "n1_security_scan.contingency.failed_violations",
                    contingency_id=contingency_id,
                    violations=len(violations),
                )
                contingencies.append(
                    ContingencyResult(
                        contingency_id=contingency_id,
                        contingency_type=etype,
                        element_id=eid,
                        status=N1Status.FAILED,
                        violations=violations,
                        message=f"N-1 violated: {', '.join(violations)}",
                    )
                )
                violated_ids.append(contingency_id)
                if stop_on_first_violation:
                    break
            else:
                trace("n1_security_scan.contingency.passed", contingency_id=contingency_id)
                contingencies.append(
                    ContingencyResult(
                        contingency_id=contingency_id,
                        contingency_type=etype,
                        element_id=eid,
                        status=N1Status.PASSED,
                        violations=(),
                        message="Contingency passed",
                    )
                )
                secure_ids.append(contingency_id)

        all_passed = len(violated_ids) == 0
        trace(
            "n1_security_scan.done",
            passed=all_passed,
            checked=len(contingencies),
            secure=len(secure_ids),
            violated=len(violated_ids),
        )

        return N1Result(
            passed=all_passed,
            status=N1Status.PASSED if all_passed else N1Status.FAILED,
            contingencies=tuple(contingencies),
            secure_contingencies=tuple(secure_ids),
            violated_contingencies=tuple(violated_ids),
            message="N-1 scan passed" if all_passed else f"N-1 failed: {len(violated_ids)} violations",
            timestamp=simulated_time,
        )


def _get_n1_parallel_executor(
    max_workers: int | None = None,
    use_process_pool: bool = True,
) -> tuple[Any, bool]:
    if not use_process_pool:
        trace("n1._get_n1_parallel_executor.thread_pool", max_workers=max_workers)
        return concurrent.futures.ThreadPoolExecutor(max_workers=max_workers), True

    try:
        from athenaai.physics.process_pool import PhysicsProcessPool
        pool = PhysicsProcessPool(max_workers=max_workers)
        pool._get_or_create_executor()
        trace(
            "n1._get_n1_parallel_executor.process_pool",
            max_workers=pool.max_workers,
            is_process_pool=pool.is_process_pool,
        )
        if not pool.is_process_pool:
            pool.shutdown(wait=False)
            trace("n1._get_n1_parallel_executor.fallback_to_thread")
            return concurrent.futures.ThreadPoolExecutor(max_workers=max_workers), True
        return pool, True
    except Exception as exc:
        trace(
            "n1._get_n1_parallel_executor.process_pool_unavailable",
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return concurrent.futures.ThreadPoolExecutor(max_workers=max_workers), True


def _shutdown_executor_safe(executor: Any) -> None:
    try:
        shutdown = getattr(executor, "shutdown", None)
        if shutdown is not None:
            shutdown(wait=False)
        else:
            executor.__exit__(None, None, None)
    except Exception:
        pass


def n1_parallel_scan(
    network_state: dict[str, Any],
    simulated_time: datetime | None = None,
    critical_elements: list[dict[str, Any]] | None = None,
    max_loading_percent: float = 100.0,
    min_voltage_pu: float = 0.95,
    max_voltage_pu: float = 1.05,
    stop_on_first_violation: bool = False,
    seed: int | None = None,
    max_workers: int | None = None,
    pool: Any | None = None,
    use_cache: bool = False,
    cache_ttl: float = 300.0,
    use_process_pool: bool = True,
) -> N1Result:
    with trace_scope(
        "n1_parallel_scan",
        simulated_time=simulated_time.isoformat() if simulated_time is not None else None,
        contingencies=len(critical_elements) if critical_elements else 0,
        max_workers=max_workers,
        seed=seed,
        use_cache=use_cache,
        use_process_pool=use_process_pool,
    ):
        if use_cache and _ResultCache is not None:
            cache = _ResultCache()
            cache_key = cache.make_key(
                network_state,
                operation="n1_scan",
                max_loading=max_loading_percent,
                min_v=min_voltage_pu,
                max_v=max_voltage_pu,
                seed=seed,
            )
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                trace("n1_parallel_scan.cache_hit")
                return N1Result(
                    passed=cached_result.get("passed", True),
                    status=N1Status(cached_result.get("status", "passed")),
                    contingencies=tuple(),
                    secure_contingencies=tuple(cached_result.get("secure_contingencies", [])),
                    violated_contingencies=tuple(cached_result.get("violated_contingencies", [])),
                    message=cached_result.get("message", "Cached N-1 result"),
                    timestamp=simulated_time,
                )

        if critical_elements is None:
            critical_elements = []
            for b in network_state.get("branches", []):
                critical_elements.append({"type": "branch", "id": b.get("branch_id"), "data": b})
            for g in network_state.get("generators", []):
                critical_elements.append({"type": "generator", "id": g.get("generator_id"), "data": g})

        if not critical_elements:
            trace("n1_parallel_scan.no_elements")
            return N1Result(
                passed=True,
                status=N1Status.PASSED,
                contingencies=(),
                secure_contingencies=(),
                violated_contingencies=(),
                message="No critical elements to scan",
                timestamp=simulated_time,
            )

        if len(critical_elements) <= 4:
            trace("n1_parallel_scan.small_set_sequential", count=len(critical_elements))
            return n1_security_scan(
                network_state,
                simulated_time=simulated_time,
                critical_elements=critical_elements,
                max_loading_percent=max_loading_percent,
                min_voltage_pu=min_voltage_pu,
                max_voltage_pu=max_voltage_pu,
                stop_on_first_violation=stop_on_first_violation,
            )

        if pool is not None:
            num_workers = max_workers or pool.max_workers
            executor = pool
            executor_owns = False
        else:
            num_workers = max_workers or min(8, len(critical_elements) // 2 + 1)
            executor, executor_owns = _get_n1_parallel_executor(
                max_workers=num_workers,
                use_process_pool=use_process_pool,
            )
        chunk_size = max(1, len(critical_elements) // num_workers)
        chunks = [
            list(critical_elements[i : i + chunk_size])
            for i in range(0, len(critical_elements), chunk_size)
        ]
        trace("n1_parallel_scan.chunks", num_chunks=len(chunks), chunk_size=chunk_size)

        all_contingencies: list[Any] = []
        all_secure: list[str] = []
        all_violated: list[str] = []

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
                    stop_on_first_violation=stop_on_first_violation,
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
                        "n1_parallel_scan.chunk_failed",
                        chunk_index=future_to_chunk[future],
                        error=str(exc)[:200],
                    )
        finally:
            if executor_owns:
                _shutdown_executor_safe(executor)

        all_passed = len(all_violated) == 0

        if use_cache and _ResultCache is not None:
            cache = _ResultCache()
            cache_key = cache.make_key(
                network_state,
                operation="n1_scan",
                max_loading=max_loading_percent,
                min_v=min_voltage_pu,
                max_v=max_voltage_pu,
                seed=seed,
            )
            cache.put(
                cache_key,
                {
                    "passed": all_passed,
                    "status": "passed" if all_passed else "failed",
                    "secure_contingencies": all_secure,
                    "violated_contingencies": all_violated,
                    "message": "Cached parallel N-1 result",
                },
                ttl=cache_ttl,
            )
            trace("n1_parallel_scan.cache_stored")

        trace(
            "n1_parallel_scan.done",
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
