import { useEffect, useMemo, useRef } from 'react'
import { PolygonLayer } from '@deck.gl/layers'
import { ScenegraphLayer } from '@deck.gl/mesh-layers'
import type { PickingInfo } from '@deck.gl/core'
import type { Map as MapboxMap } from 'mapbox-gl'
import { DeckOverlay } from './DeckOverlay'
import type { NodeFilterType } from './NodeTypeFilter'
import type { Bus, Generator, GridSelection, Load, SnapshotData, TopologyData } from '../types/grid'

type NodeBuildingType = 'bus' | 'generator' | 'load' | 'cluster'
type BuildingColor = [number, number, number, number]
type TerrainMap = MapboxMap & {
  queryTerrainElevation?: (lngLat: [number, number], options?: { exaggerated?: boolean }) => number | null
}
type ViewBounds = {
  west: number
  south: number
  east: number
  north: number
}

interface NodeBuildingDatum {
  key: string
  type: NodeBuildingType
  id: string
  coordinates: [number, number]
  position: [number, number, number]
  footprint: [number, number, number][]
  height: number
  color: BuildingColor
  properties: GridSelection['properties']
}

interface NodeBuildingsLayerProps {
  topology: TopologyData
  snapshot: SnapshotData | null
  map: MapboxMap | null
  terrainVersion: number
  viewBounds: ViewBounds | null
  selectedKey: string | null
  enabledTypes: Record<NodeFilterType, boolean>
  onHoverKey: (key: string | null) => void
  onPick: (properties: GridSelection['properties'], relatedProperties: GridSelection['properties'][]) => void
}

const TYPE_STYLE: Record<NodeBuildingType, { color: BuildingColor; radius: number; height: number }> = {
  bus: { color: [255, 107, 107, 218], radius: 30, height: 44 },
  generator: { color: [255, 217, 61, 230], radius: 42, height: 66 },
  load: { color: [149, 225, 211, 214], radius: 24, height: 34 },
  cluster: { color: [139, 92, 246, 236], radius: 64, height: 94 },
}

const HOVER_COLOR: BuildingColor = [0, 255, 238, 255]
const SELECTED_COLOR: BuildingColor = [255, 0, 214, 255]
const GENERATOR_SELECTED_HALO: BuildingColor = [255, 0, 214, 255]
const GENERATOR_MODEL_URL = '/models/generator/generator.glb'
const GENERATOR_HALO_OFFSET_METERS: [number, number] = [0, 0]
const GENERATOR_HITBOX_HALF_SIZE_METERS = 64
const VIEW_BOUNDS_PADDING_DEGREES = 0.05

function scalarProperties(source: Record<string, unknown>): GridSelection['properties'] {
  const result: GridSelection['properties'] = {}
  for (const [key, value] of Object.entries(source)) {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || value === null) {
      result[key] = value
    }
  }
  return result
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function inViewBounds(coordinates: [number, number], bounds: ViewBounds | null): boolean {
  if (!bounds) return true
  const [longitude, latitude] = coordinates
  return longitude >= bounds.west - VIEW_BOUNDS_PADDING_DEGREES
    && longitude <= bounds.east + VIEW_BOUNDS_PADDING_DEGREES
    && latitude >= bounds.south - VIEW_BOUNDS_PADDING_DEGREES
    && latitude <= bounds.north + VIEW_BOUNDS_PADDING_DEGREES
}

function colocatedOffset(index: number, total: number): [number, number] {
  if (total <= 1 || index < 0) return [0, 0]
  const radius = total <= 4 ? 118 : 168
  const angle = (Math.PI * 2 * index) / total - Math.PI / 2
  return [Math.cos(angle) * radius, Math.sin(angle) * radius]
}

function generatorFieldOffset(index: number, total: number): [number, number] {
  if (total <= 1 || index < 0) return [0, 240]
  const columns = Math.min(6, Math.ceil(Math.sqrt(total)))
  const row = Math.floor(index / columns)
  const column = index % columns
  const visibleColumns = Math.min(columns, total - row * columns)
  const spacing = 128
  const eastMeters = (column - (visibleColumns - 1) / 2) * spacing
  const northMeters = 240 + row * spacing
  return [eastMeters, northMeters]
}

function countByAnchor(topology: TopologyData): Map<string, string[]> {
  const anchors = new Map<string, string[]>()
  for (const bus of topology.buses) anchors.set(bus.id, [`bus:${bus.id}`])
  for (const generator of topology.generators) {
    const keys = anchors.get(generator.bus_name) ?? []
    keys.push(`generator:${generator.id}`)
    anchors.set(generator.bus_name, keys)
  }
  for (const load of topology.loads) {
    const keys = anchors.get(load.bus_name) ?? []
    keys.push(`load:${load.id}`)
    anchors.set(load.bus_name, keys)
  }
  for (const [anchor, keys] of anchors) anchors.set(anchor, keys.sort())
  return anchors
}

function withOffset(coordinates: [number, number], offset: [number, number]): [number, number] {
  const [eastMeters, northMeters] = offset
  const metersPerDegreeLatitude = 111_320
  const metersPerDegreeLongitude = metersPerDegreeLatitude * Math.cos((coordinates[1] * Math.PI) / 180)
  return [
    coordinates[0] + eastMeters / metersPerDegreeLongitude,
    coordinates[1] + northMeters / metersPerDegreeLatitude,
  ]
}

function metersToLngLat(coordinates: [number, number], eastMeters: number, northMeters: number): [number, number] {
  const metersPerDegreeLatitude = 111_320
  const metersPerDegreeLongitude = metersPerDegreeLatitude * Math.cos((coordinates[1] * Math.PI) / 180)
  return [
    coordinates[0] + eastMeters / metersPerDegreeLongitude,
    coordinates[1] + northMeters / metersPerDegreeLatitude,
  ]
}

function squareFootprint(center: [number, number], halfSizeMeters: number, elevation: number): [number, number, number][] {
  return [
    [...metersToLngLat(center, -halfSizeMeters, -halfSizeMeters), elevation],
    [...metersToLngLat(center, halfSizeMeters, -halfSizeMeters), elevation],
    [...metersToLngLat(center, halfSizeMeters, halfSizeMeters), elevation],
    [...metersToLngLat(center, -halfSizeMeters, halfSizeMeters), elevation],
  ]
}

function createDatum(
  type: NodeBuildingType,
  id: string,
  source: Bus | Generator | Load | Record<string, unknown>,
  anchorCoordinates: [number, number],
  anchorKeys: string[],
  getTerrainElevation: (coordinates: [number, number]) => number,
  extraProperties: GridSelection['properties'],
  offsetOverride?: [number, number],
  viewBounds?: ViewBounds | null,
): NodeBuildingDatum | null {
  const key = `${type}:${id}`
  const offset = offsetOverride ?? colocatedOffset(anchorKeys.indexOf(key), anchorKeys.length)
  const coordinates = withOffset(anchorCoordinates, offset)
  if (!inViewBounds(coordinates, viewBounds ?? null)) return null
  const style = TYPE_STYLE[type]
  const elevation = getTerrainElevation(coordinates)
  const baseElevation = elevation + 1.5

  return {
    key,
    type,
    id,
    coordinates,
    position: [coordinates[0], coordinates[1], baseElevation],
    footprint: squareFootprint(coordinates, style.radius, baseElevation),
    height: style.height,
    color: style.color,
    properties: {
      ...scalarProperties(source),
      ...extraProperties,
      id,
      key,
      type,
      longitude: anchorCoordinates[0],
      latitude: anchorCoordinates[1],
    },
  }
}

export function NodeBuildingsLayer({
  topology,
  snapshot,
  map,
  terrainVersion,
  viewBounds,
  selectedKey,
  enabledTypes,
  onHoverKey,
  onPick,
}: NodeBuildingsLayerProps) {
  const selectedKeyRef = useRef(selectedKey)

  useEffect(() => {
    selectedKeyRef.current = selectedKey
  }, [selectedKey])
  const data = useMemo(() => {
    const busesById = new Map(topology.buses.map((bus) => [bus.id, bus]))
    const generatorsByBus = new Map<string, Generator[]>()
    for (const generator of topology.generators) {
      const generators = generatorsByBus.get(generator.bus_name) ?? []
      generators.push(generator)
      generatorsByBus.set(generator.bus_name, generators)
    }
    const snapshotBusMap = new Map(snapshot?.buses.map((bus) => [bus.id, bus]) ?? [])
    const anchors = countByAnchor(topology)
    const items: NodeBuildingDatum[] = []
    const terrainCache = new Map<string, number>()
    const queryable = map as TerrainMap | null
    const getTerrainElevation = (coordinates: [number, number]): number => {
      const cacheKey = `${coordinates[0].toFixed(5)},${coordinates[1].toFixed(5)}`
      const cached = terrainCache.get(cacheKey)
      if (cached != null) return cached
      const elevation = queryable?.queryTerrainElevation?.(coordinates, { exaggerated: true }) ?? 0
      terrainCache.set(cacheKey, elevation)
      return elevation
    }
    const pushDatum = (datum: NodeBuildingDatum | null) => {
      if (datum) items.push(datum)
    }

    for (const bus of topology.buses) {
      const snapshotBus = snapshotBusMap.get(bus.id)
      const anchorKeys = anchors.get(bus.id) ?? []

      if (anchorKeys.length >= 3) {
        const generators = topology.generators.filter((generator) => generator.bus_name === bus.id)
        const loads = topology.loads.filter((load) => load.bus_name === bus.id)
        const installedCapacityMw = generators.reduce((sum, generator) => sum + numberValue(generator.installed_capacity_mw ?? generator.max_p_mw), 0)
        const minOutputMw = generators.reduce((sum, generator) => sum + numberValue(generator.min_output_mw ?? generator.min_p_mw), 0)
        const maxOutputMw = generators.reduce((sum, generator) => sum + numberValue(generator.max_output_mw ?? generator.max_p_mw), 0)
        const flexRangeMw = Math.max(maxOutputMw - minOutputMw, 0)
        const reserveCapableCount = generators.filter((generator) => generator.reserve_capable === true || generator.reserve_capable === 'true' || generator.reserve_capable === 'True').length
        const criticalLoadCount = loads.filter((load) => load.critical_infrastructure === true || load.critical_infrastructure === 'true' || load.critical_infrastructure === 'True').length
        const demandResponseCount = loads.filter((load) => load.demand_response_capable === true || load.demand_response_capable === 'true' || load.demand_response_capable === 'True').length
        if (enabledTypes.cluster) pushDatum(createDatum('cluster', bus.id, bus, bus.coordinates, ['cluster'], getTerrainElevation, {
          color: '#8B5CF6',
          display_name: `Cluster at ${bus.id}`,
          title: `Cluster at ${bus.id}`,
          bus_name: bus.id,
          node_count: anchorKeys.length,
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
          generator_ids: generators.map((generator) => generator.id).join(', '),
          load_ids: loads.map((load) => load.id).join(', '),
        }, undefined, viewBounds))
      }

      if (enabledTypes.bus) pushDatum(createDatum('bus', bus.id, bus, bus.coordinates, anchorKeys, getTerrainElevation, {
        color: '#FF6B6B',
        region: bus.region,
        v_kV: bus.v_kV,
        vm_pu: snapshotBus?.vm_pu ?? null,
        p_mw: snapshotBus?.p_mw ?? null,
      }, undefined, viewBounds))
    }

    if (enabledTypes.generator) for (const generator of topology.generators) {
      const bus = busesById.get(generator.bus_name)
      if (!bus) continue
      const anchorKeys = anchors.get(generator.bus_name) ?? []
      const generatorGroup = generatorsByBus.get(generator.bus_name) ?? []
      const offset = anchorKeys.length >= 3
        ? generatorFieldOffset(generatorGroup.findIndex((item) => item.id === generator.id), generatorGroup.length)
        : undefined
      pushDatum(createDatum('generator', generator.id, generator, bus.coordinates, anchorKeys, getTerrainElevation, {
        color: '#FFD93D',
        bus_name: generator.bus_name,
      }, offset, viewBounds))
    }

    if (enabledTypes.load) for (const load of topology.loads) {
      const bus = busesById.get(load.bus_name)
      if (!bus) continue
      pushDatum(createDatum('load', load.id, load, bus.coordinates, anchors.get(load.bus_name) ?? [], getTerrainElevation, {
        color: '#95E1D3',
        bus_name: load.bus_name,
      }, undefined, viewBounds))
    }

    return items
  }, [enabledTypes.bus, enabledTypes.cluster, enabledTypes.generator, enabledTypes.load, map, snapshot, terrainVersion, topology, viewBounds])

  const handleHover = (info: PickingInfo<NodeBuildingDatum>) => {
    onHoverKey(info.object?.key ?? null)
  }

  const handleClick = (info: PickingInfo<NodeBuildingDatum>) => {
    if (!info.object) return
    const relatedProperties = data
      .filter((datum) => datum.properties.longitude === info.object?.properties.longitude && datum.properties.latitude === info.object?.properties.latitude)
      .map((datum) => datum.properties)
    onPick(info.object.properties, relatedProperties)
  }

  const dataByType = useMemo(() => {
    const grouped: Record<NodeBuildingType, NodeBuildingDatum[]> = {
      bus: [],
      generator: [],
      load: [],
      cluster: [],
    }
    for (const datum of data) grouped[datum.type].push(datum)
    return grouped
  }, [data])

  const layers = useMemo(() => {
    const polygonLayers = (Object.keys(TYPE_STYLE) as NodeBuildingType[])
      .filter((type) => type !== 'generator')
      .filter((type) => enabledTypes[type])
      .map((type) => new PolygonLayer<NodeBuildingDatum>({
        id: `grid-node-buildings-${type}`,
        data: dataByType[type],
        extruded: true,
        wireframe: false,
        getPolygon: (datum) => datum.footprint,
        getElevation: (datum) => datum.key === selectedKey ? datum.height * 1.12 : datum.height,
        getFillColor: (datum) => datum.key === selectedKey ? SELECTED_COLOR : datum.color,
        getLineColor: (datum) => datum.key === selectedKey ? [255, 255, 255, 255] : [28, 27, 27, 175],
        getLineWidth: (datum) => datum.key === selectedKey ? 2.5 : 1,
        lineWidthMinPixels: 1.2,
        stroked: true,
        filled: true,
        pickable: true,
        autoHighlight: true,
        highlightColor: HOVER_COLOR,
        material: {
          ambient: 0.38,
          diffuse: 0.65,
          shininess: 24,
          specularColor: [255, 255, 255],
        },
        transitions: {
          getFillColor: 120,
          getLineColor: 120,
        },
        onHover: handleHover,
        onClick: handleClick,
        updateTriggers: {
          getFillColor: [selectedKey],
          getLineColor: [selectedKey],
          getLineWidth: [selectedKey],
          getElevation: [selectedKey],
        },
      }))

    const generatorHitboxLayer = new PolygonLayer<NodeBuildingDatum>({
      id: 'grid-node-buildings-generator-hitboxes',
      data: dataByType.generator,
      extruded: false,
      wireframe: false,
      getPolygon: (datum) => squareFootprint(withOffset(datum.coordinates, GENERATOR_HALO_OFFSET_METERS), GENERATOR_HITBOX_HALF_SIZE_METERS, datum.position[2] + 0.6),
      getFillColor: [0, 0, 0, 0],
      getLineColor: [0, 0, 0, 0],
      getLineWidth: 0,
      stroked: false,
      filled: true,
      pickable: true,
      autoHighlight: true,
      highlightColor: HOVER_COLOR,
      onHover: handleHover,
      onClick: handleClick,
    })

    const generatorHaloLayer = new PolygonLayer<NodeBuildingDatum>({
      id: 'grid-node-buildings-generator-halo',
      data: dataByType.generator.filter((datum) => datum.key === selectedKey),
      extruded: false,
      wireframe: false,
      getPolygon: (datum) => squareFootprint(withOffset(datum.coordinates, GENERATOR_HALO_OFFSET_METERS), GENERATOR_HITBOX_HALF_SIZE_METERS, datum.position[2] + 0.2),
      getFillColor: GENERATOR_SELECTED_HALO,
      getLineColor: [255, 255, 255, 230],
      getLineWidth: 3,
      lineWidthMinPixels: 2,
      stroked: true,
      filled: true,
      pickable: false,
      transitions: {
        getFillColor: 100,
        getLineColor: 100,
      },
    })

    const generatorLayer = enabledTypes.generator
      ? new ScenegraphLayer<NodeBuildingDatum>({
        id: 'grid-node-buildings-generator-models',
        data: dataByType.generator,
        scenegraph: GENERATOR_MODEL_URL,
        getPosition: (datum) => datum.position,
        getOrientation: [0, -90, 90],
        getScale: (datum) => datum.key === selectedKey ? [1020, 1020, 1020] : [920, 920, 920],
        getColor: (datum) => datum.key === selectedKey ? SELECTED_COLOR : [255, 217, 61, 235],
        sizeScale: 1,
        pickable: false,
        _lighting: 'pbr',
        transitions: {
          getColor: 120,
          getScale: 120,
        },
        updateTriggers: {
          getColor: [selectedKey],
          getScale: [selectedKey],
        },
      })
      : null

    return generatorLayer ? [generatorHitboxLayer, generatorHaloLayer, ...polygonLayers, generatorLayer] : polygonLayers
  }, [dataByType, enabledTypes, selectedKey])

  return <DeckOverlay layers={layers} interleaved={false} onHover={(info) => { if (!info.object) onHoverKey(null) }} />
}
