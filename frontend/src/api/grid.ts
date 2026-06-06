import type { SnapshotData, TopologyData } from '../types/grid'

const BASE_URL = `http://${window.location.hostname}:8000`

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`)
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`)
  }
  return response.json()
}

export async function getTopology(): Promise<TopologyData> {
  return fetchJson<TopologyData>('/api/grid/topology')
}

export async function getSnapshots(): Promise<string[]> {
  return fetchJson<string[]>('/api/grid/snapshots')
}

function isoToUnderscore(iso: string): string {
  return iso.replace(/[-:T]/g, '_')
}

export async function getSnapshot(timestamp: string): Promise<SnapshotData> {
  const normalized = timestamp.includes('T') ? isoToUnderscore(timestamp) : timestamp
  return fetchJson<SnapshotData>(`/api/grid/snapshot/${encodeURIComponent(normalized)}`)
}
