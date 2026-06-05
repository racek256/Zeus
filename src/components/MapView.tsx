import { useCallback, useRef, useState } from 'react'
import { Layer, Map, Source } from 'react-map-gl/mapbox'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { MapStyleSwitcher } from './MapStyleSwitcher'
import { CZECH_BOUNDARY, CZECH_LABELS } from '../data/czech-geodata'
import CZECH_MASK from '../data/czech-mask.json'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN as string
const MAPBOX_TERRAIN_SOURCE_ID = 'mapbox-dem'
const CZECH_BOUNDARY_LAYER_ID = 'cz-boundary-outline'
const CZECH_LABEL_LAYER_ID = 'cz-operator-labels'
const HILLSHADE_LAYER_ID = 'cz-hillshade'
const MASK_LAYER_ID = 'cz-mask'
const VIEW_2D = { pitch: 0, bearing: 0 }
const VIEW_3D = { pitch: 60, bearing: -28 }

interface MapViewProps {
  mapStyle: string
  onStyleChange: (style: string) => void
}

export function MapView({ mapStyle, onStyleChange }: MapViewProps) {
  const mapRef = useRef<any>(null)
  const [labelsEnabled, setLabelsEnabled] = useState(true)
  const [is3d, setIs3d] = useState(false)

  const terrain = is3d ? { source: MAPBOX_TERRAIN_SOURCE_ID, exaggeration: 3.5 } : undefined
  const fog = is3d ? {
    range: [0.5, 8],
    color: '#dc9f9f',
    'high-color': '#245bde',
    'horizon-blend': 0.3,
    'space-color': '#000000',
    'star-intensity': 0.0,
  } : undefined

  const applyLabelVisibility = useCallback((enabled: boolean) => {
    const map = mapRef.current?.getMap?.()
    if (!map) return

    const keepLayers = new Set([CZECH_LABEL_LAYER_ID, CZECH_BOUNDARY_LAYER_ID, MASK_LAYER_ID, HILLSHADE_LAYER_ID])

    for (const layer of map.getStyle()?.layers ?? []) {
      if (keepLayers.has(layer.id)) continue

      const isSymbol = layer.type === 'symbol'
      const isAdminBoundary = layer.type === 'line' && (
        layer.id.includes('admin') || layer.id.includes('boundary')
      )

      if (isSymbol || isAdminBoundary) {
        map.setLayoutProperty(layer.id, 'visibility', 'none')
      }
    }

    if (map.getLayer(CZECH_LABEL_LAYER_ID)) {
      map.setLayoutProperty(CZECH_LABEL_LAYER_ID, 'visibility', enabled ? 'visible' : 'none')
    }
  }, [])

  const handleMapLoad = useCallback(() => {
    applyLabelVisibility(labelsEnabled)
    const map = mapRef.current?.getMap?.()
    map?.jumpTo(is3d ? VIEW_3D : VIEW_2D)
  }, [applyLabelVisibility, is3d, labelsEnabled])

  const handleLabelsChange = useCallback((enabled: boolean) => {
    setLabelsEnabled(enabled)
    applyLabelVisibility(enabled)
  }, [applyLabelVisibility])

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
        <Source id="cz-boundary-source" type="geojson" data={CZECH_BOUNDARY}>
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
        <Source id="cz-operator-label-source" type="geojson" data={CZECH_LABELS}>
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
              visibility: labelsEnabled ? 'visible' : 'none',
            }}
            paint={{
              'text-color': '#1C1B1B',
              'text-halo-color': '#FCF9F8',
              'text-halo-width': 1.6,
              'text-halo-blur': 0.4,
            }}
          />
        </Source>
      </Map>
      <MapStyleSwitcher
        currentStyle={mapStyle}
        onChange={onStyleChange}
        labelsEnabled={labelsEnabled}
        onLabelsChange={handleLabelsChange}
        is3d={is3d}
        onViewModeChange={handleViewModeChange}
      />
    </div>
  )
}
