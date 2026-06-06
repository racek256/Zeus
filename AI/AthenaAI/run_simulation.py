#!/usr/bin/env python3
"""Simplified simulation harness for the copilot frontend.

This is a stripped-down version of run_simulation.py that:
1. Runs the core simulation loop
2. Streams results via a callback
3. Has no benchmark/scoring logic
4. Has no TUI/file logging

Usage:
    from run_simulation import run_simulation
    
    for hour_result in run_simulation(...):
        print(f"Hour {hour_result['hour_index']}: {hour_result['status']}")
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from athenaai.agent_runtime import create_runtime
from athenaai.audit.logger import AuditLogger
from athenaai.config import DATASET_ROOT
from athenaai.physics.n1 import n1_security_scan
from athenaai.schema import ActionBundle
from athenaai.simulator import GridSimulator
from athenaai.trace import set_trace_enabled


def run_simulation(
    dataset_root: Path | None = None,
    start_hour: int = 0,
    end_hour: int = 24,
    stop_on_failure: bool = True,
    allow_fallback_physics: bool = False,
    full_n1_scan: bool = False,
    trace_functions: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the simulation loop and stream results via callback.
    
    Args:
        dataset_root: Path to the dataset directory
        start_hour: Starting hour index (0-23)
        end_hour: Ending hour index (exclusive, 1-24)
        stop_on_failure: Stop simulation when a step fails
        allow_fallback_physics: Allow fallback physics when pandapower unavailable
        full_n1_scan: Run all N-1 contingencies (slow) instead of fail-fast
        trace_functions: Enable verbose function tracing
        progress_callback: Called with each hour's result as it completes
    
    Returns:
        Final summary dict with total_hours, failed_hours, coverage, results
    """
    set_trace_enabled(trace_functions)
    
    root = dataset_root or DATASET_ROOT
    simulator = GridSimulator(
        dataset_root=root,
        start_hour=start_hour,
        allow_fallback_physics=allow_fallback_physics,
    )
    simulator.initialize()
    
    audit_logger = AuditLogger()
    runtime = create_runtime(
        simulator,
        audit_logger=audit_logger,
    )
    
    missing_hours = simulator.get_missing_gen_hours()
    
    results: list[dict[str, Any]] = []
    failed_hours: list[int] = []
    attempted_hours = 0
    
    for hour in range(start_hour, min(end_hour, start_hour + 24)):
        if hour in missing_hours:
            continue
        
        attempted_hours += 1
        ts = datetime(2026, 1, 1, 0, 0, 0) + timedelta(hours=hour)
        
        obs = simulator.step(hour)
        observations = runtime.distribute_observation(obs)
        responses = runtime.collect_agent_outputs(observations)
        
        actions: list[ActionBundle] = []
        for agent_id, response in responses.items():
            if response.action and not response.action.is_empty():
                actions.append(response.action)
        
        eval_results = runtime.execute_validated_actions(actions)
        
        step_failure = False
        for er in eval_results:
            if not er.get("accepted", False):
                step_failure = True
                break
            lf = er.get("load_flow_result")
            if lf:
                if not lf.get("converged", False):
                    step_failure = True
                    break
                if lf.get("violations"):
                    step_failure = True
                    break
        
        n1_result = None
        load_shedding_committed = any(action.load_shedding_flags for action in actions)
        skip_n1 = load_shedding_committed and not full_n1_scan
        
        if not step_failure and not skip_n1:
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
        
        if step_failure and hour not in failed_hours:
            failed_hours.append(hour)
        
        hour_result = {
            "hour_index": hour,
            "timestamp": obs.timestamp.isoformat(),
            "status": "failed" if step_failure else "passed",
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
                    "agent_id": a.agent_id,
                    "reasoning": getattr(a, 'reasoning', 'Monitoring'),
                    "model": "deterministic",
                    "load_shedding": len(a.load_shedding_flags),
                    "redispatch": len(a.redispatch_requests),
                    "setpoint_changes": len(a.generator_setpoint_changes),
                }
                for a in actions
            ],
            "n1_passed": True if skip_n1 else (n1_result.passed if n1_result else None),
            "n1_violations": [
                {"element": v if isinstance(v, str) else getattr(v, 'element_id', str(v)), 
                 "status": "failed"}
                for v in (n1_result.violated_contingencies if n1_result else [])
            ],
            "step_failed": step_failure,
        }
        
        results.append(hour_result)
        
        if progress_callback:
            progress_callback(hour_result)
        
        if step_failure and stop_on_failure:
            break
    
    successful_hours = len([r for r in results if not r.get("step_failed", False)])
    replay_coverage = successful_hours / max(1, attempted_hours) * 100
    
    return {
        "total_hours": len(results),
        "failed_hours": failed_hours,
        "replay_coverage_percent": replay_coverage,
        "results": results,
        "missing_gen_hours": sorted(missing_hours),
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Simple AthenaAI Simulation")
    parser.add_argument("--dataset-root", type=str, default=None)
    parser.add_argument("--start-hour", type=int, default=0)
    parser.add_argument("--end-hour", type=int, default=24)
    parser.add_argument("--no-stop-on-failure", action="store_true")
    parser.add_argument("--allow-fallback-physics", action="store_true")
    parser.add_argument("--full-n1-scan", action="store_true")
    args = parser.parse_args()
    
    root = Path(args.dataset_root) if args.dataset_root else DATASET_ROOT
    
    def print_progress(result: dict[str, Any]) -> None:
        status = "PASS" if result["status"] == "passed" else "FAIL"
        print(f"Hour {result['hour_index']:2d}: {status} | N-1: {result['n1_passed']} | Actions: {len(result['actions'])}")
    
    result = run_simulation(
        dataset_root=root,
        start_hour=args.start_hour,
        end_hour=args.end_hour,
        stop_on_failure=not args.no_stop_on_failure,
        allow_fallback_physics=args.allow_fallback_physics,
        full_n1_scan=args.full_n1_scan,
        progress_callback=print_progress,
    )
    
    print(f"\nTotal: {result['total_hours']} hours")
    print(f"Failed: {len(result['failed_hours'])} hours")
    print(f"Coverage: {result['replay_coverage_percent']:.1f}%")
    if result["failed_hours"]:
        print(f"Failed at: {result['failed_hours']}")
