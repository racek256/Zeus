import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Loader2,
  Play,
  Sparkles,
  Square,
  X,
} from 'lucide-react'
import {
  initCopilot,
  getCopilotStatus,
  startSimulation,
  getSimulationStatus,
  getSimulationHours,
} from '../api/copilot'
import type {
  CopilotStatus,
  SimulationStatus,
  SimulationHourResult,
  AgentOutput,
} from '../types/copilot'

type Phase = 'idle' | 'initialising' | 'running' | 'completed' | 'error'

function simulationPhaseLabel(phase?: string): string {
  switch (phase) {
    case 'loading_observation': return 'Loading snapshot'
    case 'distributing_observation': return 'Distributing state'
    case 'agent_reasoning': return 'Agent reasoning'
    case 'agent_complete': return 'Agent complete'
    case 'simulating_actions': return 'Physics simulation'
    case 'n1_scan': return 'Security scan'
    case 'hour_complete': return 'Hour complete'
    case 'completed': return 'Complete'
    case 'failed': return 'Failed'
    default: return 'Simulating'
  }
}

function phaseLabel(p: Phase): string {
  switch (p) {
    case 'idle': return 'Ready'
    case 'initialising': return 'Initialising'
    case 'running': return 'Simulating'
    case 'completed': return 'Complete'
    case 'error': return 'Error'
  }
}

function phaseTone(p: Phase): string {
  switch (p) {
    case 'running': return 'bg-primary/10 text-primary'
    case 'completed': return 'bg-[#E8F4EC] text-[#1E6F3A]'
    case 'error': return 'bg-[#FFF3D8] text-[#8A4B00]'
    default: return 'bg-surface-high text-on-background'
  }
}

function agentTone(id: string): string {
  switch (id) {
    case 'coordinator': return 'bg-primary/10 text-primary'
    case 'bohemia-west': return 'bg-[#FFE8E8] text-[#8A1C1C]'
    case 'bohemia-east': return 'bg-[#E8F0FF] text-[#1C3D8A]'
    case 'moravia': return 'bg-[#E8FFE8] text-[#1C6F1C]'
    case 'silesia': return 'bg-[#FFF8E0] text-[#6B4B00]'
    case 'oracle': return 'bg-[#F0E8FF] text-[#4B1C8A]'
    default: return 'bg-surface-high text-on-background'
  }
}

function agentName(id: string): string {
  switch (id) {
    case 'coordinator': return 'Coordinator'
    case 'bohemia-west': return 'Bohemia W'
    case 'bohemia-east': return 'Bohemia E'
    case 'moravia': return 'Moravia'
    case 'silesia': return 'Silesia'
    case 'oracle': return 'Oracle'
    default: return id
  }
}

function firstRejectionReason(hour: SimulationHourResult): string | null {
  const rejected = hour.evaluation_results?.find((result) => result.accepted === false)
  if (!rejected) {
    if (hour.step_failed) return 'Prediction was rejected by the simulator.'
    return null
  }

  const validationError = rejected.validation_errors?.find(Boolean)
  if (validationError) return validationError

  const loadFlow = rejected.load_flow_result
  const violation = loadFlow?.violations?.find(Boolean)
  if (violation) return violation
  if (loadFlow?.message) return loadFlow.message
  if (loadFlow?.status) return `Load-flow status: ${loadFlow.status}`
  return 'Action was rejected by load-flow validation.'
}

function balanceSummary(hour: SimulationHourResult): string {
  const imbalance = hour.observation.imbalance_mw
  const absImbalance = Math.abs(imbalance)
  if (absImbalance < 1) return 'Generation and load are balanced.'
  const direction = imbalance > 0 ? 'shortfall' : 'surplus'
  return `${absImbalance.toFixed(1)} MW ${direction} between load and generation.`
}

function securitySummary(hour: SimulationHourResult): string | null {
  if (hour.step_failed) return firstRejectionReason(hour) ?? 'Prediction did not pass operational validation.'
  return 'Prediction passed operational validation.'
}

function actionSummary(hour: SimulationHourResult): string {
  const actingAgents = hour.agent_outputs.filter((agent) => agent.has_action).map((agent) => agentName(agent.agent_id))
  if (actingAgents.length === 0) return 'No corrective action was needed.'
  return `${actingAgents.join(', ')} proposed corrective action.`
}

export function AIDynamicIsland() {
  const [expanded, setExpanded] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [status, setStatus] = useState<CopilotStatus | null>(null)
  const [simStatus, setSimStatus] = useState<SimulationStatus | null>(null)
  const [hours, setHours] = useState<SimulationHourResult[]>([])
  const [selectedHour, setSelectedHour] = useState<number | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const pollSimulation = useCallback(() => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const [s, h] = await Promise.all([getSimulationStatus(), getSimulationHours()])
        setSimStatus(s)
        setHours(h)
        setStatus(await getCopilotStatus())
        if (s.status === 'completed' || s.status === 'failed') {
          stopPolling()
          setPhase(s.status === 'completed' ? 'completed' : 'error')
          if (s.status === 'failed') setError(s.error ?? 'Simulation failed')
        }
      } catch {
        stopPolling()
        setPhase('error')
        setError('Lost connection to simulation')
      }
    }, 800)
  }, [stopPolling])

  const handleInit = useCallback(async () => {
    setPhase('initialising')
    setError(null)
    try {
      await initCopilot()
      setStatus(await getCopilotStatus())
      setPhase('idle')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Init failed')
      setPhase('error')
    }
  }, [])

  const latestHour = hours.length > 0 ? hours[hours.length - 1] : null
  const selected = selectedHour !== null ? hours.find((h) => h.hour_index === selectedHour) ?? null : null
  const display = selected ?? latestHour
  const progress = simStatus ? (simStatus.completed_hours / simStatus.total_hours) * 100 : 0

  const handleStartSim = useCallback(async () => {
    setPhase('running')
    setError(null)
    setHours([])
    setSelectedHour(null)
    setDetailsOpen(false)
    try {
      const nextHour = latestHour ? latestHour.hour_index + 1 : simStatus?.completed_hours ?? 0
      await startSimulation({
        start_hour: nextHour,
        end_hour: 8760,
        stop_on_failure: false,
        allow_fallback_physics: false,
        model: 'deepseek-v4-flash',
      })
      pollSimulation()
    } catch (err) {
      const msg = err instanceof Error ? err.message : ''
      if (msg.includes('already running')) {
        // Resume tracking the already-running simulation
        try {
          const [s, h] = await Promise.all([getSimulationStatus(), getSimulationHours()])
          setSimStatus(s)
          setHours(h)
        } catch {
          setPhase('error')
          setError('Failed to resume existing simulation')
          return
        }
        pollSimulation()
        return
      }
      setError(msg || 'Failed to start')
      setPhase('error')
    }
  }, [latestHour, pollSimulation, simStatus])

  const handleStop = useCallback(() => {
    stopPolling()
    setPhase('idle')
  }, [stopPolling])

  useEffect(() => () => stopPolling(), [stopPolling])

  return (
    <div className="absolute bottom-6 left-1/2 z-20 -translate-x-1/2">
      <div className={`overflow-hidden rounded-[1.35rem] bg-surface-lowest/95 text-on-background shadow-[0_24px_56px_rgba(28,27,27,0.16)] backdrop-blur-[20px] transition-all duration-300 ease-out ${expanded ? 'w-[460px]' : 'w-[430px]'}`}>
        <button type="button" onClick={() => setExpanded((v) => !v)} className="flex w-full items-center gap-3 bg-surface-low px-4 py-3 text-left transition hover:bg-surface-high focus:outline-none focus:ring-2 focus:ring-primary/20">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-primary text-on-primary">
            {phase === 'running' ? <Loader2 size={18} strokeWidth={1.9} className="animate-spin" /> : <Sparkles size={18} strokeWidth={1.9} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-[11px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">Athena</p>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] ${phaseTone(phase)}`}>{phaseLabel(phase)}</span>
            </div>
            <p className="mt-1 truncate text-sm font-semibold text-on-background">
              {error
                ? error
                  : phase === 'running' && simStatus
                    ? simStatus.completed_hours === 0
                      ? `${simulationPhaseLabel(simStatus.phase)} — ${simStatus.phase_detail ?? 'agents generating...'}`
                      : `Simulation survived ${simStatus.completed_hours} hours`
                  : phase === 'completed' && simStatus
                    ? `Survival simulation complete — ${simStatus.completed_hours} hours survived`
                    : display
                      ? `Hour ${display.hour_index}: Gen ${display.observation.total_generation_mw.toFixed(0)} MW · Load ${display.observation.total_load_mw.toFixed(0)} MW`
                      : 'Ready to simulate'}
            </p>
          </div>
          <div className="hidden min-w-[86px] text-right sm:block">
            <p className="font-display text-xl font-extrabold leading-none text-on-background">
              {simStatus ? `${simStatus.completed_hours}` : '—'}
            </p>
            <p className="mt-1 text-[9px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Hours</p>
          </div>
          {expanded ? <ChevronDown size={17} strokeWidth={2} className="text-on-surface-variant" /> : <ChevronUp size={17} strokeWidth={2} className="text-on-surface-variant" />}
        </button>

        {expanded && (
          <div className="bg-surface-low px-4 pb-4">
            <div className="space-y-3">
              <div className="flex gap-2">
                {phase !== 'running' ? (
                  <button onClick={status?.initialised ? handleStartSim : handleInit} className="flex h-9 items-center gap-2 rounded-xl bg-primary px-3 text-xs font-bold text-on-primary transition hover:bg-primary-container focus:outline-none focus:ring-2 focus:ring-primary/20">
                    {phase === 'initialising' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} strokeWidth={2} />}
                    {status?.initialised ? 'Start survival simulation' : 'Init copilot'}
                  </button>
                ) : (
                  <button onClick={handleStop} className="flex h-9 items-center gap-2 rounded-xl bg-[#FFE8E8] px-3 text-xs font-bold text-[#8A1C1C] transition hover:bg-[#FFD0D0] focus:outline-none focus:ring-2 focus:ring-primary/20">
                    <Square size={14} strokeWidth={2} />
                    Stop
                  </button>
                )}
              </div>

              {phase === 'running' && simStatus && (
                <div className="rounded-2xl bg-surface-lowest p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Simulation progress</p>
                    <p className="text-[11px] font-bold text-on-background">{Math.round(progress)}%</p>
                  </div>
                  <div className="h-3 overflow-hidden rounded-full bg-surface-high">
                    <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${progress}%` }} />
                  </div>
                  <div className="mt-2 flex justify-between text-[10px] text-on-surface-variant">
                    <span>{simStatus.completed_hours} completed</span>
                    <span>{simStatus.total_hours - simStatus.completed_hours} remaining</span>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <Loader2 size={12} className="animate-spin text-primary" />
                    <p className="text-[11px] text-on-surface-variant">
                      {simulationPhaseLabel(simStatus.phase)}: {simStatus.phase_detail ?? 'Working...'}
                    </p>
                  </div>
                  {simStatus.active_agent && (
                    <p className="mt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-primary">
                      Active agent: {agentName(simStatus.active_agent)}
                    </p>
                  )}
                  {simStatus.agent_states && Object.keys(simStatus.agent_states).length > 0 && (
                    <div className="mt-2 grid grid-cols-2 gap-1.5">
                      {Object.entries(simStatus.agent_states).map(([id, state]) => (
                        <div key={id} className="rounded-lg bg-surface-low px-2 py-1.5">
                          <div className="flex items-center justify-between gap-1">
                            <span className={`rounded-full px-1.5 py-0.5 text-[8px] font-bold uppercase ${agentTone(id)}`}>{agentName(id)}</span>
                            <span className="text-[8px] font-bold uppercase text-on-surface-variant">{state.status}</span>
                          </div>
                          <p className="mt-1 line-clamp-1 text-[9px] text-on-surface-variant">{state.message}</p>
                        </div>
                      ))}
                    </div>
                  )}
                  {simStatus.completed_hours > 0 && simStatus.completed_hours < simStatus.total_hours && (
                    <div className="mt-2 flex items-center gap-2">
                      <Loader2 size={12} className="animate-spin text-primary" />
                      <p className="text-[11px] text-on-surface-variant">Processing hour {simStatus.current_hour}...</p>
                    </div>
                  )}
                  {simStatus.failed_hours.length > 0 && (
                    <p className="mt-1.5 text-[11px] font-medium text-[#8A1C1C]">{simStatus.failed_hours.length} operational failures: {simStatus.failed_hours.slice(0, 5).join(', ')}{simStatus.failed_hours.length > 5 ? '...' : ''}</p>
                  )}
                </div>
              )}

              {hours.length > 0 && (
                <div className="rounded-2xl bg-surface-lowest p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <Sparkles size={15} strokeWidth={1.8} className="text-primary" />
                    <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Hour timeline</p>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {hours.map((h) => (
                      <button
                        key={h.hour_index}
                        onClick={() => setSelectedHour(selectedHour === h.hour_index ? null : h.hour_index)}
                        className={`h-7 min-w-[28px] rounded-lg px-1.5 text-[10px] font-bold transition ${
                          selectedHour === h.hour_index
                            ? 'bg-primary text-on-primary'
                            : h.step_failed
                              ? 'bg-[#FFE8E8] text-[#8A1C1C] hover:bg-[#FFD0D0]'
                              : 'bg-surface-low text-on-surface-variant hover:bg-surface-high'
                        }`}
                      >
                        {h.hour_index}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {display && (
                <div className="rounded-2xl bg-surface-lowest p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Sparkles size={15} strokeWidth={1.8} className="text-primary" />
                      <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">
                        Hour {display.hour_index} — {display.observation.total_generation_mw.toFixed(0)} MW gen, {display.observation.total_load_mw.toFixed(0)} MW load
                      </p>
                    </div>
                    {display.step_failed && (
                      <span className="rounded-full bg-[#FFE8E8] px-2 py-0.5 text-[9px] font-bold uppercase text-[#8A1C1C]">
                        Operational reject
                      </span>
                    )}
                  </div>

                  <div className="mb-2 rounded-xl bg-surface-low px-3 py-2">
                    <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Prediction analysis</p>
                    <div className="mt-1.5 space-y-1 text-[11px] font-medium text-on-surface-variant">
                      <p>{balanceSummary(display)}</p>
                      <p>Frequency is {display.observation.system_frequency_hz.toFixed(3)} Hz.</p>
                      {securitySummary(display) && <p>{securitySummary(display)}</p>}
                      <p>{actionSummary(display)}</p>
                    </div>
                  </div>

                  {display.step_failed && firstRejectionReason(display) && (
                    <div className="mb-2 rounded-xl bg-[#FFE8E8] px-3 py-2">
                      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#8A1C1C]">Rejected prediction</p>
                      <p className="mt-1 text-[11px] font-medium text-[#8A1C1C]">{firstRejectionReason(display)}</p>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    {display.agent_outputs.map((agent: AgentOutput) => (
                      <div key={agent.agent_id} className="rounded-xl bg-surface-low px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] ${agentTone(agent.agent_id)}`}>
                            {agentName(agent.agent_id)}
                          </span>
                          {agent.has_action && <span className="rounded-full bg-[#E8F4EC] px-1.5 py-0.5 text-[8px] font-bold uppercase text-[#1E6F3A]">Action</span>}
                        </div>
                        <p className="mt-1 text-[11px] font-medium text-on-surface-variant line-clamp-2">{agent.reasoning}</p>
                      </div>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={() => setDetailsOpen(true)}
                    className="mt-2 w-full rounded-xl bg-primary px-3 py-2 text-[11px] font-bold uppercase tracking-[0.12em] text-on-primary transition hover:bg-primary-container focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    Show technical changes
                  </button>

                  {detailsOpen && (
                    <div className="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4 backdrop-blur-sm">
                      <div className="max-h-[82vh] w-full max-w-3xl overflow-hidden rounded-3xl bg-surface-lowest text-on-background shadow-[0_30px_90px_rgba(0,0,0,0.28)]">
                        <div className="flex items-start justify-between gap-3 border-b border-outline-variant/40 px-5 py-4">
                          <div>
                            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">Technical changes</p>
                            <h3 className="mt-1 font-display text-xl font-extrabold">Hour {display.hour_index} AI output</h3>
                          </div>
                          <button type="button" onClick={() => setDetailsOpen(false)} className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface-low text-on-surface-variant transition hover:bg-surface-high" aria-label="Close details">
                            <X size={16} />
                          </button>
                        </div>
                        <div className="max-h-[calc(82vh-80px)] space-y-3 overflow-y-auto p-5">
                          <div className="grid grid-cols-2 gap-2">
                            <div className="rounded-2xl bg-surface-low p-3">
                              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Grid totals</p>
                              <p className="mt-1 text-xs font-medium text-on-background">Generation {display.observation.total_generation_mw.toFixed(2)} MW</p>
                              <p className="text-xs font-medium text-on-background">Load {display.observation.total_load_mw.toFixed(2)} MW</p>
                              <p className="text-xs font-medium text-on-background">Imbalance {display.observation.imbalance_mw.toFixed(2)} MW</p>
                            </div>
                            <div className="rounded-2xl bg-surface-low p-3">
                              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Execution</p>
                              <p className="mt-1 text-xs font-medium text-on-background">Actions proposed: {display.actions_executed}</p>
                              <p className="text-xs font-medium text-on-background">Accepted actions: {display.actions_accepted}</p>
                              <p className="text-xs font-medium text-on-background">Status: {display.step_failed ? 'rejected' : 'accepted'}</p>
                            </div>
                          </div>

                          <div className="rounded-2xl bg-surface-low p-3">
                            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Agent reasoning</p>
                            <div className="mt-2 space-y-2">
                              {display.agent_outputs.map((agent) => (
                                <div key={agent.agent_id} className="rounded-xl bg-surface-lowest px-3 py-2">
                                  <div className="flex items-center gap-2">
                                    <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] ${agentTone(agent.agent_id)}`}>{agentName(agent.agent_id)}</span>
                                    {agent.has_action && <span className="rounded-full bg-[#E8F4EC] px-1.5 py-0.5 text-[8px] font-bold uppercase text-[#1E6F3A]">Changed grid</span>}
                                  </div>
                                  <p className="mt-1 text-xs leading-relaxed text-on-surface-variant">{agent.reasoning}</p>
                                </div>
                              ))}
                            </div>
                          </div>

                          {display.proposals.length > 0 && (
                            <div className="rounded-2xl bg-surface-low p-3">
                              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Proposed technical actions</p>
                              <pre className="mt-2 max-h-56 overflow-auto rounded-xl bg-[#111] p-3 text-[11px] leading-relaxed text-white">{JSON.stringify(display.proposals, null, 2)}</pre>
                            </div>
                          )}

                          {display.evaluation_results && display.evaluation_results.length > 0 && (
                            <div className="rounded-2xl bg-surface-low p-3">
                              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Validation results</p>
                              <pre className="mt-2 max-h-56 overflow-auto rounded-xl bg-[#111] p-3 text-[11px] leading-relaxed text-white">{JSON.stringify(display.evaluation_results, null, 2)}</pre>
                            </div>
                          )}

                          <div className="rounded-2xl bg-surface-low p-3">
                            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Raw prediction data</p>
                            <pre className="mt-2 max-h-72 overflow-auto rounded-xl bg-[#111] p-3 text-[11px] leading-relaxed text-white">{JSON.stringify(display, null, 2)}</pre>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {error && (
                <div className="flex items-center gap-2 rounded-2xl bg-[#FFE8E8] p-3">
                  <AlertTriangle size={15} className="shrink-0 text-[#8A1C1C]" />
                  <p className="text-xs font-medium text-[#8A1C1C]">{error}</p>
                  <button onClick={() => setError(null)} className="ml-auto shrink-0"><X size={14} className="text-[#8A1C1C]" /></button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
