import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Loader2,
  MessageSquare,
  Play,
  Send,
  ShieldCheck,
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
  sendChat,
} from '../api/copilot'
import type {
  CopilotStatus,
  SimulationStatus,
  SimulationHourResult,
  AgentOutput,
  ChatMessage,
} from '../types/copilot'

type Phase = 'idle' | 'initialising' | 'running' | 'completed' | 'error'

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

function actionSummary(action: { generator_setpoint_changes: unknown[]; redispatch_requests: unknown[]; load_shedding_flags: unknown[]; interconnect_flow_adjustments: unknown[] }): string {
  const parts: string[] = []
  if (action.generator_setpoint_changes.length > 0) parts.push(`${action.generator_setpoint_changes.length} setpoint`)
  if (action.redispatch_requests.length > 0) parts.push(`${action.redispatch_requests.length} redispatch`)
  if (action.load_shedding_flags.length > 0) parts.push(`${action.load_shedding_flags.length} shed`)
  if (action.interconnect_flow_adjustments.length > 0) parts.push(`${action.interconnect_flow_adjustments.length} interconnect`)
  return parts.length > 0 ? parts.join(', ') : 'Monitoring'
}

export function AIDynamicIsland() {
  const [expanded, setExpanded] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [status, setStatus] = useState<CopilotStatus | null>(null)
  const [simStatus, setSimStatus] = useState<SimulationStatus | null>(null)
  const [hours, setHours] = useState<SimulationHourResult[]>([])
  const [selectedHour, setSelectedHour] = useState<number | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

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

  const handleStartSim = useCallback(async () => {
    setPhase('running')
    setError(null)
    setHours([])
    setSelectedHour(null)
    try {
      await startSimulation({ start_hour: 0, end_hour: 24, stop_on_failure: false })
      pollSimulation()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start')
      setPhase('error')
    }
  }, [pollSimulation])

  const handleStop = useCallback(() => {
    stopPolling()
    setPhase('idle')
  }, [stopPolling])

  const handleChat = useCallback(async () => {
    const msg = chatInput.trim()
    if (!msg || chatLoading) return
    setChatLoading(true)
    setChatInput('')
    try {
      const result = await sendChat(msg)
      setChatMessages(result.chat_history)
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: 'athena', content: 'Failed to reach copilot.', timestamp: new Date().toISOString() },
      ])
    } finally {
      setChatLoading(false)
    }
  }, [chatInput, chatLoading])

  useEffect(() => () => stopPolling(), [stopPolling])

  const latestHour = hours.length > 0 ? hours[hours.length - 1] : null
  const selected = selectedHour !== null ? hours.find((h) => h.hour_index === selectedHour) ?? null : null
  const display = selected ?? latestHour
  const progress = simStatus ? (simStatus.completed_hours / simStatus.total_hours) * 100 : 0

  return (
    <div className="absolute bottom-6 left-1/2 z-20 -translate-x-1/2">
      <div className={`overflow-hidden rounded-[1.35rem] bg-surface-lowest/95 text-on-background shadow-[0_24px_56px_rgba(28,27,27,0.16)] backdrop-blur-[20px] transition-all duration-300 ease-out ${expanded ? 'w-[620px]' : 'w-[430px]'}`}>
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
                    ? `Starting simulation — agents generating...`
                    : `Hour ${simStatus.current_hour}/${simStatus.end_hour} — ${simStatus.completed_hours} done (${Math.round(progress)}%)`
                  : phase === 'completed' && simStatus
                    ? `${simStatus.completed_hours} hours — ${simStatus.replay_coverage_percent}% coverage`
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
          <div className="grid grid-cols-[1fr_260px] gap-3 bg-surface-low px-4 pb-4">
            <div className="space-y-3">
              <div className="flex gap-2">
                {phase !== 'running' ? (
                  <button onClick={status?.initialised ? handleStartSim : handleInit} className="flex h-9 items-center gap-2 rounded-xl bg-primary px-3 text-xs font-bold text-on-primary transition hover:bg-primary-container focus:outline-none focus:ring-2 focus:ring-primary/20">
                    {phase === 'initialising' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} strokeWidth={2} />}
                    {status?.initialised ? 'Run 24h simulation' : 'Init copilot'}
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
                  {simStatus.completed_hours === 0 && (
                    <div className="mt-2 flex items-center gap-2">
                      <Loader2 size={12} className="animate-spin text-primary" />
                      <p className="text-[11px] text-on-surface-variant">Agents analyzing grid state...</p>
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
                  {simStatus.n1_failed_hours.length > 0 && (
                    <p className="mt-1.5 text-[11px] font-medium text-[#8A4B00]">{simStatus.n1_failed_hours.length} N-1 violations: {simStatus.n1_failed_hours.slice(0, 5).join(', ')}{simStatus.n1_failed_hours.length > 5 ? '...' : ''}</p>
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
                              : h.n1_failed
                                ? 'bg-[#FFF3D8] text-[#8A4B00] hover:bg-[#FFE6A8]'
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
                    {display.n1_passed !== null && (
                      <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${display.n1_passed ? 'bg-[#E8F4EC] text-[#1E6F3A]' : 'bg-[#FFE8E8] text-[#8A1C1C]'}`}>
                        N-1 {display.n1_passed ? 'Pass' : 'Fail'}
                      </span>
                    )}
                  </div>

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

                  {display.n1_detail && !display.n1_detail.passed && display.n1_detail.violated_contingencies.length > 0 && (
                    <div className="mt-2 rounded-xl bg-[#FFE8E8] px-3 py-2">
                      <p className="text-[10px] font-bold uppercase text-[#8A1C1C]">N-1 violations</p>
                      {display.n1_detail.violated_contingencies.slice(0, 3).map((v, i) => (
                        <p key={i} className="text-[11px] font-medium text-[#8A1C1C]">{v.element}: {v.status}</p>
                      ))}
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

            <div className="flex min-h-[420px] flex-col rounded-2xl bg-surface-lowest p-3">
              <div className="mb-3 flex items-center gap-2">
                <MessageSquare size={15} strokeWidth={1.8} className="text-primary" />
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Ask for evidence</p>
              </div>
              <div className="flex-1 space-y-2 overflow-y-auto">
                {chatMessages.length === 0 && (
                  <div className="rounded-2xl bg-surface-low px-3 py-2 text-xs leading-relaxed text-on-surface-variant">
                    Ask about the simulation, N-1 security, failed hours, or grid state.
                  </div>
                )}
                {chatMessages.map((msg, i) => (
                  <div key={i} className={`rounded-2xl px-3 py-2 text-xs leading-relaxed ${msg.role === 'operator' ? 'ml-7 bg-primary text-on-primary' : 'bg-surface-low text-on-background'}`}>
                    {msg.content}
                  </div>
                ))}
                {chatLoading && (
                  <div className="flex items-center gap-2 rounded-2xl bg-surface-low px-3 py-2">
                    <Loader2 size={12} className="animate-spin text-primary" />
                    <span className="text-[11px] text-on-surface-variant">Thinking...</span>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
              <div className="mt-3 flex items-end gap-2 rounded-2xl bg-surface-low px-2.5 py-2 focus-within:ring-2 focus-within:ring-primary/20">
                <textarea
                  rows={1}
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChat() } }}
                  placeholder="Ask about the simulation..."
                  className="min-h-7 flex-1 resize-none bg-transparent text-xs text-on-background placeholder:text-on-surface-variant/55 focus:outline-none"
                />
                <button onClick={handleChat} disabled={!chatInput.trim() || chatLoading} className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-primary text-on-primary transition hover:bg-primary-container focus:outline-none focus:ring-2 focus:ring-primary/20 disabled:opacity-50" aria-label="Send">
                  <Send size={14} strokeWidth={2} />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
