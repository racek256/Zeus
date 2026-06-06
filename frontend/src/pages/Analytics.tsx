import { useEffect, useRef, useState } from 'react'
import Plotly from 'plotly.js-dist'
import { getAnalyticsOverview, getAnalyticsTimeseries, getAnalyticsAlarms } from '../api/analytics'
import type { OverviewData, TimeseriesData, AlarmsData } from '../api/analytics'

type PlotTrace = Record<string, unknown>
type PlotLayout = Record<string, unknown>
type PlotConfig = Record<string, unknown>

interface PlotFigureProps {
  data: PlotTrace[]
  layout: PlotLayout
  config?: PlotConfig
}

function PlotFigure({ data, layout, config }: PlotFigureProps) {
  const nodeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!nodeRef.current) return

    const node = nodeRef.current
    let cancelled = false
    void Plotly.react(node, data, layout, {
      displayModeBar: false,
      scrollZoom: false,
      doubleClick: false,
      responsive: true,
      ...config,
    }).then(() => {
      if (!cancelled) Plotly.Plots.resize(node)
    })

    return () => { cancelled = true }
  }, [data, layout, config])

  useEffect(() => {
    const node = nodeRef.current
    if (!node) return
    const observer = new ResizeObserver(() => Plotly.Plots.resize(node))
    observer.observe(node)
    return () => {
      observer.disconnect()
      Plotly.purge(node)
    }
  }, [])

  return <div ref={nodeRef} className="h-full w-full" />
}

const surfaceHigh = '#EBE7E7'
const text = '#1C1B1B'
const muted = '#6B6B6B'
const primary = '#00288E'
const primarySoft = '#1E40AF'
const normal = '#4CAF50'
const alert = '#FF9800'
const alarm = '#FF5722'
const critical = '#F44336'

const baseLayout = {
  paper_bgcolor: 'transparent',
  plot_bgcolor: 'transparent',
  font: { family: 'Inter, system-ui, sans-serif', color: text, size: 12 },
  margin: { t: 18, r: 20, b: 38, l: 48 },
  hovermode: 'closest',
  hoverdistance: -1,
  spikedistance: -1,
  xaxis: {
    gridcolor: surfaceHigh,
    zeroline: false,
    tickfont: { color: muted, size: 11 },
  },
  yaxis: {
    gridcolor: surfaceHigh,
    zeroline: false,
    automargin: true,
    tickfont: { color: muted, size: 11 },
  },
  dragmode: false,
}

function loadingColor(value: number): string {
  if (value >= 95) return critical
  if (value >= 85) return alarm
  if (value >= 70) return alert
  return normal
}

function safetyStateColor(state: string): string {
  switch (state) {
    case 'Normal': return normal
    case 'Elevated': return alert
    case 'Tightening': return alarm
    case 'Critical': return critical
    default: return muted
  }
}

function safetyStateDescription(state: string): string {
  switch (state) {
    case 'Normal': return 'all margins comfortable'
    case 'Elevated': return 'some constraints active'
    case 'Tightening': return 'line + reserve constrained'
    case 'Critical': return 'emergency actions required'
    default: return 'unknown'
  }
}

function numberSeries(values: number[]): number[] {
  return values.map((value) => Number(value))
}

export function Analytics() {
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [timeseries, setTimeseries] = useState<TimeseriesData | null>(null)
  const [alarms, setAlarms] = useState<AlarmsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function fetchData() {
      try {
        const [ov, ts, al] = await Promise.all([
          getAnalyticsOverview(),
          getAnalyticsTimeseries(24),
          getAnalyticsAlarms(),
        ])
        if (!cancelled) {
          setOverview(ov)
          setTimeseries(ts)
          setAlarms(al)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load analytics')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div className="h-full overflow-auto bg-surface px-7 py-6 text-on-background flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="font-body text-sm text-on-background">Loading analytics...</span>
        </div>
      </div>
    )
  }

  if (error || !overview || !timeseries || !alarms) {
    return (
      <div className="h-full overflow-auto bg-surface px-7 py-6 text-on-background flex items-center justify-center">
        <div className="rounded-xl bg-surface-low px-6 py-4">
          <p className="text-sm text-on-background">{error || 'No data available'}</p>
          <p className="mt-1 text-xs text-on-surface-variant">Ensure the backend is running on port 8000</p>
        </div>
      </div>
    )
  }

  const hours = timeseries.hours
  const nextHours = Array.from({ length: hours.length }, (_, i) => `+${i + 1}h`)
  const chartHours = [...hours, ...nextHours]

  const loadActual = numberSeries(timeseries.load_actual)
  const generationActual = numberSeries(timeseries.generation_actual)
  const balanceActual = numberSeries(timeseries.balance_actual)
  const emptyPredictionWindow = Array.from<null>({ length: nextHours.length }).fill(null)
  const loadChart = [...loadActual, ...emptyPredictionWindow]

  const currentLoad = Number(overview.consumption_now)
  const currentGeneration = Number(overview.production_now)
  const currentImbalance = Number(overview.net_imbalance)
  const currentRatio = Number(overview.prod_cons_ratio).toFixed(2)
  const safetyState = overview.safety_state

  const cards = [
    { label: 'Consumption now', value: `${currentLoad.toLocaleString()} MW`, state: 'live demand', color: text },
    { label: 'Production now', value: `${currentGeneration.toLocaleString()} MW`, state: 'available supply', color: primarySoft },
    { label: 'Prod / cons ratio', value: `${currentRatio}x`, state: currentRatio >= '1.00' ? 'covered' : 'deficit pressure', color: currentImbalance >= 0 ? normal : alarm },
    { label: 'Net imbalance', value: `${currentImbalance > 0 ? '+' : ''}${currentImbalance} MW`, state: 'dispatch action window', color: currentImbalance >= 0 ? normal : critical },
    { label: 'Safety state', value: safetyState, state: safetyStateDescription(safetyState), color: safetyStateColor(safetyState) },
  ]

  const safetyWatchlist = [...timeseries.safety_watchlist].sort((a, b) => b.max_loading - a.max_loading)
  const corridors = safetyWatchlist.map((s) => s.corridor).reverse()
  const lineLoading = safetyWatchlist.map((s) => Number(s.max_loading)).reverse()
  const lineColors = lineLoading.map(loadingColor)
  const safetyAxisMax = Math.max(20, Math.ceil((Math.max(...lineLoading, 0) * 1.35) / 5) * 5)

  const reserveTypes = timeseries.reserve_types
  const reserveUsed = numberSeries(timeseries.reserve_used)
  const reserveAvailable = numberSeries(timeseries.reserve_available)
  const reserveAxisMax = Math.max(100, Math.ceil((Math.max(...reserveAvailable, ...reserveUsed, 0) * 1.15) / 500) * 500)

  const alarmQueue = [
    { priority: 'P1', count: alarms.P1, label: 'N-1 breach risk', color: critical },
    { priority: 'P2', count: alarms.P2, label: 'Line utilization high', color: alarm },
    { priority: 'P3', count: alarms.P3, label: 'Voltage drift', color: alert },
    { priority: 'Info', count: alarms.Info, label: 'Routine state changes', color: muted },
  ]

  return (
    <div className="h-full overflow-auto bg-surface px-7 py-6 text-on-background">
      <div className="mb-5 grid grid-cols-[minmax(300px,1fr)_auto] items-end gap-8">
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-on-surface-variant">
            Operator overview
          </p>
          <h2 className="font-display text-4xl font-extrabold tracking-[-0.02em] text-on-background">
            Grid Analytics
          </h2>
        </div>
        <div className="rounded-xl bg-surface-low px-4 py-3 text-right">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-on-surface-variant">Snapshot</p>
          <p className="mt-1 text-sm font-semibold text-on-background">Live model, 5 sec cadence</p>
        </div>
      </div>

      <div className="mb-5 grid grid-cols-5 gap-3">
        {cards.map(({ label, value, state, color }) => (
          <div key={label} className="rounded-xl bg-surface-low p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-on-surface-variant">{label}</p>
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
            </div>
            <p className="font-display text-2xl font-bold tracking-tight text-on-background">{value}</p>
            <p className="mt-1 text-xs font-medium text-on-surface-variant">{state}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-12 gap-3">
        <section className="col-span-8 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Load forecast — TimesFM target</h3>
            <p className="text-xs text-on-surface-variant">Predict only demand; future API window is intentionally empty</p>
          </div>
          <div className="h-[255px]">
            <PlotFigure
              data={[
                {
                  x: chartHours,
                  y: loadChart,
                  type: 'scatter',
                  mode: 'lines',
                  name: 'actual load',
                  line: { color: text, width: 3, shape: 'spline' },
                  fill: 'tozeroy',
                  fillcolor: 'rgba(0, 40, 142, 0.08)',
                  hovertemplate: '%{x}<br>%{y:.0f} MW load<extra></extra>',
                },
              ]}
              layout={{
                ...baseLayout,
                hovermode: 'x unified',
                margin: { t: 12, r: 18, b: 40, l: 58 },
                xaxis: {
                  ...baseLayout.xaxis,
                  type: 'category',
                  categoryorder: 'array',
                  categoryarray: chartHours,
                  range: [-0.5, chartHours.length - 0.5],
                  showspikes: true,
                  spikemode: 'across',
                  spikesnap: 'cursor',
                  spikedistance: -1,
                  spikecolor: '#6B6B6B',
                  spikethickness: 1,
                  spikedash: 'dot',
                },
                yaxis: { ...baseLayout.yaxis, type: 'linear', title: { text: 'MW' }, showspikes: false },
                shapes: [
                  { type: 'rect', xref: 'paper', yref: 'paper', x0: 0.5, x1: 1, y0: 0, y1: 1, fillcolor: primary, opacity: 0.05, line: { width: 0 } },
                  { type: 'line', xref: 'paper', yref: 'paper', x0: 0.5, x1: 0.5, y0: 0, y1: 1, line: { color: muted, width: 1, dash: 'dash' } },
                ],
                annotations: [
                  { xref: 'paper', yref: 'paper', x: 0.75, y: 0.96, text: 'TimesFM prediction API →', showarrow: false, font: { size: 11, color: muted } },
                ],
                legend: { orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center', font: { size: 11, color: muted } },
              }}
            />
          </div>
        </section>

        <section className="col-span-4 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Safety watchlist</h3>
            <p className="text-xs text-on-surface-variant">Sort by immediate operating risk</p>
          </div>
          <div className="h-[255px]">
            <PlotFigure
              data={[
                {
                  x: lineLoading,
                  y: corridors,
                  type: 'bar',
                  orientation: 'h',
                  marker: { color: lineColors },
                  text: lineLoading.map((value) => `${value.toFixed(1)}%`),
                  textposition: 'outside',
                  cliponaxis: false,
                  hovertemplate: '%{y}<br>%{x:.1f}% utilized<extra></extra>',
                  showlegend: false,
                },
              ]}
              layout={{
                ...baseLayout,
                margin: { t: 12, r: 22, b: 30, l: 104 },
                hovermode: 'y unified',
                hoverdistance: 20,
                hoverlabel: {
                  bgcolor: '#FFFFFF',
                  bordercolor: surfaceHigh,
                  font: { family: 'Inter, system-ui, sans-serif', size: 12, color: text },
                },
                xaxis: { ...baseLayout.xaxis, type: 'linear', range: [0, safetyAxisMax], ticksuffix: '%' },
                yaxis: { ...baseLayout.yaxis, type: 'category' },
                shapes: safetyAxisMax >= 70 ? [
                  { type: 'line', yref: 'paper', y0: 0, y1: 1, x0: 70, x1: 70, line: { color: alert, width: 1, dash: 'dot' } },
                  { type: 'line', yref: 'paper', y0: 0, y1: 1, x0: 95, x1: 95, line: { color: critical, width: 2, dash: 'dot' } },
                ] : [],
              }}
            />
          </div>
        </section>

        <section className="col-span-7 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Consumption vs production — 24h actuals</h3>
            <p className="text-xs text-on-surface-variant">Context only — not a prediction target</p>
          </div>
          <div className="h-[300px]">
            <PlotFigure
              data={[
                { x: hours, y: loadActual, type: 'scatter', mode: 'lines', name: 'load actual', line: { color: text, width: 2.5, shape: 'spline' }, hovertemplate: '%{x}<br>%{y} MW load<extra></extra>' },
                { x: hours, y: generationActual, type: 'scatter', mode: 'lines', name: 'generation actual', line: { color: primarySoft, width: 2.5, shape: 'spline' }, hovertemplate: '%{x}<br>%{y} MW generation<extra></extra>' },
              ]}
              layout={{
                ...baseLayout,
                hovermode: 'x unified',
                margin: { t: 12, r: 18, b: 40, l: 58 },
                xaxis: {
                  ...baseLayout.xaxis,
                  type: 'category',
                  categoryorder: 'array',
                  categoryarray: hours,
                  showspikes: true,
                  spikemode: 'across',
                  spikesnap: 'cursor',
                  spikedistance: -1,
                  spikecolor: '#6B6B6B',
                  spikethickness: 1,
                  spikedash: 'dot',
                },
                yaxis: { ...baseLayout.yaxis, type: 'linear', title: { text: 'MW' }, showspikes: false },
                legend: { orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center', font: { size: 11, color: muted } },
              }}
            />
          </div>
        </section>

        <section className="col-span-5 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Reserve/flexibility readiness</h3>
            <p className="text-xs text-on-surface-variant">MW capacity by balancing service</p>
          </div>
          <div className="mb-2 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg bg-surface px-3 py-2">
              <p className="font-semibold uppercase tracking-[0.12em] text-on-surface-variant">Gen headroom</p>
              <p className="mt-1 font-display text-lg font-bold text-on-background">{overview.reserve_headroom.toLocaleString()} MW</p>
            </div>
            <div className="rounded-lg bg-surface px-3 py-2">
              <p className="font-semibold uppercase tracking-[0.12em] text-on-surface-variant">Imbalance</p>
              <p className="mt-1 font-display text-lg font-bold" style={{ color: currentImbalance >= 0 ? normal : critical }}>
                {currentImbalance > 0 ? '+' : ''}{currentImbalance} MW
              </p>
            </div>
          </div>
          <div className="h-[185px]">
            <PlotFigure
              data={[
                { x: reserveTypes, y: reserveAvailable, type: 'bar', name: 'available MW', marker: { color: surfaceHigh }, hovertemplate: '%{x}<br>%{y:.0f} MW available<extra></extra>' },
                { x: reserveTypes, y: reserveUsed, type: 'bar', name: 'used MW', marker: { color: primary }, hovertemplate: '%{x}<br>%{y:.0f} MW used<extra></extra>' },
              ]}
              layout={{
                ...baseLayout,
                barmode: 'group',
                hovermode: 'x unified',
                margin: { t: 6, r: 12, b: 42, l: 68 },
                yaxis: { ...baseLayout.yaxis, type: 'linear', range: [0, reserveAxisMax], ticksuffix: ' MW', title: { text: 'reserve capacity' } },
                legend: { orientation: 'h', y: -0.28, x: 0.5, xanchor: 'center', font: { size: 11, color: muted } },
              }}
            />
          </div>
        </section>

        <section className="col-span-8 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Net imbalance — 24h actuals</h3>
            <p className="text-xs text-on-surface-variant">Zero line shows surplus vs deficit pressure</p>
          </div>
          <div className="h-[235px]">
            <PlotFigure
              data={[
                {
                  x: hours,
                  y: balanceActual,
                  type: 'scatter',
                  mode: 'lines',
                  name: 'actual imbalance',
                  line: { color: text, width: 3, shape: 'spline' },
                  fill: 'tozeroy',
                  fillcolor: 'rgba(0, 40, 142, 0.08)',
                  hovertemplate: '%{x}<br>%{y:+.0f} MW imbalance<extra></extra>',
                },
              ]}
              layout={{
                ...baseLayout,
                hovermode: 'x unified',
                margin: { t: 12, r: 18, b: 40, l: 58 },
                xaxis: {
                  ...baseLayout.xaxis,
                  type: 'category',
                  categoryorder: 'array',
                  categoryarray: hours,
                  showspikes: true,
                  spikemode: 'across',
                  spikesnap: 'cursor',
                  spikedistance: -1,
                  spikecolor: '#6B6B6B',
                  spikethickness: 1,
                  spikedash: 'dot',
                },
                yaxis: { ...baseLayout.yaxis, type: 'linear', title: { text: 'MW' }, zeroline: true, zerolinecolor: muted },
                shapes: [
                  { type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: -320, y1: -120, fillcolor: alert, opacity: 0.08, line: { width: 0 } },
                  { type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: -800, y1: -320, fillcolor: critical, opacity: 0.08, line: { width: 0 } },
                  { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: muted, width: 1, dash: 'dot' } },
                ],
              }}
            />
          </div>
        </section>

        <section className="col-span-4 rounded-xl bg-surface-low p-4">
          <h3 className="mb-4 font-display text-sm font-bold text-on-background">Alarm queue</h3>
          <div className="space-y-3">
            {alarmQueue.map(({ priority, count, label, color }) => (
              <div key={priority} className="grid grid-cols-[46px_1fr_auto] items-center gap-3 rounded-lg bg-surface px-3 py-2">
                <span className="text-xs font-bold" style={{ color }}>{priority}</span>
                <span className="text-sm text-on-background">{label}</span>
                <span className="font-display text-xl font-bold text-on-background">{count}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
