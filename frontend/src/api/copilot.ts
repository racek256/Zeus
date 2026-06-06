import type {
  CopilotStatus,
  Proposal,
  ChatMessage,
  SimulationStatus,
  SimulationHourResult,
} from '../types/copilot'

const BASE_URL = 'https://dev.racek.xyz'

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, init)
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(`API error ${response.status}: ${body}`)
  }
  return response.json()
}

export async function initCopilot(): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>('/api/copilot/init', { method: 'POST' })
}

export async function getCopilotStatus(): Promise<CopilotStatus> {
  return fetchJson<CopilotStatus>('/api/copilot/status')
}

export async function startSimulation(opts?: {
  start_hour?: number
  end_hour?: number
  stop_on_failure?: boolean
  allow_fallback_physics?: boolean
  full_n1_scan?: boolean
  model?: string
}): Promise<Record<string, unknown>> {
  return fetchJson('/api/copilot/simulate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts ?? {}),
  })
}

export async function getSimulationStatus(): Promise<SimulationStatus> {
  return fetchJson<SimulationStatus>('/api/copilot/simulation')
}

export async function getSimulationHours(): Promise<SimulationHourResult[]> {
  return fetchJson<SimulationHourResult[]>('/api/copilot/simulation/hours')
}

export async function getSimulationHour(hourIndex: number): Promise<SimulationHourResult> {
  return fetchJson<SimulationHourResult>(`/api/copilot/simulation/hour/${hourIndex}`)
}

export async function getProposals(status?: string): Promise<Proposal[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return fetchJson<Proposal[]>(`/api/copilot/proposals${qs}`)
}

export async function sendChat(message: string): Promise<{ response: string; chat_history: ChatMessage[] }> {
  return fetchJson('/api/copilot/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
}
