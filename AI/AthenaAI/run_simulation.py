"""run_simulation.py - main simulation controller for AthenaAI Phase 2.2.

This is the top-level simulation entry point. It:
1. Initializes state and loads datasets
2. Runs hour loop: step(hour) -> distribute observations -> collect agent outputs
   -> execute validated actions -> run physics -> score -> store logs
3. Increments clock only after agent completion
4. Stops on simulation failure
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from athenaai.agent_runtime import create_async_runtime, create_runtime
from athenaai.audit.logger import AuditLogger
from athenaai.audit.live_view import (
    AgentOutputFileLog,
    AgentLogTUI,
    AgentWorkLog,
    build_agent_work_logs,
    print_agent_output_only,
    print_agent_work_logs,
)
from athenaai.config import DATASET_ROOT
from athenaai.physics.n1 import n1_security_scan
from athenaai.schema import ActionBundle
from athenaai.simulator import GridSimulator
from athenaai.trace import is_trace_enabled, set_trace_enabled, trace, trace_scope


def build_model_overrides(args: Any) -> dict[str, str]:
    model_overrides: dict[str, str] = {}
    if args.model:
        model_overrides["all"] = args.model
    if args.coordinator_model:
        model_overrides["coordinator"] = args.coordinator_model
    if args.regional_model:
        model_overrides["regional"] = args.regional_model
    if args.oracle_model:
        model_overrides["oracle"] = args.oracle_model
    if args.bohemia_west_model:
        model_overrides["bohemia-west"] = args.bohemia_west_model
    if args.bohemia_east_model:
        model_overrides["bohemia-east"] = args.bohemia_east_model
    if args.moravia_model:
        model_overrides["moravia"] = args.moravia_model
    if args.silesia_model:
        model_overrides["silesia"] = args.silesia_model
    return model_overrides


def run_simulation(
    dataset_root: Path | None = None,
    start_hour: int = 0,
    end_hour: int = 24,
    stop_on_failure: bool = True,
    verbose: bool = True,
    model_overrides: Mapping[str, str] | None = None,
    verbose_agent_logs: bool = False,
    tui: bool = False,
    tui_lines: int = 30,
    allow_fallback_physics: bool = False,
    full_n1_scan: bool = False,
    trace_functions: bool = False,
    agent_output_only: bool = False,
    agent_output_log_path: Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    phase_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    set_trace_enabled(trace_functions or is_trace_enabled())
    trace(
        "run_simulation.start",
        dataset_root=str(dataset_root) if dataset_root is not None else None,
        start_hour=start_hour,
        end_hour=end_hour,
        full_n1_scan=full_n1_scan,
    )
    with trace_scope(
        "run_simulation.initialize",
        dataset_root=str(dataset_root) if dataset_root is not None else None,
        start_hour=start_hour,
        end_hour=end_hour,
        full_n1_scan=full_n1_scan,
    ):
        simulator = GridSimulator(
            dataset_root=dataset_root,
            start_hour=start_hour,
            allow_fallback_physics=allow_fallback_physics,
        )
        simulator.initialize()
        simulator.get_or_create_physics_pool()

    audit_logger = AuditLogger()
    if agent_output_log_path is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        agent_output_log_path = Path("logs") / f"agent-output-{run_id}.log"
    agent_output_log = AgentOutputFileLog(agent_output_log_path)
    runtime = create_runtime(
        simulator,
        audit_logger=audit_logger,
        model_overrides=model_overrides,
    )

    missing_hours = simulator.get_missing_gen_hours()
    if missing_hours:
        if verbose and not agent_output_only:
            print(f"Warning: {len(missing_hours)} missing generator actual hours detected: {sorted(missing_hours)[:10]}...")

    results: list[dict[str, Any]] = []
    failed_hours: list[int] = []
    agent_work_logs: list[AgentWorkLog] = []
    live_view = AgentLogTUI(max_lines=tui_lines) if tui and sys.stdout.isatty() else None
    total_planned_hours = end_hour - start_hour
    attempted_hours = 0

    try:
        for hour in range(start_hour, end_hour):
            trace("run_simulation.hour.begin", hour=hour)
            if hour in missing_hours:
                if verbose and not agent_output_only:
                    print(f"Skipping hour {hour} - missing generator actuals")
                continue
    
            if verbose and not agent_output_only:
                ts = datetime(2026, 1, 1, 0, 0, 0) + timedelta(hours=hour)
                print(f"Hour {hour} ({ts.strftime('%Y-%m-%d %H:%M')})...")
            attempted_hours += 1
    
            with trace_scope("run_simulation.simulator.step", hour=hour):
                obs = simulator.step(hour)
    
            audit_line_start = len(audit_logger.get_lines())
            with trace_scope("run_simulation.runtime.distribute_observation", hour=hour):
                observations = runtime.distribute_observation(obs)
            with trace_scope("run_simulation.runtime.collect_agent_outputs", hour=hour):
                responses = runtime.collect_agent_outputs(observations)
            hour_agent_logs = build_agent_work_logs(
                hour_index=hour,
                responses=responses,
                model_lookup={agent_id: runtime.get_agent_model(agent_id) for agent_id in responses},
            )
            agent_work_logs.extend(hour_agent_logs)
    
            if (verbose_agent_logs or tui) and live_view is None and not agent_output_only:
                print_agent_work_logs(hour_agent_logs)
    
            actions: list[ActionBundle] = []
            for agent_id, response in responses.items():
                if response.action and not response.action.is_empty():
                    actions.append(response.action)
    
            trace("run_simulation.actions", hour=hour, count=len(actions))
            with trace_scope("run_simulation.runtime.execute_validated_actions", hour=hour, actions=len(actions)):
                eval_results = runtime.execute_validated_actions(actions)
    
            if agent_output_only:
                print_agent_output_only(hour_agent_logs, audit_logger.get_lines()[audit_line_start:])
            agent_output_log.append(hour_agent_logs, audit_logger.get_lines()[audit_line_start:])
    
            step_failure = False
            for er in eval_results:
                if not er.get("accepted", False):
                    step_failure = True
                    break
    
                lf_result = er.get("load_flow_result")
                if lf_result:
                    if not lf_result.get("converged", False):
                        step_failure = True
                        break
                    if lf_result.get("violations"):
                        step_failure = True
                        break
    
            n1_result = None
            load_shedding_committed = any(action.load_shedding_flags for action in actions)
            skip_redundant_fail_fast_n1 = load_shedding_committed and not full_n1_scan
            if not step_failure and not skip_redundant_fail_fast_n1:
                trace("run_simulation.n1.start", hour=hour, full_scan=full_n1_scan)
                n1_result = n1_security_scan(
                    simulator.current_network_state,
                    simulated_time=obs.timestamp,
                    max_loading_percent=simulator.constraints.max_branch_loading_percent,
                    min_voltage_pu=simulator.constraints.min_voltage_pu,
                    max_voltage_pu=simulator.constraints.max_voltage_pu,
                    stop_on_first_violation=not full_n1_scan,
                )
    
                if not n1_result.passed:
                    step_failure = True
                trace(
                    "run_simulation.n1.done",
                    hour=hour,
                    passed=n1_result.passed,
                    contingencies=len(n1_result.contingencies),
                    violations=len(n1_result.violated_contingencies),
                )
            elif skip_redundant_fail_fast_n1:
                trace(
                    "run_simulation.n1.skip_redundant_fail_fast",
                    hour=hour,
                    load_shedding_actions=sum(1 for action in actions if action.load_shedding_flags),
                )
    
            if step_failure and hour not in failed_hours:
                failed_hours.append(hour)
    
            if live_view is not None:
                live_view.update(
                    hour_index=hour,
                    total_hours=total_planned_hours,
                    logs=hour_agent_logs,
                    audit_lines=audit_logger.get_lines(),
                    failed_hours=failed_hours,
                )
    
            results.append(
                {
                    "hour_index": hour,
                    "timestamp": obs.timestamp.isoformat(),
                    "observation": obs,
                    "agent_responses": responses,
                    "evaluation_results": eval_results,
                    "n1_passed": n1_result.passed if n1_result is not None else None,
                    "n1_violations": n1_result.violated_contingencies if n1_result is not None else (),
                    "step_failed": step_failure,
                }
            )
            if progress_callback:
                progress_callback(_frontend_hour_result(results[-1]))
    
            if step_failure and stop_on_failure:
                if verbose and not agent_output_only:
                    print(f"Simulation FAILED at hour {hour} - stopping")
                trace("run_simulation.hour.stop_on_failure", hour=hour)
                break

    finally:
        simulator.shutdown_physics_pool()
    successful_hours = len([r for r in results if not r.get("step_failed", False)])
    replay_coverage = successful_hours / max(1, attempted_hours) * 100

    trace(
        "run_simulation.done",
        total_hours=len(results),
        failed_hours=len(failed_hours),
        replay_coverage_percent=round(replay_coverage, 3),
    )
    return {
        "total_hours": len(results),
        "failed_hours": failed_hours,
        "replay_coverage_percent": replay_coverage,
        "results": results,
        "audit_logs": audit_logger.get_logs(),
        "agent_work_logs": agent_work_logs,
        "agent_output_log_path": str(agent_output_log.path),
        "missing_gen_hours": sorted(missing_hours),
    }


async def run_simulation_async(
    dataset_root: Path | None = None,
    start_hour: int = 0,
    end_hour: int = 24,
    stop_on_failure: bool = True,
    verbose: bool = True,
    model_overrides: Mapping[str, str] | None = None,
    verbose_agent_logs: bool = False,
    tui: bool = False,
    tui_lines: int = 30,
    allow_fallback_physics: bool = False,
    full_n1_scan: bool = False,
    trace_functions: bool = False,
    agent_output_only: bool = False,
    agent_output_log_path: Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    phase_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    set_trace_enabled(trace_functions or is_trace_enabled())
    trace(
        "run_simulation_async.start",
        dataset_root=str(dataset_root) if dataset_root is not None else None,
        start_hour=start_hour,
        end_hour=end_hour,
        full_n1_scan=full_n1_scan,
    )
    with trace_scope(
        "run_simulation_async.initialize",
        dataset_root=str(dataset_root) if dataset_root is not None else None,
        start_hour=start_hour,
        end_hour=end_hour,
        full_n1_scan=full_n1_scan,
    ):
        simulator = GridSimulator(
            dataset_root=dataset_root,
            start_hour=start_hour,
            allow_fallback_physics=allow_fallback_physics,
        )
        simulator.initialize()
        simulator.get_or_create_physics_pool()

    audit_logger = AuditLogger()
    if agent_output_log_path is None:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        agent_output_log_path = Path("logs") / f"agent-output-{run_id}.log"
    agent_output_log = AgentOutputFileLog(agent_output_log_path)
    runtime = create_async_runtime(
        simulator,
        audit_logger=audit_logger,
        model_overrides=model_overrides,
    )

    missing_hours = simulator.get_missing_gen_hours()
    if missing_hours:
        if verbose and not agent_output_only:
            print(f"Warning: {len(missing_hours)} missing generator actual hours detected: {sorted(missing_hours)[:10]}...")

    results: list[dict[str, Any]] = []
    failed_hours: list[int] = []
    agent_work_logs: list[AgentWorkLog] = []
    live_view = AgentLogTUI(max_lines=tui_lines) if tui and sys.stdout.isatty() else None
    total_planned_hours = end_hour - start_hour
    attempted_hours = 0

    try:
        for hour in range(start_hour, end_hour):
            trace("run_simulation_async.hour.begin", hour=hour)
            if hour in missing_hours:
                if verbose and not agent_output_only:
                    print(f"Skipping hour {hour} - missing generator actuals")
                continue
    
            if verbose and not agent_output_only:
                ts = datetime(2026, 1, 1, 0, 0, 0) + timedelta(hours=hour)
                print(f"Hour {hour} ({ts.strftime('%Y-%m-%d %H:%M')})...")
            attempted_hours += 1
            ts = datetime(2026, 1, 1, 0, 0, 0) + timedelta(hours=hour)
            if phase_callback:
                phase_callback({
                    "phase": "loading_observation",
                    "hour_index": hour,
                    "timestamp": ts.isoformat(),
                    "message": f"Loading grid snapshot for hour {hour}",
                })
    
            with trace_scope("run_simulation_async.simulator.step", hour=hour):
                obs = simulator.step(hour)
    
            audit_line_start = len(audit_logger.get_lines())
    
            with trace_scope("run_simulation_async.runtime.distribute_observation", hour=hour):
                observations = runtime.distribute_observation(obs)
            if phase_callback:
                phase_callback({
                    "phase": "distributing_observation",
                    "hour_index": hour,
                    "timestamp": obs.timestamp.isoformat(),
                    "message": "Distributing observation to coordinator, regional agents, and oracle",
                })
    
            with trace_scope("run_simulation_async.runtime.collect_agent_outputs", hour=hour):
                responses = await runtime.collect_agent_outputs_async(observations, progress_callback=phase_callback)
    
            hour_agent_logs = build_agent_work_logs(
                hour_index=hour,
                responses=responses,
                model_lookup={agent_id: runtime.get_agent_model(agent_id) for agent_id in responses},
            )
            agent_work_logs.extend(hour_agent_logs)
    
            if (verbose_agent_logs or tui) and live_view is None and not agent_output_only:
                print_agent_work_logs(hour_agent_logs)
    
            actions: list[ActionBundle] = []
            for agent_id, response in responses.items():
                if response.action and not response.action.is_empty():
                    actions.append(response.action)
    
            trace("run_simulation_async.actions", hour=hour, count=len(actions))
            if phase_callback:
                phase_callback({
                    "phase": "simulating_actions",
                    "hour_index": hour,
                    "timestamp": obs.timestamp.isoformat(),
                    "message": f"Simulating {len(actions)} validated action(s) against load flow",
                })
    
            with trace_scope("run_simulation_async.runtime.execute_validated_actions", hour=hour, actions=len(actions)):
                eval_results = await runtime.execute_validated_actions_async(actions)
    
            if agent_output_only:
                print_agent_output_only(hour_agent_logs, audit_logger.get_lines()[audit_line_start:])
            agent_output_log.append(hour_agent_logs, audit_logger.get_lines()[audit_line_start:])
    
            step_failure = False
            for er in eval_results:
                if not er.get("accepted", False):
                    step_failure = True
                    break
    
                lf_result = er.get("load_flow_result")
                if lf_result:
                    if not lf_result.get("converged", False):
                        step_failure = True
                        break
                    if lf_result.get("violations"):
                        step_failure = True
                        break
    
            n1_result = None
            load_shedding_committed = any(action.load_shedding_flags for action in actions)
            skip_redundant_fail_fast_n1 = load_shedding_committed and not full_n1_scan
            if not step_failure and not skip_redundant_fail_fast_n1:
                trace("run_simulation_async.n1.start", hour=hour, full_scan=full_n1_scan)
                if phase_callback:
                    phase_callback({
                        "phase": "n1_scan",
                        "hour_index": hour,
                        "timestamp": obs.timestamp.isoformat(),
                        "message": "Running N-1 contingency security scan",
                    })
                n1_result = await asyncio.to_thread(
                    n1_security_scan,
                    simulator.current_network_state,
                    simulated_time=obs.timestamp,
                    max_loading_percent=simulator.constraints.max_branch_loading_percent,
                    min_voltage_pu=simulator.constraints.min_voltage_pu,
                    max_voltage_pu=simulator.constraints.max_voltage_pu,
                    stop_on_first_violation=not full_n1_scan,
                )
    
                if not n1_result.passed:
                    step_failure = True
                trace(
                    "run_simulation_async.n1.done",
                    hour=hour,
                    passed=n1_result.passed,
                    contingencies=len(n1_result.contingencies),
                    violations=len(n1_result.violated_contingencies),
                )
            elif skip_redundant_fail_fast_n1:
                trace(
                    "run_simulation_async.n1.skip_redundant_fail_fast",
                    hour=hour,
                    load_shedding_actions=sum(1 for action in actions if action.load_shedding_flags),
                )
    
            if step_failure and hour not in failed_hours:
                failed_hours.append(hour)
    
            if live_view is not None:
                live_view.update(
                    hour_index=hour,
                    total_hours=total_planned_hours,
                    logs=hour_agent_logs,
                    audit_lines=audit_logger.get_lines(),
                    failed_hours=failed_hours,
                )
    
            results.append(
                {
                    "hour_index": hour,
                    "timestamp": obs.timestamp.isoformat(),
                    "observation": obs,
                    "agent_responses": responses,
                    "evaluation_results": eval_results,
                    "n1_passed": n1_result.passed if n1_result is not None else None,
                    "n1_violations": n1_result.violated_contingencies if n1_result is not None else (),
                    "step_failed": step_failure,
                }
            )
            if progress_callback:
                progress_callback(_frontend_hour_result(results[-1]))
    
            if step_failure and stop_on_failure:
                if verbose and not agent_output_only:
                    print(f"Simulation FAILED at hour {hour} - stopping")
                trace("run_simulation_async.hour.stop_on_failure", hour=hour)
                break

    finally:
        simulator.shutdown_physics_pool()
    successful_hours = len([r for r in results if not r.get("step_failed", False)])
    replay_coverage = successful_hours / max(1, attempted_hours) * 100

    trace(
        "run_simulation_async.done",
        total_hours=len(results),
        failed_hours=len(failed_hours),
        replay_coverage_percent=round(replay_coverage, 3),
    )
    return {
        "total_hours": len(results),
        "failed_hours": failed_hours,
        "replay_coverage_percent": replay_coverage,
        "results": results,
        "audit_logs": audit_logger.get_logs(),
        "agent_work_logs": agent_work_logs,
        "agent_output_log_path": str(agent_output_log.path),
        "missing_gen_hours": sorted(missing_hours),
    }


def _frontend_hour_result(result: dict[str, Any]) -> dict[str, Any]:
    obs = result["observation"]
    responses = result.get("agent_responses", {})
    n1_violations = result.get("n1_violations", ())
    return {
        "hour_index": result["hour_index"],
        "timestamp": result["timestamp"],
        "status": "failed" if result.get("step_failed") else "passed",
        "observation": {
            "hour_index": obs.hour_index,
            "timestamp": obs.timestamp.isoformat(),
            "total_generation_mw": round(obs.scada.total_generation_mw, 2),
            "total_load_mw": round(obs.scada.total_load_mw, 2),
            "imbalance_mw": round(obs.scada.total_load_mw - obs.scada.total_generation_mw, 2),
            "system_frequency_hz": obs.scada.system_frequency_hz,
            "num_generators": len(obs.scada.generators),
            "num_loads": len(obs.scada.loads),
            "num_buses": len(obs.scada.buses),
            "num_branches": len(obs.scada.branches),
            "has_violations": obs.has_violations(),
            "market_price_eur_mwh": obs.market_state.system_marginal_price_eur_mwh,
        },
        "actions": [
            {
                "agent_id": response.agent_id,
                "reasoning": response.reasoning,
                "model": "async-runtime",
                "load_shedding": len(response.action.load_shedding_flags) if response.action else 0,
                "redispatch": len(response.action.redispatch_requests) if response.action else 0,
                "setpoint_changes": len(response.action.generator_setpoint_changes) if response.action else 0,
            }
            for response in responses.values()
        ],
        "n1_passed": result.get("n1_passed"),
        "n1_violations": [
            {
                "element": getattr(v, "element", str(v)),
                "status": getattr(getattr(v, "status", "failed"), "value", "failed"),
                "violations": list(getattr(v, "violations", ())),
            }
            for v in n1_violations
        ],
        "step_failed": bool(result.get("step_failed")),
        "evaluation_results": result.get("evaluation_results", []),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AthenaAI Phase 2.2 Simulation")
    parser.add_argument("--dataset-root", type=str, default=None)
    parser.add_argument("--start-hour", type=int, default=0)
    parser.add_argument("--end-hour", type=int, default=24)
    parser.add_argument("--no-stop-on-failure", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--verbose-agent-logs",
        action="store_true",
        help="Print every agent response, selected model, and action summary as the simulation runs.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Show a dependency-free live terminal dashboard with agent logs and audit tail.",
    )
    parser.add_argument(
        "--tui-lines",
        type=int,
        default=30,
        help="Maximum number of agent log lines to keep in the live dashboard.",
    )
    parser.add_argument(
        "--allow-fallback-physics",
        action="store_true",
        help=(
            "Allow accepted state commits when pandapower is unavailable and the "
            "deterministic fallback load-flow check passes. Without this flag, "
            "fallback physics is reported but blocks physical control."
        ),
    )
    parser.add_argument(
        "--full-n1-scan",
        action="store_true",
        help=(
            "Run every N-1 contingency before reporting the hour result. By default, "
            "simulation gating stops at the first N-1 violation so live runs stay responsive."
        ),
    )
    parser.add_argument(
        "--trace-functions",
        action="store_true",
        help=(
            "Print very verbose function-level trace logs to stderr for debugging slow runs. "
            "Can also be enabled with ATHENAAI_TRACE=1."
        ),
    )
    parser.add_argument(
        "--agent-output-only",
        action="store_true",
        help=(
            "Print only agent-facing output: reasoning/action lines and agent audit/tool events. "
            "Suppresses normal hour progress and final simulation summary."
        ),
    )
    parser.add_argument(
        "--agent-output-log",
        type=str,
        default=None,
        help=(
            "Path for the agent-output log file. Defaults to "
            "logs/agent-output-YYYYMMDD-HHMMSS.log."
        ),
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the model for all AthenaAI agents for this run.",
    )
    parser.add_argument(
        "--coordinator-model",
        type=str,
        default=None,
        help="Override only the national coordinator model.",
    )
    parser.add_argument(
        "--regional-model",
        type=str,
        default=None,
        help="Override all regional agent models.",
    )
    parser.add_argument(
        "--oracle-model",
        type=str,
        default=None,
        help="Override only the Oracle diagnostic agent model.",
    )
    parser.add_argument("--bohemia-west-model", type=str, default=None)
    parser.add_argument("--bohemia-east-model", type=str, default=None)
    parser.add_argument("--moravia-model", type=str, default=None)
    parser.add_argument("--silesia-model", type=str, default=None)
    args = parser.parse_args()

    model_overrides = build_model_overrides(args)

    dataset_root = Path(args.dataset_root) if args.dataset_root else DATASET_ROOT
    if not dataset_root.exists():
        print(f"Error: Dataset root not found: {dataset_root}")
        sys.exit(1)

    result = run_simulation(
        dataset_root=dataset_root,
        start_hour=args.start_hour,
        end_hour=args.end_hour,
        stop_on_failure=not args.no_stop_on_failure,
        verbose=not args.quiet,
        model_overrides=model_overrides,
        verbose_agent_logs=args.verbose_agent_logs,
        tui=args.tui,
        tui_lines=args.tui_lines,
        allow_fallback_physics=args.allow_fallback_physics,
        full_n1_scan=args.full_n1_scan,
        trace_functions=args.trace_functions,
        agent_output_only=args.agent_output_only,
        agent_output_log_path=Path(args.agent_output_log) if args.agent_output_log else None,
    )

    if not args.agent_output_only:
        print(f"\nSimulation complete:")
        print(f"  Total hours: {result['total_hours']}")
        print(f"  Failed hours: {len(result['failed_hours'])}")
        print(f"  Replay coverage: {result['replay_coverage_percent']:.1f}%")
        print(f"  Missing gen hours: {len(result['missing_gen_hours'])}")
        print(f"  Agent output log: {result['agent_output_log_path']}")

    if result["failed_hours"]:
        sys.exit(1)


def main_async() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AthenaAI Phase 2.2 Simulation (async)")
    parser.add_argument("--dataset-root", type=str, default=None)
    parser.add_argument("--start-hour", type=int, default=0)
    parser.add_argument("--end-hour", type=int, default=24)
    parser.add_argument("--no-stop-on-failure", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--verbose-agent-logs",
        action="store_true",
        help="Print every agent response, selected model, and action summary as the simulation runs.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Show a dependency-free live terminal dashboard with agent logs and audit tail.",
    )
    parser.add_argument(
        "--tui-lines",
        type=int,
        default=30,
        help="Maximum number of agent log lines to keep in the live dashboard.",
    )
    parser.add_argument(
        "--allow-fallback-physics",
        action="store_true",
        help=(
            "Allow accepted state commits when pandapower is unavailable and the "
            "deterministic fallback load-flow check passes. Without this flag, "
            "fallback physics is reported but blocks physical control."
        ),
    )
    parser.add_argument(
        "--full-n1-scan",
        action="store_true",
        help=(
            "Run every N-1 contingency before reporting the hour result. By default, "
            "simulation gating stops at the first N-1 violation so live runs stay responsive."
        ),
    )
    parser.add_argument(
        "--trace-functions",
        action="store_true",
        help=(
            "Print very verbose function-level trace logs to stderr for debugging slow runs. "
            "Can also be enabled with ATHENAAI_TRACE=1."
        ),
    )
    parser.add_argument(
        "--agent-output-only",
        action="store_true",
        help=(
            "Print only agent-facing output: reasoning/action lines and agent audit/tool events. "
            "Suppresses normal hour progress and final simulation summary."
        ),
    )
    parser.add_argument(
        "--agent-output-log",
        type=str,
        default=None,
        help=(
            "Path for the agent-output log file. Defaults to "
            "logs/agent-output-YYYYMMDD-HHMMSS.log."
        ),
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the model for all AthenaAI agents for this run.",
    )
    parser.add_argument(
        "--coordinator-model",
        type=str,
        default=None,
        help="Override only the national coordinator model.",
    )
    parser.add_argument(
        "--regional-model",
        type=str,
        default=None,
        help="Override all regional agent models.",
    )
    parser.add_argument(
        "--oracle-model",
        type=str,
        default=None,
        help="Override only the Oracle diagnostic agent model.",
    )
    parser.add_argument("--bohemia-west-model", type=str, default=None)
    parser.add_argument("--bohemia-east-model", type=str, default=None)
    parser.add_argument("--moravia-model", type=str, default=None)
    parser.add_argument("--silesia-model", type=str, default=None)
    args = parser.parse_args()

    model_overrides = build_model_overrides(args)

    dataset_root = Path(args.dataset_root) if args.dataset_root else DATASET_ROOT
    if not dataset_root.exists():
        print(f"Error: Dataset root not found: {dataset_root}")
        sys.exit(1)

    result = asyncio.run(
        run_simulation_async(
            dataset_root=dataset_root,
            start_hour=args.start_hour,
            end_hour=args.end_hour,
            stop_on_failure=not args.no_stop_on_failure,
            verbose=not args.quiet,
            model_overrides=model_overrides,
            verbose_agent_logs=args.verbose_agent_logs,
            tui=args.tui,
            tui_lines=args.tui_lines,
            allow_fallback_physics=args.allow_fallback_physics,
            full_n1_scan=args.full_n1_scan,
            trace_functions=args.trace_functions,
            agent_output_only=args.agent_output_only,
            agent_output_log_path=Path(args.agent_output_log) if args.agent_output_log else None,
        )
    )

    if not args.agent_output_only:
        print(f"\nSimulation complete:")
        print(f"  Total hours: {result['total_hours']}")
        print(f"  Failed hours: {len(result['failed_hours'])}")
        print(f"  Replay coverage: {result['replay_coverage_percent']:.1f}%")
        print(f"  Missing gen hours: {len(result['missing_gen_hours'])}")
        print(f"  Agent output log: {result['agent_output_log_path']}")

    if result["failed_hours"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
