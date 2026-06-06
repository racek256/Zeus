type ColorStop = { pct: number; r: number; g: number; b: number }

function rampColor(value: number, stops: ColorStop[]): string {
  const clamped = Math.max(stops[0].pct, Math.min(stops[stops.length - 1].pct, value))
  let lower = stops[0]
  let upper = stops[stops.length - 1]

  for (let i = 0; i < stops.length - 1; i++) {
    if (clamped >= stops[i].pct && clamped <= stops[i + 1].pct) {
      lower = stops[i]
      upper = stops[i + 1]
      break
    }
  }

  if (lower.pct === upper.pct) return `rgb(${lower.r},${lower.g},${lower.b})`

  const t = (clamped - lower.pct) / (upper.pct - lower.pct)
  const r = Math.round(lower.r + (upper.r - lower.r) * t)
  const g = Math.round(lower.g + (upper.g - lower.g) * t)
  const b = Math.round(lower.b + (upper.b - lower.b) * t)
  return `rgb(${r},${g},${b})`
}

export function loadingColor(loadingPercent: number): string {
  return rampColor(loadingPercent, [
    { pct: 0, r: 34, g: 197, b: 94 },
    { pct: 50, r: 234, g: 179, b: 8 },
    { pct: 85, r: 239, g: 68, b: 68 },
    { pct: 100, r: 153, g: 27, b: 27 },
  ])
}
