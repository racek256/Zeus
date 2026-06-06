import { useState } from 'react'
import { ChevronLeft, ChevronRight, Filter } from 'lucide-react'
import type { GridElementType } from '../types/grid'

export type NodeFilterType = Extract<GridElementType, 'bus' | 'generator' | 'load' | 'cluster'>

const FILTERS: Array<{ type: NodeFilterType; label: string; color: string; hint: string }> = [
  { type: 'cluster', label: 'Cluster', color: '#8B5CF6', hint: 'Grouped colocated assets' },
  { type: 'bus', label: 'Bus', color: '#FF6B6B', hint: 'Grid connection nodes' },
  { type: 'generator', label: 'Generator', color: '#FFD93D', hint: 'Production units' },
  { type: 'load', label: 'Load', color: '#95E1D3', hint: 'Demand points' },
]

interface NodeTypeFilterProps {
  enabledTypes: Record<NodeFilterType, boolean>
  onChange: (type: NodeFilterType, enabled: boolean) => void
}

export function NodeTypeFilter({ enabledTypes, onChange }: NodeTypeFilterProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const activeCount = FILTERS.filter(({ type }) => enabledTypes[type]).length

  return (
    <section
      className="absolute bottom-6 left-6 z-10 flex items-stretch gap-2 rounded-lg bg-[#FCF9F8]/92 p-2 text-[#1C1B1B] shadow-[0_20px_40px_rgba(28,27,27,0.16)] backdrop-blur-[20px]"
      aria-label="Node layer filters"
    >
      <div className="flex w-[104px] items-center gap-2 rounded-md bg-[#EBE7E7]/90 px-3 py-2">
        <Filter size={16} strokeWidth={1.8} className="shrink-0 text-[#1E40AF]" />
        <div className="min-w-0">
          <p className="text-[9px] font-bold uppercase tracking-[0.19em] text-[#1C1B1B]/48">Layers</p>
          <p className="text-[13px] font-semibold tabular-nums leading-tight text-[#1C1B1B]">{activeCount}/{FILTERS.length}</p>
        </div>
      </div>

      <div
        className={`flex items-center gap-1.5 overflow-hidden transition-all duration-300 ease-out ${isExpanded ? 'max-w-[400px] opacity-100' : 'max-w-0 opacity-0'}`}
      >
        {FILTERS.map(({ type, label, color, hint }) => {
          const enabled = enabledTypes[type]
          return (
            <button
              key={type}
              type="button"
              onClick={() => onChange(type, !enabled)}
              aria-pressed={enabled}
              className={`shrink-0 flex h-9 items-center gap-2 rounded-full px-3 text-[11px] font-bold uppercase tracking-[0.08em] transition duration-200 ease-out focus:outline-none focus:ring-2 focus:ring-[#1E40AF]/20 ${
                enabled
                  ? 'bg-[#1C1B1B] text-[#FCF9F8] shadow-[0_8px_18px_rgba(28,27,27,0.18)]'
                  : 'bg-[#F6F3F2] text-[#1C1B1B]/50 hover:bg-[#EBE7E7] hover:text-[#1C1B1B]/80'
              }`}
              title={`${enabled ? 'Hide' : 'Show'} ${label}: ${hint}`}
            >
              <span
                className={`h-2 w-2 rounded-full ${enabled ? 'opacity-100' : 'opacity-40'}`}
                style={{ backgroundColor: color }}
              />
              <span className="whitespace-nowrap leading-none">{label}</span>
            </button>
          )
        })}
      </div>

      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="flex w-6 items-center justify-center rounded-md transition hover:bg-[#EBE7E7]/80 focus:outline-none focus:ring-2 focus:ring-[#1E40AF]/20"
        aria-label={isExpanded ? 'Collapse filters' : 'Expand filters'}
      >
        {isExpanded ? (
          <ChevronLeft size={14} strokeWidth={2} className="text-[#1C1B1B]/50" />
        ) : (
          <ChevronRight size={14} strokeWidth={2} className="text-[#1C1B1B]/50" />
        )}
      </button>
    </section>
  )
}
