import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, X } from 'lucide-react'
import type { GridElementType, GridSelection } from '../types/grid'

function rampColor(value: number, stops: Array<{ pct: number; r: number; g: number; b: number }>): string {
  let lower = stops[0]
  let upper = stops[stops.length - 1]
  for (let i = 0; i < stops.length - 1; i++) {
    if (value >= stops[i].pct && value <= stops[i + 1].pct) {
      lower = stops[i]
      upper = stops[i + 1]
      break
    }
  }
  if (lower.pct === upper.pct) return `rgb(${lower.r},${lower.g},${lower.b})`
  const t = (value - lower.pct) / (upper.pct - lower.pct)
  const r = Math.round(lower.r + (upper.r - lower.r) * t)
  const g = Math.round(lower.g + (upper.g - lower.g) * t)
  const b = Math.round(lower.b + (upper.b - lower.b) * t)
  return `rgb(${r},${g},${b})`
}

function loadingColor(loadingPercent: number): string {
  return rampColor(loadingPercent, [
    { pct: 0, r: 34, g: 197, b: 94 },   // #22C55E green
    { pct: 50, r: 234, g: 179, b: 8 }, // #EAB308 yellow
    { pct: 85, r: 239, g: 68, b: 68 },  // #EF4444 red
    { pct: 100, r: 153, g: 27, b: 27 }, // #991B1B dark red
  ])
}

type ActiveFilter = Extract<GridElementType, 'bus' | 'generator' | 'load' | 'branch'>

const FILTER_GROUPS: Array<{ type: ActiveFilter; label: string; short: string; color: string }> = [
  { type: 'bus', label: 'Bus', short: 'Bus', color: '#FF6B6B' },
  { type: 'generator', label: 'Generator', short: 'Gen', color: '#FFD93D' },
  { type: 'load', label: 'Load', short: 'Load', color: '#95E1D3' },
  { type: 'branch', label: 'Branch', short: 'Branch', color: '#22C55E' },
]

type PanelValue = string | number | boolean | null | undefined

interface MapDetailsPanelProps {
  selection: GridSelection | null
  onClose: () => void
  onReferenceSelect?: (referenceId: string) => void
  relatedSelections?: GridSelection[]
  onSelectionChange?: (selection: GridSelection) => void
}

interface MetricSpec {
  key: string
  label: string
  unit?: string
  kind?: 'bar' | 'plain' | 'chip'
  max?: number
}

interface RowSpec {
  key: string
  label: string
  unit?: string
  visual?: 'bar' | 'chip'
  max?: number
}

interface SectionSpec {
  title: string
  rows: RowSpec[]
}

const TYPE_LABELS: Record<GridSelection['type'], string> = {
  bus: 'Bus node',
  branch: 'Transmission branch',
  generator: 'Generator',
  load: 'Load point',
  cluster: 'Asset cluster',
}

const STATUS_FALSE = new Set<PanelValue>([false, 'no', 'No', 'false', 'False'])
const STATUS_TRUE = new Set<PanelValue>([true, 'yes', 'Yes', 'true', 'True'])

const METRICS: Record<GridSelection['type'], MetricSpec[]> = {
  branch: [
    { key: 'loading_percent', label: 'Utilization', unit: '%', kind: 'bar', max: 100 },
    { key: 'max_i_ka', label: 'Max current', unit: 'kA' },
    { key: 'line_length_km', label: 'Length', unit: 'km' },
  ],
  bus: [
    { key: 'vm_pu', label: 'Voltage', unit: 'pu', kind: 'bar', max: 1.2 },
    { key: 'voltage_kv', label: 'Rated voltage', unit: 'kV' },
    { key: 'connected_lines_count', label: 'Lines' },
  ],
  generator: [
    { key: 'installed_capacity_mw', label: 'Capacity', unit: 'MW' },
    { key: 'reserve_capable', label: 'Reserve', kind: 'chip' },
    { key: 'forced_outage_count_12m', label: 'Forced outages' },
  ],
  load: [
    { key: 'priority_class', label: 'Priority', kind: 'chip' },
    { key: 'customer_type', label: 'Customer' },
    { key: 'outage_count_12m', label: 'Outages' },
  ],
  cluster: [
    { key: 'node_count', label: 'Assets' },
    { key: 'installed_capacity_mw', label: 'Gen capacity', unit: 'MW' },
    { key: 'generator_count', label: 'Generators' },
  ],
}

const SECTIONS: Record<GridSelection['type'], SectionSpec[]> = {
  branch: [
    { title: 'Connection', rows: [
      { key: 'from_bus', label: 'From bus' },
      { key: 'to_bus', label: 'To bus' },
      { key: 'from_substation', label: 'From substation' },
      { key: 'to_substation', label: 'To substation' },
    ] },
    { title: 'Line facts', rows: [
      { key: 'voltage_kv', label: 'Voltage', unit: 'kV' },
      { key: 'line_type', label: 'Line type', visual: 'chip' },
      { key: 'conductor_type', label: 'Conductor' },
      { key: 'tower_count', label: 'Towers' },
      { key: 'circuit_count', label: 'Circuits' },
    ] },
    { title: 'Maintenance', rows: [
      { key: 'last_inspection_date', label: 'Last inspection' },
      { key: 'next_maintenance_date', label: 'Next maintenance' },
      { key: 'last_vegetation_clearance_date', label: 'Vegetation cleared' },
      { key: 'planned_outage_date', label: 'Planned outage' },
    ] },
    { title: 'History', rows: [
      { key: 'last_alarm_type', label: 'Last alarm', visual: 'chip' },
      { key: 'alarm_count_12m', label: 'Alarms 12m' },
      { key: 'outage_count_12m', label: 'Outages 12m' },
      { key: 'open_work_orders', label: 'Open work' },
    ] },
  ],
  bus: [
    { title: 'Connectivity', rows: [
      { key: 'substation_name', label: 'Substation' },
      { key: 'busbar_section', label: 'Busbar' },
      { key: 'connected_lines_count', label: 'Lines' },
      { key: 'connected_generators_count', label: 'Generators' },
      { key: 'connected_loads_count', label: 'Loads' },
    ] },
    { title: 'Voltage limits', rows: [
      { key: 'min_v_pu', label: 'Min voltage', unit: 'pu' },
      { key: 'max_v_pu', label: 'Max voltage', unit: 'pu' },
      { key: 'p_mw', label: 'Injection', unit: 'MW' },
    ] },
    { title: 'Maintenance', rows: [
      { key: 'last_inspection_date', label: 'Last inspection' },
      { key: 'last_protection_test_date', label: 'Protection test' },
      { key: 'next_maintenance_date', label: 'Next maintenance' },
    ] },
    { title: 'Operations', rows: [
      { key: 'scada_available', label: 'SCADA', visual: 'chip' },
      { key: 'remote_control_enabled', label: 'Remote control', visual: 'chip' },
      { key: 'last_alarm_type', label: 'Last alarm', visual: 'chip' },
      { key: 'open_work_orders', label: 'Open work' },
    ] },
  ],
  generator: [
    { title: 'Plant', rows: [
      { key: 'plant_name', label: 'Plant' },
      { key: 'unit_name', label: 'Unit' },
      { key: 'bus_name', label: 'Connected bus' },
      { key: 'technology_type', label: 'Technology', visual: 'chip' },
      { key: 'fuel_type', label: 'Fuel' },
    ] },
    { title: 'Capability', rows: [
      { key: 'min_output_mw', label: 'Min output', unit: 'MW' },
      { key: 'max_output_mw', label: 'Max output', unit: 'MW' },
      { key: 'black_start_capable', label: 'Black start', visual: 'chip' },
      { key: 'remote_dispatchable', label: 'Remote dispatch', visual: 'chip' },
    ] },
    { title: 'Maintenance', rows: [
      { key: 'last_major_overhaul_date', label: 'Major overhaul' },
      { key: 'next_maintenance_date', label: 'Next maintenance' },
      { key: 'planned_outage_date', label: 'Planned outage' },
    ] },
    { title: 'History', rows: [
      { key: 'last_alarm_type', label: 'Last alarm', visual: 'chip' },
      { key: 'alarm_count_12m', label: 'Alarms 12m' },
      { key: 'outage_count_12m', label: 'Outages 12m' },
      { key: 'open_work_orders', label: 'Open work' },
    ] },
  ],
  load: [
    { title: 'Demand point', rows: [
      { key: 'load_area_name', label: 'Area' },
      { key: 'bus_name', label: 'Connected bus' },
      { key: 'critical_infrastructure', label: 'Critical infra', visual: 'chip' },
      { key: 'backup_supply_available', label: 'Backup supply', visual: 'chip' },
    ] },
    { title: 'Flexibility', rows: [
      { key: 'interruptible', label: 'Interruptible', visual: 'chip' },
      { key: 'demand_response_capable', label: 'Demand response', visual: 'chip' },
    ] },
    { title: 'Maintenance', rows: [
      { key: 'last_inspection_date', label: 'Last inspection' },
      { key: 'next_maintenance_date', label: 'Next maintenance' },
      { key: 'planned_outage_date', label: 'Planned outage' },
    ] },
    { title: 'History', rows: [
      { key: 'last_alarm_type', label: 'Last alarm', visual: 'chip' },
      { key: 'alarm_count_12m', label: 'Alarms 12m' },
      { key: 'outage_count_12m', label: 'Outages 12m' },
      { key: 'open_work_orders', label: 'Open work' },
    ] },
  ],
  cluster: [
    { title: 'Cluster overview', rows: [
      { key: 'bus_name', label: 'Anchor bus' },
      { key: 'bus_count', label: 'Bus nodes' },
      { key: 'generator_count', label: 'Generators' },
      { key: 'load_count', label: 'Loads' },
    ] },
    { title: 'Power aggregate', rows: [
      { key: 'installed_capacity_mw', label: 'Installed generation', unit: 'MW' },
      { key: 'min_output_mw', label: 'Minimum output floor', unit: 'MW' },
      { key: 'reserve_capable_count', label: 'Reserve-capable units' },
    ] },
    { title: 'Demand aggregate', rows: [
      { key: 'load_count', label: 'Load points' },
      { key: 'critical_load_count', label: 'Critical loads' },
      { key: 'demand_response_count', label: 'Demand response' },
    ] },
    { title: 'Members', rows: [
      { key: 'generator_ids', label: 'Generator IDs' },
      { key: 'load_ids', label: 'Load IDs' },
    ] },
  ],
}

function getValue(selection: GridSelection, key: string): PanelValue {
  return selection.properties[key]
}

function hasValue(value: PanelValue): boolean {
  return value !== null && value !== undefined && value !== ''
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return 'N/A'
  if (Math.abs(value) >= 100) return value.toLocaleString(undefined, { maximumFractionDigits: 1 })
  if (Math.abs(value) >= 10) return value.toLocaleString(undefined, { maximumFractionDigits: 1 })
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 })
}

function formatValue(value: PanelValue, unit?: string, key?: string): string {
  if (!hasValue(value)) return 'N/A'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (key?.includes('year')) return String(value)
  if (typeof value === 'number') return `${formatNumber(value)}${unit ? ` ${unit}` : ''}`
  if (STATUS_TRUE.has(value)) return 'Yes'
  if (STATUS_FALSE.has(value)) return 'No'
  const text = String(value)
  return unit && /^-?\d+(\.\d+)?$/.test(text) ? `${formatNumber(Number(text))} ${unit}` : text
}

function numberValue(value: PanelValue): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) return Number(value)
  return null
}

function statusTone(value: PanelValue): string {
  if (STATUS_FALSE.has(value)) return 'bg-[#FCE8E6] text-[#9F2A1D]'
  if (String(value).toLowerCase() === 'critical') return 'bg-[#FCE8E6] text-[#9F2A1D]'
  if (String(value).toLowerCase() === 'important') return 'bg-[#FFF3D8] text-[#8A4B00]'
  return 'bg-[#E8F4EC] text-[#1E6F3A]'
}

function serviceLabel(value: PanelValue): string {
  if (STATUS_FALSE.has(value)) return 'Out of service'
  return 'In service'
}

function isReferenceValue(value: PanelValue): value is string {
  return typeof value === 'string' && /^(bus|branch|load|biomass|solar|wind|hydro|ror|gas|ccgt|coal|nuclear)_\d{3}(?:_\d{3})?(?:_\d+)?$/.test(value)
}

function coordinateValue(lat: PanelValue, lon: PanelValue): string | null {
  const latitude = numberValue(lat)
  const longitude = numberValue(lon)
  if (latitude === null || longitude === null) return null
  return `${formatNumber(latitude)}, ${formatNumber(longitude)}`
}

function dateDistance(value: PanelValue): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const target = new Date(`${value}T00:00:00`)
  const now = new Date('2025-01-15T00:00:00')
  const days = Math.round((target.getTime() - now.getTime()) / 86_400_000)
  if (Math.abs(days) < 45) return days >= 0 ? `${days}d away` : `${Math.abs(days)}d ago`
  const months = Math.round(Math.abs(days) / 30)
  return days >= 0 ? `${months}mo away` : `${months}mo ago`
}

function renderValue(value: PanelValue, spec: RowSpec, onReferenceSelect?: (referenceId: string) => void) {
  if (onReferenceSelect && isReferenceValue(value)) {
    return (
      <button
        type="button"
        onClick={() => onReferenceSelect(value)}
        className="min-w-0 justify-self-end rounded-lg bg-primary/5 px-2 py-1 text-right font-mono text-[13px] font-bold text-primary transition hover:bg-primary/10 focus:outline-none focus:ring-2 focus:ring-primary/20"
      >
        {value}
      </button>
    )
  }

  if (spec.visual === 'chip') {
    return <span className={`justify-self-end rounded-full px-2 py-1 text-[11px] font-bold uppercase tracking-[0.1em] ${statusTone(value)}`}>{formatValue(value, spec.unit)}</span>
  }

  return <span className="min-w-0 break-words text-right font-mono text-[13px] font-semibold text-on-background">{formatValue(value, spec.unit)}</span>
}

function MetricCard({ selection, spec, featured }: { selection: GridSelection; spec: MetricSpec; featured?: boolean }) {
  const value = getValue(selection, spec.key)
  const numeric = numberValue(value)
  const width = spec.kind === 'bar' && numeric !== null ? Math.max(4, Math.min(100, (numeric / (spec.max ?? 100)) * 100)) : null
  const barColor = spec.key === 'loading_percent' && numeric !== null ? loadingColor(numeric) : undefined

  return (
    <div className={`rounded-2xl bg-surface-lowest px-3.5 py-3 ${featured ? 'col-span-2' : ''}`}>
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-on-surface-variant">{spec.label}</p>
      {spec.kind === 'chip' && <span className={`mt-2 inline-flex max-w-full rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] ${statusTone(value)}`}>{formatValue(value)}</span>}
      {spec.kind !== 'chip' && (
        <p className="mt-1 break-words font-display text-xl font-extrabold leading-tight tracking-tight text-on-background">{formatValue(value, spec.unit, spec.key)}</p>
      )}
      {width !== null && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-high">
          <div className="h-full rounded-full bg-primary" style={{ width: `${width}%`, backgroundColor: barColor }} />
        </div>
      )}
    </div>
  )
}

function DatePill({ label, value }: { label: string; value: PanelValue }) {
  if (!hasValue(value)) return null
  return (
    <div className="rounded-xl bg-surface px-3 py-2">
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">{label}</p>
      <p className="mt-1 font-mono text-[13px] font-semibold text-on-background">{formatValue(value, undefined, label.toLowerCase() === 'built' ? 'commissioning_year' : undefined)}</p>
      {dateDistance(value) && <p className="mt-0.5 text-[11px] font-medium text-on-surface-variant">{dateDistance(value)}</p>}
    </div>
  )
}

function selectionChipLabel(selection: GridSelection): string {
  if (selection.type === 'cluster') return 'Cluster'
  if (selection.type === 'branch') return 'Branch'
  return formatValue(selection.title)
}

export function MapDetailsPanel({ selection, onClose, onReferenceSelect, relatedSelections = [], onSelectionChange }: MapDetailsPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>(() => {
    if (selection && selection.type !== 'cluster') return selection.type as ActiveFilter
    return 'bus'
  })

  const filteredItems = relatedSelections.filter((item) => item.type === activeFilter)
  const currentFilteredIndex = filteredItems.findIndex((item) => item.key === selection?.key)
  const hasPrev = currentFilteredIndex > 0
  const hasNext = currentFilteredIndex < filteredItems.length - 1
  const prevItem = hasPrev ? filteredItems[currentFilteredIndex - 1] : null
  const nextItem = hasNext ? filteredItems[currentFilteredIndex + 1] : null

  const selectionKeyRef = useRef(selection?.key)
  useEffect(() => {
    if (selectionKeyRef.current !== selection?.key) {
      selectionKeyRef.current = selection?.key
      setIsExpanded(false)
    }
  }, [selection?.key])

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
        return
      }
      event.preventDefault()
      event.stopPropagation()
      if (event.key === 'ArrowLeft' && prevItem && onSelectionChange) {
        onSelectionChange(prevItem)
      }
      if (event.key === 'ArrowRight' && nextItem && onSelectionChange) {
        onSelectionChange(nextItem)
      }
    }
    document.addEventListener('keydown', handleKeyDown, true)
    return () => document.removeEventListener('keydown', handleKeyDown, true)
  }, [onClose, prevItem, nextItem, onSelectionChange])

  if (!selection) return null

  // Sync filter when selection changes from outside (e.g., map click)
  if (selection.type !== 'cluster' && selection.type !== activeFilter) {
    setActiveFilter(selection.type as ActiveFilter)
  }

  const inService = getValue(selection, 'in_service')
  const displayName = getValue(selection, 'asset_name') ?? selection.title
  const operator = getValue(selection, 'operator')

  const totalRelated = relatedSelections.length

  const coordinates = selection.type === 'branch'
    ? [
        ['From', coordinateValue(getValue(selection, 'from_latitude'), getValue(selection, 'from_longitude'))],
        ['To', coordinateValue(getValue(selection, 'to_latitude'), getValue(selection, 'to_longitude'))],
      ].filter(([, value]) => value)
    : [['Coordinates', coordinateValue(getValue(selection, 'latitude') ?? getValue(selection, 'y_coordinate'), getValue(selection, 'longitude') ?? getValue(selection, 'x_coordinate'))]].filter(([, value]) => value)
  const sections = SECTIONS[selection.type]
    .map((section) => ({ ...section, rows: section.rows.filter((row) => hasValue(getValue(selection, row.key))) }))
    .filter((section) => section.rows.length > 0)

  return (
    <aside className="absolute bottom-24 right-5 top-5 z-30 flex w-[408px] flex-col overflow-hidden rounded-[1.35rem] bg-surface-lowest shadow-[0_24px_56px_rgba(28,27,27,0.16)] animate-[slideIn_220ms_ease-out]">
      <div className="bg-surface-low px-5 pb-4 pt-4">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: selection.color }} />
              <span className="text-[11px] font-semibold uppercase tracking-[0.22em] text-on-surface-variant">{TYPE_LABELS[selection.type]}</span>
              {hasValue(inService) && <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] ${statusTone(inService)}`}>{serviceLabel(inService)}</span>}
            </div>
            <h3 className="truncate font-display text-2xl font-extrabold tracking-[-0.03em] text-on-background">{formatValue(displayName)}</h3>
            <p className="mt-1 truncate text-sm font-medium text-on-surface-variant">{operator ? `${operator} · ${selection.subtitle}` : selection.subtitle}</p>
          </div>

          {totalRelated > 1 && onSelectionChange && (
            <div className="flex shrink-0 items-center gap-0.5">
              <button
                type="button"
                disabled={!hasPrev}
                onClick={() => prevItem && onSelectionChange(prevItem)}
                className={`grid h-8 w-8 place-items-center rounded-lg transition focus:outline-none focus:ring-2 focus:ring-primary/20 ${hasPrev ? 'hover:bg-surface-high text-on-background' : 'text-on-surface-variant/25 cursor-default'}`}
                aria-label="Previous"
              >
                <ChevronLeft size={18} strokeWidth={2} />
              </button>
              <button
                type="button"
                disabled={!hasNext}
                onClick={() => nextItem && onSelectionChange(nextItem)}
                className={`grid h-8 w-8 place-items-center rounded-lg transition focus:outline-none focus:ring-2 focus:ring-primary/20 ${hasNext ? 'hover:bg-surface-high text-on-background' : 'text-on-surface-variant/25 cursor-default'}`}
                aria-label="Next"
              >
                <ChevronRight size={18} strokeWidth={2} />
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={onClose}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-surface text-on-background transition hover:bg-surface-high focus:outline-none focus:ring-2 focus:ring-primary/20"
            aria-label="Close details panel"
          >
            <X size={19} strokeWidth={1.9} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {METRICS[selection.type].filter((metric) => hasValue(getValue(selection, metric.key))).map((metric, index) => (
            <MetricCard key={metric.key} selection={selection} spec={metric} featured={index === 0} />
          ))}
        </div>

        {relatedSelections.length > 1 && onSelectionChange && (
          <div className="mt-3 rounded-2xl bg-surface-lowest p-2">
            <div className="mb-1.5 flex items-center gap-2">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-on-surface-variant">Also here</p>
              <span className="rounded-full bg-surface-low px-2 py-0.5 text-[10px] font-bold text-on-surface-variant">{relatedSelections.length}</span>
            </div>

            {!isExpanded && (
              <>
                <div className="mb-2 flex flex-nowrap justify-between overflow-hidden">
                  {FILTER_GROUPS.map(({ type, short, color }) => {
                    const count = relatedSelections.filter((item) => item.type === type).length
                    if (count === 0) return null
                    const isActive = activeFilter === type
                    return (
                      <button
                        key={type}
                        type="button"
                        onClick={() => {
                          setActiveFilter(type)
                          const firstOfType = relatedSelections.find((item) => item.type === type)
                          if (firstOfType && firstOfType.key !== selection.key) {
                            onSelectionChange?.(firstOfType)
                          }
                        }}
                        className={`flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-[9px] font-bold uppercase tracking-[0.08em] transition ${isActive ? 'bg-primary text-white' : 'bg-surface-low text-on-surface-variant hover:bg-surface-high hover:text-on-background'}`}
                      >
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
                        <span>{short}</span>
                        <span className={`rounded-full px-1 py-0 text-[8px] font-bold tabular-nums leading-none ${isActive ? 'bg-white/20' : 'bg-surface-lowest'}`}>{count}</span>
                      </button>
                    )
                  })}
                </div>
                <button
                  type="button"
                  onClick={() => setIsExpanded(true)}
                  className="flex w-full items-center justify-center rounded-xl py-1 transition hover:bg-surface-low focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <ChevronDown size={14} strokeWidth={2} className="text-on-surface-variant" />
                </button>
              </>
            )}

            {isExpanded && (
              <>
                <div className="mb-2 max-h-[280px] space-y-3 overflow-y-auto pr-1">
                  {(['cluster', 'bus', 'generator', 'load', 'branch'] as const)
                    .map((type) => {
                      const items = relatedSelections
                        .filter((item) => item.type === type)
                        .sort((a, b) => a.title.localeCompare(b.title))
                      if (items.length === 0) return null
                      return (
                        <div key={type}>
                          <div className="mb-1.5 flex items-center gap-1.5">
                            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: items[0].color }} />
                            <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">{TYPE_LABELS[type]}</span>
                            <span className="rounded-full bg-surface-low px-1.5 py-0.5 text-[9px] font-bold tabular-nums text-on-surface-variant">{items.length}</span>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {items.map((item) => (
                              <button
                                key={item.key}
                                type="button"
                                onClick={() => {
                                  onSelectionChange(item)
                                  setIsExpanded(false)
                                }}
                                title={`${TYPE_LABELS[item.type]} · ${item.title}`}
                                className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.1em] transition ${item.key === selection.key ? 'bg-primary text-white' : 'bg-surface-low text-on-surface-variant hover:bg-surface-high hover:text-on-background'}`}
                              >
                                {selectionChipLabel(item)}
                              </button>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                </div>
                <button
                  type="button"
                  onClick={() => setIsExpanded(false)}
                  className="flex w-full items-center justify-center rounded-xl py-1 transition hover:bg-surface-low focus:outline-none focus:ring-2 focus:ring-primary/20"
                  aria-label="Collapse"
                >
                  <ChevronUp size={14} strokeWidth={2} className="text-on-surface-variant" />
                </button>
              </>
            )}
          </div>
        )}
      </div>

      <div className="overflow-y-auto bg-surface-lowest px-5 py-4">
        <div className="space-y-5">
          <section>
            <h4 className="mb-2 text-[10px] font-bold uppercase tracking-[0.24em] text-on-surface-variant">Lifecycle</h4>
            <div className="grid grid-cols-3 gap-2">
              <DatePill label="Built" value={getValue(selection, 'commissioning_year')} />
              <DatePill label="Inspect" value={getValue(selection, 'last_inspection_date')} />
              <DatePill label="Maintain" value={getValue(selection, 'next_maintenance_date')} />
            </div>
          </section>

          {sections.map((section) => (
            <section key={section.title}>
              <h4 className="mb-2 text-[10px] font-bold uppercase tracking-[0.24em] text-on-surface-variant">{section.title}</h4>
              <div className="space-y-1.5 rounded-2xl bg-surface-low p-1.5">
                {section.rows.map((row) => (
                  <div key={row.key} className="grid grid-cols-[minmax(112px,0.72fr)_1fr] items-center gap-3 rounded-xl bg-surface-lowest px-3 py-2.5">
                    <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-on-surface-variant">{row.label}</span>
                    {renderValue(getValue(selection, row.key), row, onReferenceSelect)}
                  </div>
                ))}
              </div>
            </section>
          ))}

          {coordinates.length > 0 && (
            <section>
              <h4 className="mb-2 text-[10px] font-bold uppercase tracking-[0.24em] text-on-surface-variant">Position</h4>
              <div className="grid grid-cols-2 gap-2">
                {coordinates.map(([label, value]) => (
                  <div key={label} className="rounded-xl bg-surface-low px-3 py-2">
                    <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-on-surface-variant">{label}</p>
                    <p className="mt-1 font-mono text-[12px] font-semibold text-on-background">{value}</p>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </aside>
  )
}
