export interface OverviewData {
  consumption_now: number
  production_now: number
  prod_cons_ratio: number
  net_imbalance: number
  safety_state: string
  max_line_loading: number
  max_trafo_loading: number
  reserve_headroom: number
  voltage_violations: number
}

export interface SafetyItem {
  corridor: string
  max_loading: number
  avg_loading: number
  count: number
}

export interface TimeseriesData {
  hours: string[]
  load_actual: number[]
  generation_actual: number[]
  balance_actual: number[]
  safety_watchlist: SafetyItem[]
  reserve_types: string[]
  reserve_used: number[]
  reserve_available: number[]
}

export interface AlarmsData {
  P1: number
  P2: number
  P3: number
  Info: number
}

const BASE_URL = 'https://dev.racek.xyz'

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`)
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`)
  }
  return response.json()
}

export async function getAnalyticsOverview(): Promise<OverviewData> {
  return fetchJson<OverviewData>('/api/analytics/overview')
}

export async function getAnalyticsTimeseries(hours: number = 24): Promise<TimeseriesData> {
  return fetchJson<TimeseriesData>(`/api/analytics/timeseries?hours=${hours}`)
}

export async function getAnalyticsSafety(): Promise<{ corridors: SafetyItem[] }> {
  return fetchJson<{ corridors: SafetyItem[] }>('/api/analytics/safety')
}

export async function getAnalyticsAlarms(): Promise<AlarmsData> {
  return fetchJson<AlarmsData>('/api/analytics/alarms')
}
