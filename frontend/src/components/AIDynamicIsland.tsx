import { useState } from 'react'
import { Check, ChevronDown, ChevronUp, CircleAlert, FlaskConical, MessageSquare, Pencil, Send, ShieldCheck, Sparkles } from 'lucide-react'

type AgentPhase = 'reasoning' | 'simulation' | 'rejected' | 'accepted'

const phases: Array<{ phase: AgentPhase; label: string; detail: string }> = [
  { phase: 'reasoning', label: 'Reasoning', detail: 'Balancing N-1 risk against redispatch cost' },
  { phase: 'simulation', label: 'Simulating', detail: 'Running AC load-flow validation across the grid' },
  { phase: 'rejected', label: 'Rejected', detail: 'Discarded 2 candidates due to transformer overload' },
  { phase: 'accepted', label: 'Candidate ready', detail: 'Awaiting operator review before application' },
]

const suggestions = [
  { id: 's1', label: 'Reduce biomass_022 output', value: '0.31', unit: 'MW', impact: '-4.2% line loading' },
  { id: 's2', label: 'Increase reserve on bus_103', value: '1.8', unit: 'MW', impact: '+0.7 MW reserve' },
  { id: 's3', label: 'Shift load_018 response', value: '12', unit: 'min', impact: '-1 rejected contingency' },
]

function phaseTone(phase: AgentPhase): string {
  if (phase === 'rejected') return 'bg-[#FFF3D8] text-[#8A4B00]'
  if (phase === 'accepted') return 'bg-[#E8F4EC] text-[#1E6F3A]'
  if (phase === 'simulation') return 'bg-primary/10 text-primary'
  return 'bg-surface-high text-on-background'
}

export function AIDynamicIsland() {
  const [expanded, setExpanded] = useState(false)
  const [activePhase] = useState<AgentPhase>('simulation')
  const [drafts, setDrafts] = useState(() => Object.fromEntries(suggestions.map((item) => [item.id, item.value])))
  const active = phases.find((phase) => phase.phase === activePhase) ?? phases[0]

  return (
    <div className="absolute bottom-6 left-1/2 z-20 -translate-x-1/2">
      <div className={`overflow-hidden rounded-[1.35rem] bg-surface-lowest/95 text-on-background shadow-[0_24px_56px_rgba(28,27,27,0.16)] backdrop-blur-[20px] transition-all duration-300 ease-out ${expanded ? 'w-[620px]' : 'w-[430px]'}`}>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="flex w-full items-center gap-3 bg-surface-low px-4 py-3 text-left transition hover:bg-surface-high focus:outline-none focus:ring-2 focus:ring-primary/20"
        >
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-primary text-on-primary">
            <Sparkles size={18} strokeWidth={1.9} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-[11px] font-bold uppercase tracking-[0.2em] text-on-surface-variant">Athena</p>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em] ${phaseTone(active.phase)}`}>{active.label}</span>
            </div>
            <p className="mt-1 truncate text-sm font-semibold text-on-background">{active.detail}</p>
          </div>
          <div className="hidden min-w-[86px] text-right sm:block">
            <p className="font-display text-xl font-extrabold leading-none text-on-background">64%</p>
            <p className="mt-1 text-[9px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">Validated</p>
          </div>
          {expanded ? <ChevronDown size={17} strokeWidth={2} className="text-on-surface-variant" /> : <ChevronUp size={17} strokeWidth={2} className="text-on-surface-variant" />}
        </button>

        {expanded && (
          <div className="grid grid-cols-[1fr_260px] gap-3 bg-surface-low px-4 pb-4">
            <div className="space-y-3">
              <div className="rounded-2xl bg-surface-lowest p-3">
                <div className="mb-2 flex items-center gap-2">
                  <FlaskConical size={15} strokeWidth={1.8} className="text-primary" />
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Live agent trace</p>
                </div>
                <div className="space-y-1.5">
                  {phases.map((phase) => (
                    <div key={phase.phase} className="rounded-xl bg-surface-low px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] ${phaseTone(phase.phase)}`}>{phase.label}</span>
                        {phase.phase === activePhase && <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />}
                      </div>
                      <p className="mt-1 text-xs font-medium text-on-surface-variant">{phase.detail}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl bg-surface-lowest p-3">
                <div className="mb-2 flex items-center gap-2">
                  <ShieldCheck size={15} strokeWidth={1.8} className="text-primary" />
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Operator-editable proposal</p>
                </div>
                <div className="space-y-2">
                  {suggestions.map((item) => (
                    <div key={item.id} className="grid grid-cols-[1fr_92px] items-center gap-2 rounded-xl bg-surface-low px-3 py-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-bold text-on-background">{item.label}</p>
                        <p className="mt-0.5 text-[11px] font-semibold text-on-surface-variant">{item.impact}</p>
                      </div>
                      <label className="flex items-center gap-1 rounded-xl bg-surface-lowest px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary/20">
                        <Pencil size={11} strokeWidth={1.8} className="text-on-surface-variant" />
                        <input
                          value={drafts[item.id]}
                          onChange={(event) => setDrafts((current) => ({ ...current, [item.id]: event.target.value }))}
                          className="w-8 bg-transparent text-right text-xs font-bold text-on-background focus:outline-none"
                        />
                        <span className="text-[10px] font-bold text-on-surface-variant">{item.unit}</span>
                      </label>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <button className="flex h-9 flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-3 text-xs font-bold text-on-primary transition hover:bg-primary-container focus:outline-none focus:ring-2 focus:ring-primary/20">
                    <Check size={14} strokeWidth={2} />
                    Confirm proposal
                  </button>
                  <button className="grid h-9 w-9 place-items-center rounded-xl bg-surface-high text-on-background transition hover:bg-surface-highest focus:outline-none focus:ring-2 focus:ring-primary/20" aria-label="Reject proposal">
                    <CircleAlert size={15} strokeWidth={1.9} />
                  </button>
                </div>
              </div>
            </div>

            <div className="flex min-h-[420px] flex-col rounded-2xl bg-surface-lowest p-3">
              <div className="mb-3 flex items-center gap-2">
                <MessageSquare size={15} strokeWidth={1.8} className="text-primary" />
                <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Ask for evidence</p>
              </div>
              <div className="flex-1 space-y-2 overflow-y-auto">
                <div className="rounded-2xl bg-surface-low px-3 py-2 text-xs leading-relaxed text-on-background">Candidate reduces overload risk on the north-east corridor while preserving reserve margin.</div>
                <div className="ml-7 rounded-2xl bg-primary px-3 py-2 text-xs leading-relaxed text-on-primary">Show rejected simulations and sources.</div>
                <div className="rounded-2xl bg-surface-low px-3 py-2 text-xs leading-relaxed text-on-background">2 candidates rejected: one overloaded branch_044, one violated bus_103 voltage band.</div>
              </div>
              <div className="mt-3 flex items-end gap-2 rounded-2xl bg-surface-low px-2.5 py-2 focus-within:ring-2 focus-within:ring-primary/20">
                <textarea rows={1} placeholder="Ask before approving..." className="min-h-7 flex-1 resize-none bg-transparent text-xs text-on-background placeholder:text-on-surface-variant/55 focus:outline-none" />
                <button className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-primary text-on-primary transition hover:bg-primary-container focus:outline-none focus:ring-2 focus:ring-primary/20" aria-label="Send message">
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
