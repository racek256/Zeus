export interface Bus {
  [key: string]: unknown
  id: string
  region: string
  v_kV: number
  in_service: boolean
  is_slack: boolean
  min_v_pu: number
  max_v_pu: number
  x_coordinate: number
  y_coordinate: number
  coordinates: [number, number]
}

export interface Branch {
  [key: string]: unknown
  id: string
  from_bus: string
  to_bus: string
  in_service: boolean
  max_i_ka: number
  is_trafo: boolean
  trafo_ratio_rel: number | null
  coordinates: [number, number][]
}

export interface Generator {
  [key: string]: unknown
  id: string
  bus_name: string
  opt_category: string
  min_p_mw: number
  max_p_mw: number
  coordinates: [number, number]
}

export interface Load {
  [key: string]: unknown
  id: string
  bus_name: string
  coordinates: [number, number]
}

export interface SnapshotBus {
  id: string
  vm_pu: number
  p_mw: number
}

export interface SnapshotBranch {
  id: string
  loading_percent: number
}

export interface SnapshotData {
  buses: SnapshotBus[]
  branches: SnapshotBranch[]
}

export type GridElementType = 'bus' | 'branch' | 'generator' | 'load' | 'cluster'

export interface GridSelection {
  key: string
  type: GridElementType
  title: string
  subtitle: string
  color: string
  properties: Record<string, string | number | boolean | null>
}

export interface TopologyData {
  buses: Bus[]
  branches: Branch[]
  generators: Generator[]
  loads: Load[]
}
