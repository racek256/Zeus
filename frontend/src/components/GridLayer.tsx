import { useMemo } from 'react'
import { Source, Layer } from 'react-map-gl/mapbox'
import type { FeatureCollection, Feature, Geometry } from 'geojson'
import type { TopologyData, SnapshotData, Bus, Branch, Generator, Load } from '../types/grid'
import type { NodeFilterType } from './NodeTypeFilter'

interface GridLayerProps {
  topology: TopologyData
  snapshot: SnapshotData | null
  hoveredKey: string | null
  selectedKey: string | null
  hideNodeLayers?: boolean
  enabledTypes: Record<NodeFilterType, boolean>
}

const REGION_COLORS: Record<string, string> = {
  r1: '#FF6B6B',
  r2: '#4ECDC4',
  r3: '#45B7D1',
}

function scalarProperties(source: Record<string, unknown>): Record<string, string | number | boolean | null> {
  const result: Record<string, string | number | boolean | null> = {}
  for (const [key, value] of Object.entries(source)) {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || value === null) {
      result[key] = value
    }
  }
  return result
}

function loadingColor(loadingPercent: number): string {
  if (loadingPercent < 70) return '#22C55E'
  if (loadingPercent <= 90) return '#EAB308'
  return '#EF4444'
}

function busToFeature(bus: Bus, voltage?: number, pMw?: number, hoveredKey?: string | null, selectedKey?: string | null): Feature<Geometry> {
  const key = `bus:${bus.id}`
  return {
    type: 'Feature',
    geometry: {
      type: 'Point',
      coordinates: bus.coordinates,
    },
    properties: {
      ...scalarProperties(bus),
      id: bus.id,
      key,
      region: bus.region,
      v_kV: bus.v_kV,
      color: REGION_COLORS[bus.region] ?? '#999999',
      in_service: bus.in_service,
      is_slack: bus.is_slack,
      min_v_pu: bus.min_v_pu,
      max_v_pu: bus.max_v_pu,
      x_coordinate: bus.x_coordinate,
      y_coordinate: bus.y_coordinate,
      longitude: bus.coordinates[0],
      latitude: bus.coordinates[1],
      vm_pu: voltage ?? null,
      p_mw: pMw ?? null,
      hovered: hoveredKey === key,
      selected: selectedKey === key,
      type: 'bus',
    },
  }
}

function branchToFeature(branch: Branch, loadingPercent?: number, hoveredKey?: string | null, selectedKey?: string | null): Feature<Geometry> {
  const key = `branch:${branch.id}`
  const fromCoordinates = branch.coordinates[0]
  const toCoordinates = branch.coordinates[branch.coordinates.length - 1]
  return {
    type: 'Feature',
    geometry: {
      type: 'LineString',
      coordinates: branch.coordinates,
    },
    properties: {
      ...scalarProperties(branch),
      id: branch.id,
      key,
      from_bus: branch.from_bus,
      to_bus: branch.to_bus,
      in_service: branch.in_service,
      is_trafo: branch.is_trafo,
      max_i_ka: branch.max_i_ka,
      trafo_ratio_rel: branch.trafo_ratio_rel,
      loading_percent: loadingPercent ?? 0,
      color: loadingPercent != null ? loadingColor(loadingPercent) : '#999999',
      from_longitude: fromCoordinates[0],
      from_latitude: fromCoordinates[1],
      to_longitude: toCoordinates[0],
      to_latitude: toCoordinates[1],
      hovered: hoveredKey === key,
      selected: selectedKey === key,
      type: 'branch',
    },
  }
}

function generatorToFeature(gen: Generator, buses: Bus[], hoveredKey?: string | null, selectedKey?: string | null): Feature<Geometry> {
  const bus = buses.find((b) => b.id === gen.bus_name)
  if (!bus) return null as unknown as Feature<Geometry>
  const key = `generator:${gen.id}`
  return {
    type: 'Feature',
    geometry: {
      type: 'Point',
      coordinates: bus.coordinates,
    },
    properties: {
      ...scalarProperties(gen),
      id: gen.id,
      key,
      bus_name: gen.bus_name,
      opt_category: gen.opt_category,
      min_p_mw: gen.min_p_mw,
      max_p_mw: gen.max_p_mw,
      longitude: bus.coordinates[0],
      latitude: bus.coordinates[1],
      hovered: hoveredKey === key,
      selected: selectedKey === key,
      color: '#FFD93D',
      type: 'generator',
    },
  }
}

function loadToFeature(load: Load, buses: Bus[], hoveredKey?: string | null, selectedKey?: string | null): Feature<Geometry> {
  const bus = buses.find((b) => b.id === load.bus_name)
  if (!bus) return null as unknown as Feature<Geometry>
  const key = `load:${load.id}`
  return {
    type: 'Feature',
    geometry: {
      type: 'Point',
      coordinates: bus.coordinates,
    },
    properties: {
      ...scalarProperties(load),
      id: load.id,
      key,
      bus_name: load.bus_name,
      longitude: bus.coordinates[0],
      latitude: bus.coordinates[1],
      hovered: hoveredKey === key,
      selected: selectedKey === key,
      color: '#95E1D3',
      type: 'load',
    },
  }
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function clusteredBusIds(topology: TopologyData): Set<string> {
  const counts = new Map<string, number>()
  for (const bus of topology.buses) counts.set(bus.id, 1)
  for (const generator of topology.generators) counts.set(generator.bus_name, (counts.get(generator.bus_name) ?? 0) + 1)
  for (const load of topology.loads) counts.set(load.bus_name, (counts.get(load.bus_name) ?? 0) + 1)
  return new Set([...counts.entries()].filter(([, count]) => count >= 3).map(([busId]) => busId))
}

function clusterToFeatures(topology: TopologyData, hoveredKey?: string | null, selectedKey?: string | null): Feature<Geometry>[] {
  const groups = new Map<string, { bus: Bus; generators: Generator[]; loads: Load[] }>()

  for (const bus of topology.buses) {
    groups.set(bus.id, { bus, generators: [], loads: [] })
  }

  for (const generator of topology.generators) {
    const group = groups.get(generator.bus_name)
    if (group) group.generators.push(generator)
  }

  for (const load of topology.loads) {
    const group = groups.get(load.bus_name)
    if (group) group.loads.push(load)
  }

  return [...groups.values()]
    .filter(({ generators, loads }) => 1 + generators.length + loads.length >= 3)
    .map(({ bus, generators, loads }) => {
      const key = `cluster:${bus.id}`
      const generatorIds = generators.map((generator) => generator.id).join(', ')
      const loadIds = loads.map((load) => load.id).join(', ')
      const installedCapacityMw = generators.reduce((sum, generator) => sum + numberValue(generator.installed_capacity_mw ?? generator.max_p_mw), 0)
      const minOutputMw = generators.reduce((sum, generator) => sum + numberValue(generator.min_output_mw ?? generator.min_p_mw), 0)
      const maxOutputMw = generators.reduce((sum, generator) => sum + numberValue(generator.max_output_mw ?? generator.max_p_mw), 0)
      const flexRangeMw = Math.max(maxOutputMw - minOutputMw, 0)
      const reserveCapableCount = generators.filter((generator) => generator.reserve_capable === true || generator.reserve_capable === 'true' || generator.reserve_capable === 'True').length
      const criticalLoadCount = loads.filter((load) => load.critical_infrastructure === true || load.critical_infrastructure === 'true' || load.critical_infrastructure === 'True').length
      const demandResponseCount = loads.filter((load) => load.demand_response_capable === true || load.demand_response_capable === 'true' || load.demand_response_capable === 'True').length
      return {
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: bus.coordinates,
        },
        properties: {
          id: bus.id,
          key,
          type: 'cluster',
          color: '#8B5CF6',
          display_name: `Cluster at ${bus.id}`,
          title: `Cluster at ${bus.id}`,
          bus_name: bus.id,
          node_count: 1 + generators.length + loads.length,
          bus_count: 1,
          generator_count: generators.length,
          load_count: loads.length,
          installed_capacity_mw: Math.round(installedCapacityMw * 10) / 10,
          min_output_mw: Math.round(minOutputMw * 10) / 10,
          max_output_mw: Math.round(maxOutputMw * 10) / 10,
          flex_range_mw: Math.round(flexRangeMw * 10) / 10,
          reserve_capable_count: reserveCapableCount,
          critical_load_count: criticalLoadCount,
          demand_response_count: demandResponseCount,
          generator_ids: generatorIds,
          load_ids: loadIds,
          longitude: bus.coordinates[0],
          latitude: bus.coordinates[1],
          hovered: hoveredKey === key,
          selected: selectedKey === key,
        },
      } as Feature<Geometry>
    })
}

export function GridLayer({ topology, snapshot, hoveredKey, selectedKey, hideNodeLayers = false, enabledTypes }: GridLayerProps) {
  const clusteredBuses = useMemo(() => clusteredBusIds(topology), [topology])
  const hideClusteredChildren = enabledTypes.cluster

  const snapshotBranchMap = useMemo(() => {
    if (!snapshot) return new Map<string, number>()
    return new Map(snapshot.branches.map((b) => [b.id, b.loading_percent]))
  }, [snapshot])

  const snapshotBusMap = useMemo(() => {
    if (!snapshot) return new Map<string, { vm_pu: number; p_mw: number }>()
    return new Map(snapshot.buses.map((b) => [b.id, { vm_pu: b.vm_pu, p_mw: b.p_mw }]))
  }, [snapshot])

  const branchesGeoJson: FeatureCollection = useMemo(
    () => ({
      type: 'FeatureCollection',
      features: topology.branches
        .map((branch) => branchToFeature(branch, snapshotBranchMap.get(branch.id), hoveredKey, selectedKey))
        .filter(Boolean),
    }),
    [topology.branches, snapshotBranchMap, hoveredKey, selectedKey],
  )

  const busesGeoJson: FeatureCollection = useMemo(
    () => ({
      type: 'FeatureCollection',
      features: enabledTypes.bus ? topology.buses.filter((bus) => !hideClusteredChildren || !clusteredBuses.has(bus.id)).map((bus) => {
        const snapshotBus = snapshotBusMap.get(bus.id)
        return busToFeature(bus, snapshotBus?.vm_pu, snapshotBus?.p_mw, hoveredKey, selectedKey)
      }) : [],
    }),
    [topology.buses, clusteredBuses, hideClusteredChildren, enabledTypes.bus, snapshotBusMap, hoveredKey, selectedKey],
  )

  const generatorsGeoJson: FeatureCollection = useMemo(
    () => ({
      type: 'FeatureCollection',
      features: enabledTypes.generator ? topology.generators
        .filter((gen) => !hideClusteredChildren || !clusteredBuses.has(gen.bus_name))
        .map((gen) => generatorToFeature(gen, topology.buses, hoveredKey, selectedKey))
        .filter(Boolean) : [],
    }),
    [topology.generators, topology.buses, clusteredBuses, hideClusteredChildren, enabledTypes.generator, hoveredKey, selectedKey],
  )

  const loadsGeoJson: FeatureCollection = useMemo(
    () => ({
      type: 'FeatureCollection',
      features: enabledTypes.load ? topology.loads
        .filter((load) => !hideClusteredChildren || !clusteredBuses.has(load.bus_name))
        .map((load) => loadToFeature(load, topology.buses, hoveredKey, selectedKey))
        .filter(Boolean) : [],
    }),
    [topology.loads, topology.buses, clusteredBuses, hideClusteredChildren, enabledTypes.load, hoveredKey, selectedKey],
  )

  const clustersGeoJson: FeatureCollection = useMemo(
    () => ({
      type: 'FeatureCollection',
      features: enabledTypes.cluster ? clusterToFeatures(topology, hoveredKey, selectedKey) : [],
    }),
    [topology, enabledTypes.cluster, hoveredKey, selectedKey],
  )

  return (
    <>
      {/* Branches as lines */}
      <Source id="grid-branches" type="geojson" data={branchesGeoJson}>
        <Layer
          id="grid-branches-hit"
          type="line"
          paint={{
            'line-color': '#1C1B1B',
            'line-width': ['interpolate', ['linear'], ['zoom'], 6, 10, 10, 14, 14, 18],
            'line-opacity': 0.01,
          }}
        />
        <Layer
          id="grid-branches-line"
          type="line"
          paint={{
            'line-color': ['get', 'color'],
            'line-width': [
              'interpolate',
              ['linear'],
              ['zoom'],
              6,
              ['case', ['==', ['get', 'selected'], true], 3.2, ['==', ['get', 'hovered'], true], 2.4, 1.2],
              10,
              ['case', ['==', ['get', 'selected'], true], 5.2, ['==', ['get', 'hovered'], true], 4.2, 2.5],
              14,
              ['case', ['==', ['get', 'selected'], true], 7.2, ['==', ['get', 'hovered'], true], 6, 4],
            ],
            'line-opacity': ['case', ['==', ['get', 'selected'], true], 1, ['==', ['get', 'hovered'], true], 1, 0.85],
          }}
        />
      </Source>

      {!hideNodeLayers && (
        <Source id="grid-clusters" type="geojson" data={clustersGeoJson}>
          <Layer
            id="grid-clusters-circle"
            type="circle"
            paint={{
              'circle-color': '#8B5CF6',
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['zoom'],
                6,
                ['case', ['==', ['get', 'selected'], true], 10, ['==', ['get', 'hovered'], true], 9, 7],
                10,
                ['case', ['==', ['get', 'selected'], true], 16, ['==', ['get', 'hovered'], true], 14, 11],
                14,
                ['case', ['==', ['get', 'selected'], true], 24, ['==', ['get', 'hovered'], true], 21, 17],
              ],
              'circle-opacity': 0.92,
              'circle-stroke-color': '#FCF9F8',
              'circle-stroke-width': ['case', ['==', ['get', 'selected'], true], 3, ['==', ['get', 'hovered'], true], 2.5, 1.5],
            }}
          />
          <Layer
            id="grid-clusters-label"
            type="symbol"
            layout={{
              'text-field': ['to-string', ['get', 'node_count']],
              'text-size': ['interpolate', ['linear'], ['zoom'], 6, 9, 10, 11, 14, 13],
              'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
              'text-allow-overlap': true,
            }}
            paint={{
              'text-color': '#FCF9F8',
              'text-halo-color': '#1C1B1B',
              'text-halo-width': 1,
            }}
          />
        </Source>
      )}

      {!hideNodeLayers && (
        <>
          {/* Buses as circles */}
          <Source id="grid-buses" type="geojson" data={busesGeoJson}>
            <Layer
              id="grid-buses-circle"
              type="circle"
              paint={{
                'circle-color': ['get', 'color'],
                'circle-radius': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  6,
                  ['case', ['==', ['get', 'selected'], true], 6, ['==', ['get', 'hovered'], true], 5, 3],
                  10,
                  ['case', ['==', ['get', 'selected'], true], 9, ['==', ['get', 'hovered'], true], 7.5, 5],
                  14,
                  ['case', ['==', ['get', 'selected'], true], 12, ['==', ['get', 'hovered'], true], 10, 7],
                ],
                'circle-opacity': 0.9,
                'circle-stroke-color': ['case', ['==', ['get', 'selected'], true], '#FCF9F8', ['==', ['get', 'hovered'], true], '#FCF9F8', '#1C1B1B'],
                'circle-stroke-width': ['case', ['==', ['get', 'selected'], true], 2, ['==', ['get', 'hovered'], true], 1.5, 0.5],
              }}
            />
          </Source>

          {/* Generators as larger circles */}
          <Source id="grid-generators" type="geojson" data={generatorsGeoJson}>
            <Layer
              id="grid-generators-circle"
              type="circle"
              paint={{
                'circle-color': '#FFD93D',
                'circle-radius': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  6,
                  ['case', ['==', ['get', 'selected'], true], 8, ['==', ['get', 'hovered'], true], 7, 5],
                  10,
                  ['case', ['==', ['get', 'selected'], true], 12, ['==', ['get', 'hovered'], true], 10.5, 8],
                  14,
                  ['case', ['==', ['get', 'selected'], true], 16, ['==', ['get', 'hovered'], true], 14, 11],
                ],
                'circle-opacity': 0.9,
                'circle-stroke-color': ['case', ['==', ['get', 'selected'], true], '#FCF9F8', ['==', ['get', 'hovered'], true], '#FCF9F8', '#1C1B1B'],
                'circle-stroke-width': ['case', ['==', ['get', 'selected'], true], 2.5, ['==', ['get', 'hovered'], true], 2, 1],
              }}
            />
          </Source>

          {/* Loads as smaller circles */}
          <Source id="grid-loads" type="geojson" data={loadsGeoJson}>
            <Layer
              id="grid-loads-circle"
              type="circle"
              paint={{
                'circle-color': '#95E1D3',
                'circle-radius': [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  6,
                  ['case', ['==', ['get', 'selected'], true], 5.5, ['==', ['get', 'hovered'], true], 4.5, 2.5],
                  10,
                  ['case', ['==', ['get', 'selected'], true], 8, ['==', ['get', 'hovered'], true], 6.5, 4],
                  14,
                  ['case', ['==', ['get', 'selected'], true], 10.5, ['==', ['get', 'hovered'], true], 8.5, 5.5],
                ],
                'circle-opacity': 0.85,
                'circle-stroke-color': ['case', ['==', ['get', 'selected'], true], '#FCF9F8', ['==', ['get', 'hovered'], true], '#FCF9F8', '#1C1B1B'],
                'circle-stroke-width': ['case', ['==', ['get', 'selected'], true], 2, ['==', ['get', 'hovered'], true], 1.5, 0.5],
              }}
            />
          </Source>
        </>
      )}
    </>
  )
}
