import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-dist'

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
    void Plotly.react(node, data, layout, {
      displayModeBar: false,
      responsive: true,
      ...config,
    })

    return () => Plotly.purge(node)
  }, [data, layout, config])

  return <div ref={nodeRef} className="h-full w-full" />
}

const surface = '#FCF9F8'
const surfaceLow = '#F6F3F2'
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
  xaxis: {
    gridcolor: surfaceHigh,
    zeroline: false,
    tickfont: { color: muted, size: 11 },
  },
  yaxis: {
    gridcolor: surfaceHigh,
    zeroline: false,
    tickfont: { color: muted, size: 11 },
  },
}

const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`)
const nextHours = Array.from({ length: 24 }, (_, i) => `+${i + 1}h`)

const frequency = [50.01, 50.004, 49.997, 49.986, 49.978, 49.971, 49.982, 49.994, 50.006, 50.011, 50.004, 49.996, 49.991, 49.984, 49.976, 49.982, 49.996, 50.008, 50.014, 50.006, 49.997, 49.989, 49.982, 49.986]
const loadActual = [8200, 7950, 7700, 7480, 7400, 7600, 8050, 8900, 9650, 10150, 10480, 10650, 10580, 10350, 10100, 9950, 10200, 10850, 11350, 11100, 10400, 9650, 9000, 8500]
const generationActual = [8350, 8100, 7800, 7550, 7480, 7700, 8120, 8820, 9480, 10050, 10320, 10520, 10470, 10260, 10020, 10000, 10380, 11020, 11540, 11220, 10550, 9820, 9180, 8660]
const forecastMedian = [8580, 8320, 8120, 7980, 7920, 8080, 8540, 9180, 9920, 10460, 10820, 11050, 11120, 10900, 10620, 10480, 10780, 11420, 11950, 11720, 11050, 10240, 9480, 8980]
const forecastLow = forecastMedian.map((value, index) => value - [360, 330, 310, 300, 300, 320, 350, 390, 430, 460, 480, 500, 510, 490, 470, 450, 470, 520, 560, 540, 500, 450, 400, 370][index])
const forecastHigh = forecastMedian.map((value, index) => value + [420, 390, 360, 340, 340, 360, 400, 460, 520, 560, 590, 620, 640, 610, 580, 560, 590, 660, 710, 680, 620, 540, 470, 430][index])
const forecastAxis = [hours[hours.length - 1], ...nextHours]
const forecastMedianSeries = [loadActual[loadActual.length - 1], ...forecastMedian]
const forecastLowSeries = [loadActual[loadActual.length - 1], ...forecastLow]
const forecastHighSeries = [loadActual[loadActual.length - 1], ...forecastHigh]
const balanceActual = generationActual.map((value, index) => value - loadActual[index])
const balanceForecast = forecastMedian.map((value, index) => {
  const generationForecast = [8740, 8460, 8250, 8080, 8030, 8120, 8450, 9010, 9580, 10080, 10390, 10540, 10490, 10310, 10120, 10040, 10260, 10780, 11180, 10940, 10310, 9590, 9050, 8680][index]
  return generationForecast - value
})
const balanceForecastSeries = [balanceActual[balanceActual.length - 1], ...balanceForecast]
const importCapacity = [120, 120, 120, 140, 140, 140, 180, 220, 260, 300, 320, 320, 320, 300, 280, 280, 300, 340, 360, 340, 280, 220, 180, 150]
const reserveCover = [210, 210, 220, 220, 220, 230, 250, 270, 300, 320, 330, 330, 330, 320, 310, 300, 310, 330, 340, 330, 300, 270, 240, 220]
const deficitRisk = balanceForecast.map((value) => Math.max(0, -value))
const currentLoad = loadActual[loadActual.length - 1]
const currentGeneration = generationActual[generationActual.length - 1]
const currentImbalance = currentGeneration - currentLoad
const currentRatio = (currentGeneration / currentLoad).toFixed(2)
const safetyState = 'Tightening'

const corridors = ['CZ-DE North', 'CZ-AT South', 'CZ-SK East', 'CZ-PL North', 'Prague ring', 'Moravia spine']
const lineLoading = [96, 89, 82, 77, 68, 61]
const lineColors = lineLoading.map((value) => {
  if (value >= 95) return critical
  if (value >= 85) return alarm
  if (value >= 70) return alert
  return normal
})

const borders = ['DE', 'SK', 'PL', 'AT']
const scheduledFlow = [980, 420, -260, 610]
const actualFlow = [1140, 360, -410, 690]
const reserveTypes = ['FCP 30s', 'aFRR 5-10m', 'mFRR 5m', 'mFRR 15m', 'SVQC']
const reserveUsed = [42, 68, 51, 24, 39]
const reserveAvailable = [100, 100, 100, 100, 100]

const cards = [
  { label: 'Consumption now', value: `${currentLoad.toLocaleString()} MW`, state: 'live demand', color: text },
  { label: 'Production now', value: `${currentGeneration.toLocaleString()} MW`, state: 'available supply', color: primarySoft },
  { label: 'Prod / cons ratio', value: `${currentRatio}x`, state: currentRatio >= '1.00' ? 'covered' : 'deficit pressure', color: currentImbalance >= 0 ? normal : alarm },
  { label: 'Net imbalance', value: `${currentImbalance > 0 ? '+' : ''}${currentImbalance} MW`, state: 'dispatch action window', color: currentImbalance >= 0 ? normal : critical },
  { label: 'Safety state', value: safetyState, state: 'line + reserve constrained', color: critical },
]

export function Analytics() {
  return (
    <div className="flex-1 overflow-auto bg-surface px-7 py-6 text-on-background">
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
            <h3 className="font-display text-sm font-bold text-on-background">Balance margin now and next 24h</h3>
            <p className="text-xs text-on-surface-variant">Zero line separates surplus from deficit</p>
          </div>
          <div className="h-[255px]">
            <PlotFigure
              data={[
                {
                  x: hours,
                  y: balanceActual,
                  type: 'scatter',
                  mode: 'lines',
                  name: 'actual balance',
                  line: { color: text, width: 3, shape: 'spline' },
                  fill: 'tozeroy',
                  fillcolor: 'rgba(0, 40, 142, 0.08)',
                  hovertemplate: '%{x}<br>%{y:+.0f} MW balance<extra></extra>',
                },
                {
                  x: forecastAxis,
                  y: balanceForecastSeries,
                  type: 'scatter',
                  mode: 'lines',
                  name: 'forecast balance',
                  line: { color: primary, width: 3, dash: 'dash', shape: 'spline' },
                  hovertemplate: '%{x}<br>%{y:+.0f} MW forecast balance<extra></extra>',
                },
              ]}
              layout={{
                ...baseLayout,
                margin: { t: 14, r: 16, b: 32, l: 46 },
                xaxis: {
                  ...baseLayout.xaxis,
                  categoryorder: 'array',
                  categoryarray: [...hours, ...nextHours],
                  showspikes: true,
                  spikemode: 'across',
                  spikesnap: 'cursor',
                  spikedistance: -1,
                  spikecolor: '#6B6B6B',
                  spikethickness: 1,
                  spikedash: 'dot',
                },
                yaxis: { ...baseLayout.yaxis, title: { text: 'MW' } },
                hovermode: 'x unified',
                shapes: [
                  { type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: -120, y1: 120, fillcolor: '#4CAF50', opacity: 0.08, line: { width: 0 } },
                  { type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: -320, y1: -120, fillcolor: '#FF9800', opacity: 0.08, line: { width: 0 } },
                  { type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: -800, y1: -320, fillcolor: '#F44336', opacity: 0.08, line: { width: 0 } },
                  { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0, y1: 0, line: { color: muted, width: 1, dash: 'dot' } },
                ],
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
                  hovertemplate: '%{y}<br>%{x}% loading<extra></extra>',
                },
              ]}
              layout={{
                ...baseLayout,
                margin: { t: 12, r: 22, b: 30, l: 104 },
                xaxis: { ...baseLayout.xaxis, range: [0, 105], ticksuffix: '%' },
                yaxis: { ...baseLayout.yaxis, autorange: 'reversed' },
                shapes: [
                  { type: 'line', yref: 'paper', y0: 0, y1: 1, x0: 70, x1: 70, line: { color: alert, width: 1, dash: 'dot' } },
                  { type: 'line', yref: 'paper', y0: 0, y1: 1, x0: 95, x1: 95, line: { color: critical, width: 2, dash: 'dot' } },
                ],
              }}
            />
          </div>
        </section>

        <section className="col-span-7 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Consumption versus production</h3>
            <p className="text-xs text-on-surface-variant">Actuals plus forecast envelope for demand pressure</p>
          </div>
          <div className="h-[300px]">
            <PlotFigure
              data={[
                { x: forecastAxis, y: forecastHighSeries, type: 'scatter', mode: 'lines', line: { width: 0 }, showlegend: false, hoverinfo: 'skip' },
                { x: forecastAxis, y: forecastLowSeries, type: 'scatter', mode: 'lines', fill: 'tonexty', fillcolor: 'rgba(30, 64, 175, 0.16)', line: { width: 0 }, name: 'forecast band', hoverinfo: 'skip' },
                { x: hours, y: loadActual, type: 'scatter', mode: 'lines', name: 'load actual', line: { color: text, width: 2.5, shape: 'spline' }, hovertemplate: '%{x}<br>%{y} MW load<extra></extra>' },
                { x: hours, y: generationActual, type: 'scatter', mode: 'lines', name: 'generation actual', line: { color: primarySoft, width: 2.5, shape: 'spline' }, hovertemplate: '%{x}<br>%{y} MW generation<extra></extra>' },
                { x: forecastAxis, y: forecastMedianSeries, type: 'scatter', mode: 'lines', name: 'load forecast', line: { color: primary, width: 3, dash: 'dash', shape: 'spline' }, hovertemplate: '%{x}<br>%{y} MW forecast<extra></extra>' },
              ]}
              layout={{
                ...baseLayout,
                hovermode: 'x unified',
                margin: { t: 12, r: 18, b: 40, l: 58 },
                xaxis: {
                  ...baseLayout.xaxis,
                  categoryorder: 'array',
                  categoryarray: [...hours, ...nextHours],
                  showspikes: true,
                  spikemode: 'across',
                  spikesnap: 'cursor',
                  spikedistance: -1,
                  spikecolor: '#6B6B6B',
                  spikethickness: 1,
                  spikedash: 'dot',
                },
                yaxis: { ...baseLayout.yaxis, title: { text: 'MW' }, showspikes: false },
                legend: { orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center', font: { size: 11, color: muted } },
              }}
            />
          </div>
        </section>

        <section className="col-span-5 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Deficit coverage stack</h3>
            <p className="text-xs text-on-surface-variant">Imports and reserves against forecast shortfall</p>
          </div>
          <div className="h-[300px]">
            <PlotFigure
              data={[
                { x: nextHours, y: deficitRisk, type: 'bar', name: 'forecast deficit', marker: { color: '#FFD7D7' }, hovertemplate: '%{x}<br>%{y} MW deficit<extra></extra>' },
                { x: nextHours, y: importCapacity, type: 'scatter', mode: 'lines', name: 'import support', line: { color: primarySoft, width: 2.5, shape: 'spline' }, hovertemplate: '%{x}<br>%{y} MW imports<extra></extra>' },
                { x: nextHours, y: reserveCover, type: 'scatter', mode: 'lines', name: 'reserve cover', line: { color: primary, width: 3, shape: 'spline' }, hovertemplate: '%{x}<br>%{y} MW reserves<extra></extra>' },
              ]}
              layout={{
                ...baseLayout,
                margin: { t: 12, r: 18, b: 44, l: 56 },
                yaxis: { ...baseLayout.yaxis, title: { text: 'MW' } },
                hovermode: 'x unified',
                legend: { orientation: 'h', y: -0.20, x: 0.5, xanchor: 'center', font: { size: 11, color: muted } },
              }}
            />
          </div>
        </section>

        <section className="col-span-8 rounded-xl bg-surface-low p-4">
          <div className="mb-2 flex items-baseline justify-between gap-4">
            <h3 className="font-display text-sm font-bold text-on-background">Ancillary services headroom</h3>
            <p className="text-xs text-on-surface-variant">Can reserves absorb imbalance before safety limits are hit?</p>
          </div>
          <div className="h-[235px]">
            <PlotFigure
              data={[
                { x: reserveTypes, y: reserveAvailable, type: 'bar', name: 'available', marker: { color: surfaceHigh }, hovertemplate: '%{x}<br>%{y}% available<extra></extra>' },
                { x: reserveTypes, y: reserveUsed, type: 'bar', name: 'used', marker: { color: primary }, hovertemplate: '%{x}<br>%{y}% used<extra></extra>' },
              ]}
              layout={{
                ...baseLayout,
                barmode: 'overlay',
                margin: { t: 12, r: 18, b: 44, l: 46 },
                yaxis: { ...baseLayout.yaxis, range: [0, 110], ticksuffix: '%' },
                legend: { orientation: 'h', y: -0.22, x: 0.5, xanchor: 'center', font: { size: 11, color: muted } },
              }}
            />
          </div>
        </section>

        <section className="col-span-4 rounded-xl bg-surface-low p-4">
          <h3 className="mb-4 font-display text-sm font-bold text-on-background">Alarm queue</h3>
          <div className="space-y-3">
            {[
              { priority: 'P1', count: 2, label: 'N-1 breach risk', color: critical },
              { priority: 'P2', count: 5, label: 'Line loading high', color: alarm },
              { priority: 'P3', count: 11, label: 'Voltage drift', color: alert },
              { priority: 'Info', count: 24, label: 'Routine state changes', color: muted },
            ].map(({ priority, count, label, color }) => (
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
