import { useEffect, useRef } from "react"
import type { CSSProperties } from "react"
import maplibregl from "maplibre-gl"
import type { FeatureCollection } from "./api"

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] }

// 基底底图瓦片模板。默认 OSM，可通过 env 换为内网瓦片/天地图。
// 以拼接方式书写默认值，避免构建工具将完整 URL 误当作占位符压缩。
const DEFAULT_TILES =
  "https://" + "tile.openstreetmap.org/" + "{z}/{x}/{y}.png"
const BASEMAP_TILES = (import.meta.env.VITE_BASEMAP_TILES as string) || DEFAULT_TILES

const RASTER_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: [BASEMAP_TILES],
      tileSize: 256,
      attribution: (import.meta.env.VITE_BASEMAP_ATTR as string) || "© OpenStreetMap",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
}

const OBS_SOURCE = "observations"
const CONTAINER_STYLE: CSSProperties = { position: "absolute", inset: 0 }

export default function MapView({ data }: { data: FeatureCollection | null }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)

  // 仅初始化一次地图实例。
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: RASTER_STYLE,
      center: [110.3, 21.5],
      zoom: 9,
    })
    map.addControl(new maplibregl.NavigationControl({}), "top-right")
    map.on("load", () => {
      map.addSource(OBS_SOURCE, { type: "geojson", data: EMPTY })
      map.addLayer({
        id: "obs-crowns",
        type: "fill",
        source: OBS_SOURCE,
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": "#2e8b57",
          "fill-opacity": 0.25,
          "fill-outline-color": "#1a5c38",
        },
      })
      map.addLayer({
        id: "obs-points",
        type: "circle",
        source: OBS_SOURCE,
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 2, 16, 6],
          "circle-color": "#2e8b57",
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 0.5,
          "circle-opacity": 0.85,
        },
      })
    })
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // 数据变化时更新图层并自适应缩放。
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const apply = () => {
      const src = map.getSource(OBS_SOURCE) as maplibregl.GeoJSONSource | undefined
      if (!src) return
      const fc = data ?? EMPTY
      src.setData(fc as unknown as GeoJSON.FeatureCollection)
      const b = boundsOf(fc)
      if (b) map.fitBounds(b, { padding: 40, maxZoom: 18, duration: 600 })
    }
    if (map.isStyleLoaded()) apply()
    else map.once("idle", apply)
  }, [data])

  return <div ref={containerRef} style={CONTAINER_STYLE} />
}

// 由 FeatureCollection 算包围盒(仅处理 Point/Polygon，足够本场景)。
function boundsOf(fc: FeatureCollection): maplibregl.LngLatBoundsLike | null {
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity
  const visit = (coords: unknown): void => {
    const arr = coords as number[]
    if (typeof arr[0] === "number") {
      const [x, y] = arr
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    } else {
      for (const c of coords as unknown[]) visit(c)
    }
  }
  for (const f of fc.features) {
    const g = f.geometry as { coordinates?: unknown } | null
    if (g?.coordinates) visit(g.coordinates)
  }
  if (!isFinite(minX)) return null
  return [
    [minX, minY],
    [maxX, maxY],
  ]
}
