import { useCallback, useEffect, useRef, useState } from 'react'
import { Layer, Map, Source } from 'react-map-gl/mapbox'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { MapStyleSwitcher } from './MapStyleSwitcher'
import { AIDynamicIsland } from './AIDynamicIsland'
import { GridLayer } from './GridLayer'
import { NodeBuildingsLayer } from './NodeBuildingsLayer'
import { MapDetailsPanel } from './MapDetailsPanel'
import { NodeTypeFilter, type NodeFilterType } from './NodeTypeFilter'
import { CZECH_BOUNDARY, CZECH_LABELS } from '../data/czech-geodata'
import CZECH_MASK from '../data/czech-mask.json'
import { getTopology, getSnapshots, getSnapshot } from '../api/grid'
import type { TopologyData, SnapshotData, GridElementType, GridSelection } from '../types/grid'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN as string
const MAPBOX_TERRAIN_SOURCE_ID = 'mapbox-dem'
const CZECH_BOUNDARY_LAYER_ID = 'cz-boundary-outline'
const CZECH_LABEL_LAYER_ID = 'cz-operator-labels'
const HILLSHADE_LAYER_ID = 'cz-hillshade'
const MASK_LAYER_ID = 'cz-mask'
const VIEW_2D = { pitch: 0, bearing: 0 }
const VIEW_3D = { pitch: 60, bearing: -28 }
const NODE_BUILDING_ZOOM = 13.0
const NODE_BUILDING_FOCUS_ZOOM = 14.4
type ViewBounds = {
  west: number
  south: number
  east: number
  north: number
}
const GRID_INTERACTIVE_LAYER_IDS = [
  'grid-clusters-circle',
  'grid-clusters-label',
  'grid-generators-circle',
  'grid-loads-circle',
  'grid-buses-circle',
  'grid-branches-hit',
  'grid-branches-line',
]

const REGION_COLORS: Record<string, string> = {
  r1: '#FF6B6B',
  r2: '#4ECDC4',
  r3: '#45B7D1',
}

const DEFAULT_NODE_FILTERS: Record<NodeFilterType, boolean> = {
  cluster: true,
  bus: true,
  generator: true,
  load: true,
}

function loadingColor(loadingPercent: number): string {
  if (loadingPercent < 70) return '#22C55E'
  if (loadingPercent <= 90) return '#EAB308'
  return '#EF4444'
}

function scalarProperties(source: Record<string, unknown>): GridSelection['properties'] {
  const result: GridSelection['properties'] = {}
  for (const [key, value] of Object.entries(source)) {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || value === null) {
      result[key] = value
    }
  }
  return result
}

interface MapViewProps {
  mapStyle: string
  onStyleChange: (style: string) => void
}

export function MapView({ mapStyle, onStyleChange }: MapViewProps) {
  const mapRef = useRef<any>(null)
  const [is3d, setIs3d] = useState(false)
  const [topology, setTopology] = useState<TopologyData | null>(null)
  const [snapshots, setSnapshots] = useState<string[]>([])
  const [selectedTimestamp, setSelectedTimestamp] = useState<string | null>(null)
  const [snapshotData, setSnapshotData] = useState<SnapshotData | null>(null)
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)
  const [selectedItem, setSelectedItem] = useState<GridSelection | null>(null)
  const [selectionStack, setSelectionStack] = useState<GridSelection[]>([])
  const [terrainVersion, setTerrainVersion] = useState(0)
  const [mapZoom, setMapZoom] = useState(6.5)
  const [viewBounds, setViewBounds] = useState<ViewBounds | null>(null)
  const [enabledTypes, setEnabledTypes] = useState<Record<NodeFilterType, boolean>>(DEFAULT_NODE_FILTERS)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetchData() {
      try {
        const [topo, snaps] = await Promise.all([getTopology(), getSnapshots()])
        setTopology(topo)
        setSnapshots(snaps)
        if (snaps.length > 0) {
          setSelectedTimestamp(snaps[0])
        }
      } catch (err) {
        console.error('Failed to fetch grid data:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  useEffect(() => {
    if (!selectedTimestamp) {
      setSnapshotData(null)
      return
    }
    let cancelled = false
    async function fetchSnapshot() {
      try {
        const data = await getSnapshot(selectedTimestamp!)
        if (!cancelled) setSnapshotData(data)
      } catch (err) {
        console.error('Failed to fetch snapshot:', err)
      }
    }
    fetchSnapshot()
    return () => { cancelled = true }
  }, [selectedTimestamp])

  const terrain = is3d ? { source: MAPBOX_TERRAIN_SOURCE_ID, exaggeration: 1.5 } : undefined
  const fog = is3d ? {
    range: [0.5, 8] as [number, number],
    color: '#dc9f9f',
    'high-color': '#245bde',
    'horizon-blend': 0.3,
    'space-color': '#000000',
    'star-intensity': 0.0,
  } : undefined

  const handleMapLoad = useCallback(() => {
    const map = mapRef.current?.getMap?.()
    if (typeof map?.getZoom === 'function') setMapZoom(map.getZoom())
    if (typeof map?.getBounds === 'function') {
      const bounds = map.getBounds()
      setViewBounds({ west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth() })
    }
    map?.jumpTo(is3d ? VIEW_3D : VIEW_2D)
    setTerrainVersion((version) => version + 1)
  }, [is3d])

  const updateViewBounds = useCallback(() => {
    const map = mapRef.current?.getMap?.()
    if (!map || typeof map.getBounds !== 'function') return
    const bounds = map.getBounds()
    setViewBounds({ west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth() })
  }, [])

  const handleNodeTypeFilterChange = useCallback((type: NodeFilterType, enabled: boolean) => {
    setEnabledTypes((current) => ({ ...current, [type]: enabled }))
  }, [])

  const handleViewModeChange = useCallback((enabled: boolean) => {
    const map = mapRef.current?.getMap?.()
    if (!map) {
      setIs3d(enabled)
      return
    }

    if (enabled) {
      setIs3d(true)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          map.easeTo({
            ...VIEW_3D,
            duration: 750,
            essential: true,
          })
        })
      })
      return
    }

    map.once('moveend', () => {
      setIs3d(false)
    })
    map.easeTo({
      ...VIEW_2D,
      duration: 750,
      essential: true,
    })
  }, [])

  const buildSelection = useCallback((properties: Record<string, unknown>): GridSelection | null => {
    const type = properties.type
    const id = properties.id
    const key = properties.key

    if (typeof type !== 'string' || typeof id !== 'string' || typeof key !== 'string') return null
    if (!['bus', 'branch', 'generator', 'load', 'cluster'].includes(type)) return null

    const safeProperties: GridSelection['properties'] = {}
    for (const [propKey, value] of Object.entries(properties)) {
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' || value === null) {
        safeProperties[propKey] = value
      }
    }

    const subtitleByType: Record<GridElementType, string> = {
      bus: `${safeProperties.region ?? 'Unknown region'} · ${safeProperties.v_kV ?? 'N/A'} kV`,
      branch: `${safeProperties.from_bus ?? 'Unknown'} → ${safeProperties.to_bus ?? 'Unknown'}`,
      generator: `Connected to ${safeProperties.bus_name ?? 'unknown bus'}`,
      load: `Connected to ${safeProperties.bus_name ?? 'unknown bus'}`,
      cluster: `${safeProperties.node_count ?? 'Multiple'} colocated grid assets`,
    }

    return {
      key,
      type: type as GridElementType,
      title: type === 'cluster' && typeof safeProperties.display_name === 'string' ? safeProperties.display_name : id,
      subtitle: subtitleByType[type as GridElementType],
      color: typeof properties.color === 'string' ? properties.color : '#1E40AF',
      properties: safeProperties,
    }
  }, [])

  const buildTopologySelection = useCallback((type: GridElementType, id: string): GridSelection | null => {
    if (!topology) return null

    if (type === 'bus') {
      const bus = topology.buses.find((item) => item.id === id)
      if (!bus) return null
      const snapshotBus = snapshotData?.buses.find((item) => item.id === id)
      return buildSelection({
        ...scalarProperties(bus),
        id: bus.id,
        key: `bus:${bus.id}`,
        type: 'bus',
        color: REGION_COLORS[bus.region] ?? '#999999',
        v_kV: bus.v_kV,
        longitude: bus.coordinates[0],
        latitude: bus.coordinates[1],
        vm_pu: snapshotBus?.vm_pu ?? null,
        p_mw: snapshotBus?.p_mw ?? null,
      })
    }

    if (type === 'branch') {
      const branch = topology.branches.find((item) => item.id === id)
      if (!branch) return null
      const loadingPercent = snapshotData?.branches.find((item) => item.id === id)?.loading_percent ?? 0
      const fromCoordinates = branch.coordinates[0]
      const toCoordinates = branch.coordinates[branch.coordinates.length - 1]
      return buildSelection({
        ...scalarProperties(branch),
        id: branch.id,
        key: `branch:${branch.id}`,
        type: 'branch',
        color: loadingColor(loadingPercent),
        loading_percent: loadingPercent,
        from_longitude: fromCoordinates[0],
        from_latitude: fromCoordinates[1],
        to_longitude: toCoordinates[0],
        to_latitude: toCoordinates[1],
      })
    }

    if (type === 'generator') {
      const generator = topology.generators.find((item) => item.id === id)
      const bus = generator ? topology.buses.find((item) => item.id === generator.bus_name) : null
      if (!generator || !bus) return null
      return buildSelection({
        ...scalarProperties(generator),
        id: generator.id,
        key: `generator:${generator.id}`,
        type: 'generator',
        color: '#FFD93D',
        longitude: bus.coordinates[0],
        latitude: bus.coordinates[1],
      })
    }

    const load = topology.loads.find((item) => item.id === id)
    const bus = load ? topology.buses.find((item) => item.id === load.bus_name) : null
    if (!load || !bus) return null
    return buildSelection({
      ...scalarProperties(load),
      id: load.id,
      key: `load:${load.id}`,
      type: 'load',
      color: '#95E1D3',
      longitude: bus.coordinates[0],
      latitude: bus.coordinates[1],
    })
  }, [buildSelection, snapshotData, topology])

  const zoomToSelection = useCallback((selection: GridSelection, targetZoom = NODE_BUILDING_ZOOM) => {
    if (!topology) return
    const map = mapRef.current?.getMap?.()
    if (!map) return

    if (selection.type === 'branch') {
      const branch = topology.branches.find((item) => item.id === selection.title)
      if (!branch || branch.coordinates.length === 0) return
      const bounds = branch.coordinates.reduce((acc, coordinate) => acc.extend(coordinate as [number, number]), new mapboxgl.LngLatBounds(branch.coordinates[0] as [number, number], branch.coordinates[0] as [number, number]))
      map.fitBounds(bounds, { padding: { top: 90, bottom: 90, left: 120, right: 440 }, duration: 850, maxZoom: 9.5 })
      return
    }

    const longitude = selection.properties.longitude
    const latitude = selection.properties.latitude
    if (typeof longitude !== 'number' || typeof latitude !== 'number') return
    map.easeTo({ center: [longitude, latitude], zoom: Math.max(map.getZoom(), targetZoom), duration: 850, essential: true })
  }, [topology])

  const handleReferenceSelect = useCallback((referenceId: string) => {
    if (!topology) return
    const candidates: Array<[GridElementType, boolean]> = [
      ['bus', topology.buses.some((item) => item.id === referenceId)],
      ['branch', topology.branches.some((item) => item.id === referenceId)],
      ['generator', topology.generators.some((item) => item.id === referenceId)],
      ['load', topology.loads.some((item) => item.id === referenceId)],
    ]
    const match = candidates.find(([, exists]) => exists)
    if (!match) return
    const selection = buildTopologySelection(match[0], referenceId)
    if (!selection) return
    setSelectionStack([selection])
    setSelectedItem(selection)
    zoomToSelection(selection)
  }, [buildTopologySelection, topology, zoomToSelection])

  const buildClusterSelectionStack = useCallback((clusterSelection: GridSelection, extraSelections: GridSelection[] = []) => {
    if (!topology) return [clusterSelection]
    const busName = clusterSelection.properties.bus_name
    if (typeof busName !== 'string') return [clusterSelection, ...extraSelections]

    const stack: GridSelection[] = [clusterSelection]
    const busSelection = buildTopologySelection('bus', busName)
    if (busSelection) stack.push(busSelection)

    for (const generator of topology.generators.filter((item) => item.bus_name === busName)) {
      const generatorSelection = buildTopologySelection('generator', generator.id)
      if (generatorSelection) stack.push(generatorSelection)
    }

    for (const load of topology.loads.filter((item) => item.bus_name === busName)) {
      const loadSelection = buildTopologySelection('load', load.id)
      if (loadSelection) stack.push(loadSelection)
    }

    for (const extraSelection of extraSelections) stack.push(extraSelection)

    const seen = new Set<string>()
    return stack.filter((selection) => {
      if (seen.has(selection.key)) return false
      seen.add(selection.key)
      return true
    })
  }, [buildTopologySelection, topology])

  useEffect(() => {
    if (!selectedItem) return
    const [type, id] = selectedItem.key.split(':')
    if (!id || !['bus', 'branch', 'generator', 'load', 'cluster'].includes(type)) return

    if (type === 'cluster') return

    const refreshedSelection = buildTopologySelection(type as GridElementType, id)
    if (refreshedSelection) {
      setSelectedItem(refreshedSelection)
      setSelectionStack((items) => items.map((item) => item.key === refreshedSelection.key ? refreshedSelection : item))
    }
  }, [buildTopologySelection, selectedItem?.key])

  const handleMapClick = useCallback((event: any) => {
    const map = mapRef.current?.getMap?.()
    const point = event.point
    let renderedFeatures: any[] = []
    try {
      if (map && point) {
        const style = map.getStyle()
        const existingLayers = new Set((style?.layers ?? []).map((l: any) => l.id))
        const validLayerIds = GRID_INTERACTIVE_LAYER_IDS.filter((id) => existingLayers.has(id))
        renderedFeatures = map.queryRenderedFeatures(
          [[point.x - 10, point.y - 10], [point.x + 10, point.y + 10]],
          { layers: validLayerIds },
        )
      } else {
        renderedFeatures = event.features ?? []
      }
    } catch {
      renderedFeatures = event.features ?? []
    }

    const seen = new Set<string>()
    const selections: GridSelection[] = []
    for (const feature of renderedFeatures) {
      if (!feature?.properties) continue
      const selection = buildSelection(feature.properties)
      if (!selection || seen.has(selection.key)) continue
      seen.add(selection.key)
      selections.push(selection)
    }

    if (selections.length === 0) return
    selections.sort((a, b) => (a.type === 'cluster' ? 0 : 1) - (b.type === 'cluster' ? 0 : 1))
    const primarySelection = selections[0]
    const nextStack = primarySelection.type === 'cluster'
      ? buildClusterSelectionStack(primarySelection, selections.slice(1))
      : selections
    setSelectionStack(nextStack)
    setSelectedItem(primarySelection)
    if (is3d && mapZoom < NODE_BUILDING_ZOOM && primarySelection.type === 'cluster') {
      zoomToSelection(primarySelection, NODE_BUILDING_FOCUS_ZOOM)
    }
  }, [buildClusterSelectionStack, buildSelection, is3d, mapZoom, zoomToSelection])

  const handleMapMouseMove = useCallback((event: any) => {
    const feature = event.features?.[0]
    const key = feature?.properties?.key
    const map = mapRef.current?.getMap?.()
    if (typeof key === 'string') {
      setHoveredKey(key)
      if (map) map.getCanvas().style.cursor = 'pointer'
      return
    }
    setHoveredKey(null)
    if (map) map.getCanvas().style.cursor = ''
  }, [])

  const handleMapMouseLeave = useCallback(() => {
    const map = mapRef.current?.getMap?.()
    setHoveredKey(null)
    if (map) map.getCanvas().style.cursor = ''
  }, [])

  const handleNodeBuildingHover = useCallback((key: string | null) => {
    const map = mapRef.current?.getMap?.()
    setHoveredKey(key)
    if (map) map.getCanvas().style.cursor = key ? 'pointer' : ''
  }, [])

  const handleNodeBuildingPick = useCallback((properties: GridSelection['properties'], relatedProperties: GridSelection['properties'][]) => {
    setHoveredKey(null)
    const primaryProperties = properties.type === 'cluster'
      ? relatedProperties.find((candidate) => candidate.type === 'cluster') ?? properties
      : properties
    const selection = buildSelection(primaryProperties)
    if (!selection) return
    const seen = new Set<string>()
    const relatedSelections: GridSelection[] = []
    for (const candidateProperties of relatedProperties) {
      const candidateSelection = buildSelection(candidateProperties)
      if (!candidateSelection || seen.has(candidateSelection.key)) continue
      seen.add(candidateSelection.key)
      relatedSelections.push(candidateSelection)
    }
    if (!seen.has(selection.key)) relatedSelections.unshift(selection)
    const nextStack = selection.type === 'cluster'
      ? buildClusterSelectionStack(selection, relatedSelections.filter((item) => item.type === 'branch'))
      : relatedSelections
    setSelectionStack(nextStack.length > 0 ? nextStack : [selection])
    setSelectedItem(selection)
  }, [buildClusterSelectionStack, buildSelection])

  return (
    <div className="relative h-full w-full">
      <Map
        ref={mapRef}
        key={mapStyle}
        mapboxAccessToken={MAPBOX_TOKEN}
        initialViewState={{
          longitude: 15.5,
          latitude: 49.8,
          zoom: 6.5,
          pitch: is3d ? VIEW_3D.pitch : VIEW_2D.pitch,
          bearing: is3d ? VIEW_3D.bearing : VIEW_2D.bearing,
        }}
        terrain={terrain}
        fog={fog}
        style={{ width: '100%', height: '100%' }}
        mapStyle={`mapbox://styles/mapbox/${mapStyle}`}
        mapLib={mapboxgl}
        onLoad={handleMapLoad}
        interactiveLayerIds={GRID_INTERACTIVE_LAYER_IDS}
        onClick={handleMapClick}
        onMouseMove={handleMapMouseMove}
        onMouseLeave={handleMapMouseLeave}
        onMoveEnd={() => {
          updateViewBounds()
          setTerrainVersion((version) => version + 1)
        }}
        onMove={(event) => setMapZoom(event.viewState.zoom)}
      >
        <Source id={MAPBOX_TERRAIN_SOURCE_ID} type="raster-dem" url="mapbox://mapbox.mapbox-terrain-dem-v1" tileSize={512} maxzoom={14} />
        {is3d && (
          <Layer
            id={HILLSHADE_LAYER_ID}
            type="hillshade"
            source={MAPBOX_TERRAIN_SOURCE_ID}
            layout={{ visibility: 'visible' }}
            paint={{
              'hillshade-exaggeration': 0.6,
              'hillshade-illumination-direction': 315,
              'hillshade-shadow-color': '#1C1B1B',
              'hillshade-highlight-color': '#FCF9F8',
              'hillshade-accent-color': '#6B6B6B',
            }}
            beforeId={CZECH_BOUNDARY_LAYER_ID}
          />
        )}
        <Source id="cz-mask-source" type="geojson" data={CZECH_MASK as any}>
          <Layer
            id={MASK_LAYER_ID}
            type="fill"
            paint={{
              'fill-color': '#1C1B1B',
              'fill-opacity': 0.45,
            }}
          />
        </Source>
        <Source id="cz-boundary-source" type="geojson" data={CZECH_BOUNDARY as any}>
          <Layer
            id={CZECH_BOUNDARY_LAYER_ID}
            type="line"
            paint={{
              'line-color': '#1C1B1B',
              'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 8, 1.1, 11, 1.8],
              'line-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.24, 8, 0.42, 11, 0.55],
            }}
          />
        </Source>
        <Source id="cz-operator-label-source" type="geojson" data={CZECH_LABELS as any}>
          <Layer
            id={CZECH_LABEL_LAYER_ID}
            type="symbol"
            filter={[
              'step',
              ['zoom'],
              ['<=', ['get', 'rank'], 1],
              6,
              ['<=', ['get', 'rank'], 2],
              7,
              ['<=', ['get', 'rank'], 3],
              8,
              ['<=', ['get', 'rank'], 4],
              9,
              ['<=', ['get', 'rank'], 5],
              10,
              ['<=', ['get', 'rank'], 6],
            ] as any}
            layout={{
              'text-field': ['get', 'label'],
              'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
              'text-size': [
                'interpolate',
                ['linear'],
                ['zoom'],
                5,
                ['*', ['get', 'textSize'], 0.82],
                9,
                ['get', 'textSize'],
                12,
                ['*', ['get', 'textSize'], 1.18],
              ],
              'text-variable-anchor': ['top', 'bottom', 'left', 'right', 'top-left', 'top-right', 'bottom-left', 'bottom-right'],
              'text-radial-offset': 0.45,
              'text-justify': 'auto',
              'text-max-width': 9,
              'text-padding': 2,
              'text-allow-overlap': false,
              visibility: 'visible',
            }}
            paint={{
              'text-color': '#1C1B1B',
              'text-halo-color': '#FCF9F8',
              'text-halo-width': 1.6,
              'text-halo-blur': 0.4,
            }}
          />
        </Source>
        {topology && is3d && mapZoom >= NODE_BUILDING_ZOOM && (
          <NodeBuildingsLayer
            topology={topology}
            snapshot={snapshotData}
            map={mapRef.current?.getMap?.() ?? null}
            terrainVersion={terrainVersion}
            viewBounds={viewBounds}
            selectedKey={selectedItem?.key ?? null}
            enabledTypes={enabledTypes}
            onHoverKey={handleNodeBuildingHover}
            onPick={handleNodeBuildingPick}
          />
        )}
        {topology && (
          <GridLayer
            topology={topology}
            snapshot={snapshotData}
            hoveredKey={hoveredKey}
            selectedKey={selectedItem?.key ?? null}
            hideNodeLayers={is3d && mapZoom >= NODE_BUILDING_ZOOM}
            enabledTypes={enabledTypes}
          />
        )}
      </Map>
      <MapDetailsPanel
        selection={selectedItem}
        onClose={() => {
          setSelectedItem(null)
          setSelectionStack([])
          setHoveredKey(null)
        }}
        onReferenceSelect={handleReferenceSelect}
        relatedSelections={selectionStack}
        onSelectionChange={(selection) => {
          setSelectedItem(selection)
          setHoveredKey(null)
        }}
      />
      <MapStyleSwitcher
        currentStyle={mapStyle}
        onChange={onStyleChange}
        is3d={is3d}
        onViewModeChange={handleViewModeChange}
      />
      <NodeTypeFilter
        enabledTypes={enabledTypes}
        onChange={handleNodeTypeFilterChange}
      />
      <AIDynamicIsland />
      {loading && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-surface/60 backdrop-blur-sm">
          <div className="rounded-xl bg-surface-low px-6 py-4">
            <div className="flex items-center gap-3">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <span className="font-body text-sm text-on-background">Loading grid data...</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
