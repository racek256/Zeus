"""AI Copilot — runs the full AthenaAI simulation and exposes it to the frontend.

The simulation loop (from run_simulation.py) is the core:
  for hour in 0..23:
    obs = simulator.step(hour)
    observations = runtime.distribute_observation(obs)
    responses = runtime.collect_agent_outputs(observations)
    actions = [r.action for r in responses if r.action]
    eval_results = runtime.execute_validated_actions(actions)
    n1_result = n1_security_scan(...)
    score / record

This module wraps that loop in a background thread and streams results to the
FastAPI endpoints so the frontend can display live simulation progress.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time as _time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ATHENAAI_ROOT = Path(__file__).resolve().parent.parent / "AI" / "AthenaAI"
if str(_ATHENAAI_ROOT) not in sys.path:
    sys.path.insert(0, str(_ATHENAAI_ROOT))

from athenaai.agent_runtime import AgentRuntime, create_runtime  # noqa: E402
from athenaai.audit.logger import AuditLogger  # noqa: E402
from athenaai.config import DATASET_ROOT, AGENT_COORDINATOR, ALL_AGENTS, KIMI_K2_6_MODEL  # noqa: E402
from athenaai.model_client import OpenCodeModelClient  # noqa: E402
from athenaai.physics.n1 import n1_security_scan  # noqa: E402
from athenaai.schema import (  # noqa: E402
    ActionBundle,
    GeneratorSetpointChange,
    InterconnectFlowAdjustment,
    LoadSheddingFlag,
    ObservationBundle,
    RedispatchRequest,
)
from athenaai.simulator import GridSimulator  # noqa: E402
from athenaai.trace import set_trace_enabled  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, frozenset):
        return [_jsonable(item) for item in value]
    return value


def _action_to_dict(action: ActionBundle) -> dict[str, Any]:
    return {
        "timestamp": action.timestamp.isoformat(),
        "agent_id": action.agent_id,
        "generator_setpoint_changes": [
            {
                "generator_id": c.generator_id,
                "new_setpoint_mw": c.new_setpoint_mw,
                "ramp_rate_mw_per_min": c.ramp_rate_mw_per_min,
            }
            for c in action.generator_setpoint_changes
        ],
        "redispatch_requests": [
            {
                "generator_id": r.generator_id,
                "region": r.region,
                "upward_mw": r.upward_mw,
                "downward_mw": r.downward_mw,
                "reason": r.reason,
            }
            for r in action.redispatch_requests
        ],
        "load_shedding_flags": [
            {
                "load_id": f.load_id,
                "region": f.region,
                "shed_mw": f.shed_mw,
                "priority": f.priority,
            }
            for f in action.load_shedding_flags
        ],
        "interconnect_flow_adjustments": [
            {
                "border": a.border,
                "target_flow_mw": a.target_flow_mw,
                "current_flow_mw": a.current_flow_mw,
            }
            for a in action.interconnect_flow_adjustments
        ],
    }


def _observation_summary(obs: ObservationBundle) -> dict[str, Any]:
    return {
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
    }


def _n1_to_dict(n1_result: Any) -> dict[str, Any]:
    return {
        "passed": n1_result.passed,
        "status": n1_result.status.value,
        "message": n1_result.message,
        "contingencies_tested": len(n1_result.contingencies),
        "violated_contingencies": [
            {"element": c} if isinstance(c, str) else {
                "element": c.element,
                "status": c.status.value,
                "violations": list(c.violations),
            }
            for c in n1_result.violated_contingencies
        ],
    }


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class HourResult:
    hour_index: int
    timestamp: str
    observation: dict[str, Any]
    agent_outputs: list[dict[str, Any]]
    proposals: list[dict[str, Any]]
    actions_executed: int
    actions_accepted: int
    n1_passed: bool | None
    n1_detail: dict[str, Any] | None
    n1_failed: bool
    step_failed: bool
    evaluation_results: list[dict[str, Any]]


@dataclass
class SimulationRun:
    run_id: str
    status: str  # pending | running | completed | failed
    start_hour: int
    end_hour: int
    current_hour: int
    total_hours: int
    completed_hours: int
    failed_hours: list[int]
    n1_failed_hours: list[int]
    replay_coverage_percent: float
    hours: list[HourResult]
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    phase: str = "pending"
    phase_detail: str = "Waiting to start"
    active_agent: str | None = None
    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class CopilotState:
    initialised: bool = False
    simulator: GridSimulator | None = None
    runtime: AgentRuntime | None = None
    audit_logger: AuditLogger | None = None
    simulation: SimulationRun | None = None
    proposals: list[dict[str, Any]] = field(default_factory=list)
    chat_history: list[dict[str, str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = CopilotState()
_API_AGENT_ATTEMPTS = 999999


def get_copilot_state() -> CopilotState:
    return _state


# ── Initialisation ───────────────────────────────────────────────────────────

def initialise(dataset_root: Path | None = None, allow_fallback_physics: bool = True) -> dict[str, Any]:
    global _state
    with _state.lock:
        if _state.initialised:
            return {"status": "already_initialised"}

        root = dataset_root or DATASET_ROOT
        sim = GridSimulator(dataset_root=root, start_hour=0, allow_fallback_physics=allow_fallback_physics)
        sim.initialize()

        audit = AuditLogger()
        runtime = create_runtime(simulator=sim, audit_logger=audit)

        _state.simulator = sim
        _state.runtime = runtime
        _state.audit_logger = audit
        _state.initialised = True

        return {
            "status": "initialised",
            "dataset_root": str(root),
            "generators": len(sim.current_network_state.get("generators", [])),
            "loads": len(sim.current_network_state.get("loads", [])),
            "buses": len(sim.current_network_state.get("buses", [])),
            "branches": len(sim.current_network_state.get("branches", [])),
        }


# ── Simulation loop ─────────────────────────────────────────────────────────

from run_simulation import run_simulation_async as _run_simulation_async  # noqa: E402


def _run_sim_thread(
    run: SimulationRun,
    stop_on_failure: bool,
    allow_fallback_physics: bool,
    full_n1_scan: bool,
    model: str | None,
) -> None:
    asyncio.run(_run_sim_async(run, stop_on_failure, allow_fallback_physics, full_n1_scan, model))


async def _run_sim_async(
    run: SimulationRun,
    stop_on_failure: bool,
    allow_fallback_physics: bool,
    full_n1_scan: bool,
    model: str | None,
) -> None:
    try:
        def phase_callback(event: dict[str, Any]) -> None:
            with _state.lock:
                phase = str(event.get("phase", "running"))
                agent_id = event.get("agent_id")
                run.phase = phase
                run.phase_detail = str(event.get("message", phase.replace("_", " ")))
                run.current_hour = int(event.get("hour_index", run.current_hour))
                run.active_agent = str(agent_id) if agent_id else None
                if agent_id:
                    state = "reasoning" if phase == "agent_reasoning" else "completed"
                    run.agent_states[str(agent_id)] = {
                        "status": state,
                        "phase": phase,
                        "message": run.phase_detail,
                        "reasoning": event.get("reasoning"),
                        "has_action": bool(event.get("has_action", False)),
                        "updated_at": datetime.now().isoformat(),
                    }

        def progress_callback(hour_result: dict[str, Any]) -> None:
            with _state.lock:
                run.current_hour = hour_result["hour_index"]
                run.phase = "hour_complete"
                run.phase_detail = f"Hour {hour_result['hour_index']} completed"
                run.active_agent = None
                
                proposals = []
                for action in hour_result.get("actions", []):
                    if action.get("load_shedding", 0) > 0 or action.get("redispatch", 0) > 0:
                        proposal = {
                            "proposal_id": f"p-{hour_result['hour_index']}-{action['agent_id']}-{len(_state.proposals)}",
                            "hour_index": hour_result["hour_index"],
                            "agent_id": action["agent_id"],
                            "action": action,
                            "timestamp": hour_result["timestamp"],
                            "status": "auto-executed",
                        }
                        proposals.append(proposal)
                        _state.proposals.append(proposal)
                
                n1_passed = hour_result.get("n1_passed")
                n1_violations = hour_result.get("n1_violations", [])
                n1_detail = None if n1_passed is None else {
                    "passed": n1_passed,
                    "status": "passed" if n1_passed else "failed",
                    "message": "N-1 scan " + ("passed" if n1_passed else "failed"),
                    "contingencies_tested": len(n1_violations),
                    "violated_contingencies": n1_violations,
                }

                hr = HourResult(
                    hour_index=hour_result["hour_index"],
                    timestamp=hour_result["timestamp"],
                    observation=hour_result.get("observation", {
                        "hour_index": hour_result["hour_index"],
                        "timestamp": hour_result["timestamp"],
                        "total_generation_mw": 0,
                        "total_load_mw": 0,
                        "imbalance_mw": 0,
                        "system_frequency_hz": 50.0,
                        "num_generators": 0,
                        "num_loads": 0,
                        "num_buses": 0,
                        "num_branches": 0,
                        "has_violations": False,
                        "market_price_eur_mwh": 0,
                    }),
                    agent_outputs=[
                        {
                            "agent_id": a["agent_id"],
                            "reasoning": a.get("reasoning", "Monitoring"),
                            "has_action": a.get("load_shedding", 0) > 0 or a.get("redispatch", 0) > 0,
                            "model": a.get("model", "deterministic"),
                        }
                        for a in hour_result.get("actions", [])
                    ],
                    proposals=proposals,
                    actions_executed=len(hour_result.get("actions", [])),
                    actions_accepted=sum(1 for a in hour_result.get("actions", []) if a.get("agent_id")),
                    n1_passed=n1_passed,
                    n1_detail=n1_detail,
                    n1_failed=n1_passed is False,
                    step_failed=hour_result["status"] == "failed",
                    evaluation_results=_jsonable(hour_result.get("evaluation_results", [])),
                )
                
                run.hours.append(hr)
                run.completed_hours = len(run.hours)
                
                if hour_result["status"] == "failed":
                    run.failed_hours.append(hour_result["hour_index"])
                if n1_passed is False:
                    run.n1_failed_hours.append(hour_result["hour_index"])

        final_hour_results: list[dict[str, Any]] = []
        final_result: dict[str, Any] | None = None
        for attempt in range(1, _API_AGENT_ATTEMPTS + 1):
            attempt_hour_results: list[dict[str, Any]] = []

            def attempt_progress_callback(hour_result: dict[str, Any]) -> None:
                attempt_hour_results.append(hour_result)
                progress_callback(hour_result)

            def attempt_phase_callback(event: dict[str, Any]) -> None:
                updated = dict(event)
                message = str(updated.get("message", updated.get("phase", "running")))
                updated["message"] = f"{message} (attempt {attempt})"
                phase_callback(updated)

            with _state.lock:
                run.hours.clear()
                run.failed_hours.clear()
                run.n1_failed_hours.clear()
                run.completed_hours = 0
                run.phase = "agent_retry" if attempt > 1 else "running"
                run.phase_detail = f"Running AI agents, attempt {attempt}"

            final_result = await _run_simulation_async(
                dataset_root=DATASET_ROOT,
                start_hour=run.start_hour,
                end_hour=run.end_hour,
                stop_on_failure=stop_on_failure,
                verbose=False,
                model_overrides={"all": model} if model else None,
                allow_fallback_physics=allow_fallback_physics,
                full_n1_scan=full_n1_scan,
                progress_callback=attempt_progress_callback,
                phase_callback=attempt_phase_callback,
            )
            final_hour_results = attempt_hour_results
            if not final_result.get("failed_hours"):
                break
            if attempt < _API_AGENT_ATTEMPTS:
                with _state.lock:
                    run.phase = "agent_retry"
                    run.phase_detail = f"Retrying rejected AI output, attempt {attempt + 1}"
        
        successful = len([h for h in run.hours if not h.step_failed])
        attempted = run.completed_hours or 1
        run.replay_coverage_percent = round(successful / attempted * 100, 1)
        run.status = "completed"
        run.phase = "completed"
        run.phase_detail = "Simulation completed"
        run.active_agent = None
        run.finished_at = datetime.now().isoformat()
        
    except Exception as exc:
        run.status = "failed"
        run.phase = "failed"
        run.phase_detail = str(exc)[:200]
        run.active_agent = None
        run.error = str(exc)[:500]
        run.finished_at = datetime.now().isoformat()


def start_simulation(
    start_hour: int = 0,
    end_hour: int | None = None,
    stop_on_failure: bool = True,
    allow_fallback_physics: bool = False,
    full_n1_scan: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    global _state
    resolved_end_hour = start_hour + 1 if end_hour is None else end_hour
    with _state.lock:
        if not _state.initialised:
            raise RuntimeError("Copilot not initialised — call /api/copilot/init first")
        if _state.simulation and _state.simulation.status == "running":
            raise RuntimeError("Simulation already running")

        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        run = SimulationRun(
            run_id=run_id,
            status="running",
            start_hour=start_hour,
            end_hour=resolved_end_hour,
            current_hour=start_hour,
            total_hours=resolved_end_hour - start_hour,
            completed_hours=0,
            failed_hours=[],
            n1_failed_hours=[],
            replay_coverage_percent=0.0,
            hours=[],
            started_at=datetime.now().isoformat(),
        )
        _state.simulation = run

        thread = threading.Thread(
            target=_run_sim_thread,
            args=(run, stop_on_failure, allow_fallback_physics, full_n1_scan, model),
            daemon=True,
        )
        thread.start()

        return {
            "status": "started",
            "run_id": run_id,
            "start_hour": start_hour,
            "end_hour": resolved_end_hour,
            "model": model,
        }


def get_simulation_status() -> dict[str, Any]:
    global _state
    with _state.lock:
        sim = _state.simulation
        if sim is None:
            return {"status": "no_simulation"}
        return {
            "run_id": sim.run_id,
            "status": sim.status,
            "start_hour": sim.start_hour,
            "end_hour": sim.end_hour,
            "current_hour": sim.current_hour,
            "total_hours": sim.total_hours,
            "completed_hours": sim.completed_hours,
            "failed_hours": sim.failed_hours,
            "n1_failed_hours": sim.n1_failed_hours,
            "replay_coverage_percent": sim.replay_coverage_percent,
            "started_at": sim.started_at,
            "finished_at": sim.finished_at,
            "error": sim.error,
            "phase": sim.phase,
            "phase_detail": sim.phase_detail,
            "active_agent": sim.active_agent,
            "agent_states": sim.agent_states,
        }


def get_simulation_hours() -> list[dict[str, Any]]:
    global _state
    with _state.lock:
        sim = _state.simulation
        if sim is None:
            return []
        return [
            {
                "hour_index": h.hour_index,
                "timestamp": h.timestamp,
                "observation": h.observation,
                "agent_outputs": h.agent_outputs,
                "proposals": h.proposals,
                "actions_executed": h.actions_executed,
                "actions_accepted": h.actions_accepted,
                "n1_passed": h.n1_passed,
                "n1_detail": h.n1_detail,
                "n1_failed": h.n1_failed,
                "step_failed": h.step_failed,
                "evaluation_results": h.evaluation_results,
            }
            for h in sim.hours
        ]


def get_simulation_hour(hour_index: int) -> dict[str, Any] | None:
    global _state
    with _state.lock:
        sim = _state.simulation
        if sim is None:
            return None
        for h in sim.hours:
            if h.hour_index == hour_index:
                return {
                    "hour_index": h.hour_index,
                    "timestamp": h.timestamp,
                    "observation": h.observation,
                    "agent_outputs": h.agent_outputs,
                    "proposals": h.proposals,
                    "actions_executed": h.actions_executed,
                    "actions_accepted": h.actions_accepted,
                    "n1_passed": h.n1_passed,
                    "n1_detail": h.n1_detail,
                    "n1_failed": h.n1_failed,
                    "step_failed": h.step_failed,
                    "evaluation_results": h.evaluation_results,
                }
        return None


# ── Chat ─────────────────────────────────────────────────────────────────────

def chat(message: str) -> dict[str, Any]:
    global _state
    with _state.lock:
        _state.chat_history.append({
            "role": "operator",
            "content": message,
            "timestamp": datetime.now().isoformat(),
        })

        sim = _state.simulation
        msg_lower = message.lower()

        context_parts: list[str] = []
        if sim:
            context_parts.append(
                f"Simulation {sim.run_id}: {sim.status}, "
                f"{sim.completed_hours}/{sim.total_hours} hours completed, "
                f"{len(sim.failed_hours)} operational failures, "
                f"{len(sim.n1_failed_hours)} N-1 violations."
            )
            if sim.status == "running":
                context_parts.append(f"Currently at hour {sim.current_hour}.")
            elif sim.status == "completed":
                context_parts.append(f"Replay coverage: {sim.replay_coverage_percent}%.")

        pending = [p for p in _state.proposals if p.get("status") == "pending"]
        if pending:
            context_parts.append(f"{len(pending)} proposal(s) awaiting operator review.")

        if any(w in msg_lower for w in ["status", "summary", "progress"]):
            answer = " ".join(context_parts) if context_parts else "No simulation running."
        elif any(w in msg_lower for w in ["fail", "error", "reject"]):
            if sim and sim.failed_hours:
                answer = f"Operationally failed hours: {sim.failed_hours[:10]}"
            else:
                answer = "No operational failures recorded."
        elif any(w in msg_lower for w in ["n-1", "n1", "security"]):
            recent = sim.hours[-1] if sim and sim.hours else None
            if recent and recent.n1_detail:
                n1 = recent.n1_detail
                answer = (
                    f"Last N-1 scan (hour {recent.hour_index}): "
                    f"{'PASSED' if n1['passed'] else 'FAILED'}. "
                    f"{n1['message']}"
                )
            else:
                answer = "No N-1 data available."
        else:
            answer = (
                "Available commands:\n"
                "- 'status' — simulation progress\n"
                "- 'fail' — failed hours\n"
                "- 'n-1' — last security scan\n\n"
                + " ".join(context_parts)
            )

        _state.chat_history.append({
            "role": "athena",
            "content": answer,
            "timestamp": datetime.now().isoformat(),
        })

        return {"response": answer, "chat_history": _state.chat_history[-10:]}


def get_proposals(status: str | None = None) -> list[dict[str, Any]]:
    global _state
    with _state.lock:
        props = _state.proposals
        if status:
            props = [p for p in props if p.get("status") == status]
        return props


def get_status() -> dict[str, Any]:
    global _state
    with _state.lock:
        sim = _state.simulation
        return {
            "initialised": _state.initialised,
            "simulation_running": sim is not None and sim.status == "running",
            "simulation_status": sim.status if sim else "none",
            "current_hour": sim.current_hour if sim else 0,
            "completed_hours": sim.completed_hours if sim else 0,
            "total_hours": sim.total_hours if sim else 0,
            "failed_hours": len(sim.failed_hours) if sim else 0,
            "n1_failed_hours": len(sim.n1_failed_hours) if sim else 0,
            "replay_coverage": sim.replay_coverage_percent if sim else 0,
            "total_proposals": len(_state.proposals),
            "chat_messages": len(_state.chat_history),
        }
