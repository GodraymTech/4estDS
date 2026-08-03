import {
  TerraDraw,
  TerraDrawLineStringMode,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import { cloneGeometry, type EffectiveAreaGeometry } from "../../entities/effective-area";
import { GeometryHistory } from "./history";
import { mergeGeometry, splitGeometryByLine, subtractGeometry } from "./geometryOperations";

export type GeometryEditorTool = "select" | "draw" | "add" | "hole" | "split" | "merge" | "delete";
export type GeometryChangeHandler = (geometry: EffectiveAreaGeometry) => void;

export class GeometryEditorAdapter {
  private readonly draw: TerraDraw;
  private readonly history: GeometryHistory<EffectiveAreaGeometry>;
  private readonly listeners = new Set<GeometryChangeHandler>();
  private draft: EffectiveAreaGeometry;
  private tool: GeometryEditorTool = "select";
  private rendering = false;

  constructor(map: unknown, initial: EffectiveAreaGeometry) {
    this.draft = cloneGeometry(initial);
    this.history = new GeometryHistory(initial, 100);
    this.draw = new TerraDraw({
      adapter: new TerraDrawMapLibreGLAdapter({ map }),
      modes: [
        new TerraDrawPolygonMode({
          styles: {
            fillColor: "#ff7a00",
            fillOpacity: 0.15,
            outlineColor: "#ff7a00",
            outlineWidth: 2,
          } as never,
        }),
        new TerraDrawLineStringMode({
          styles: {
            lineColor: "#ff7a00",
            lineWidth: 2.5,
          } as never,
        }),
        new TerraDrawSelectMode({
          flags: {
            polygon: {
              feature: {
                draggable: true,
                coordinates: { draggable: true, midpoints: true, deletable: true },
              },
            },
          },
          keyEvents: { delete: "Delete", deselect: "Escape", rotate: null, scale: null },
          styles: {
            selectedPolygonColor: "#ff7a00",
            selectedPolygonFillOpacity: 0.25,
            selectedPolygonOutlineColor: "#ff7a00",
            selectedPolygonOutlineWidth: 2.5,
            selectedPointColor: "#ffffff",
            selectedPointOutlineColor: "#ff7a00",
            selectedPointWidth: 8,
            selectedPointOutlineWidth: 2,
            midPointColor: "#ff7a00",
            midPointOutlineColor: "#ffffff",
            midPointWidth: 6,
            midPointOutlineWidth: 1.5,
          } as never,
        }),
      ],
    });
    this.draw.on("finish", (id) => this.finishFeature(id));
    this.draw.on("change", () => this.syncVertexEdit());
    this.draw.on("select", (id) => this.deleteSelected(id));
    this.draw.start();
    this.renderDraft(initial);
    this.draw.setMode("select");
  }

  setTool(tool: GeometryEditorTool): void {
    this.tool = tool;
    if (tool === "merge") {
      this.commit(mergeAll(this.draft));
      this.tool = "select";
      this.draw.setMode("select");
      return;
    }
    this.draw.setMode(tool === "split" ? "linestring" : ["draw", "add", "hole"].includes(tool) ? "polygon" : "select");
  }

  getDraft(): EffectiveAreaGeometry {
    return cloneGeometry(this.draft);
  }

  replaceDraft(geometry: EffectiveAreaGeometry): void {
    this.commit(geometry);
  }

  canUndo(): boolean {
    return this.history.canUndo();
  }

  canRedo(): boolean {
    return this.history.canRedo();
  }

  reset(): void {
    const geometry = this.history.reset();
    this.applyHistory(geometry);
  }

  clear(): void {
    const empty: EffectiveAreaGeometry = { type: "MultiPolygon", coordinates: [] };
    this.commit(empty);
  }

  undo(): void {
    const geometry = this.history.undo();
    if (geometry) this.applyHistory(geometry);
  }

  redo(): void {
    const geometry = this.history.redo();
    if (geometry) this.applyHistory(geometry);
  }

  destroy(): void {
    this.listeners.clear();
    this.draw.stop();
  }

  onChange(handler: GeometryChangeHandler): () => void {
    this.listeners.add(handler);
    return () => this.listeners.delete(handler);
  }

  private finishFeature(id: string | number): void {
    if (!["draw", "add", "hole", "split"].includes(this.tool)) return;
    const feature = this.draw.getSnapshotFeature(id);
    if (!feature) return;
    try {
      let next = this.draft;
      if (feature.geometry.type === "LineString" && this.tool === "split") {
        next = splitGeometryByLine(this.draft, feature.geometry.coordinates as number[][]);
      } else if (feature.geometry.type === "Polygon") {
        const polygon = feature.geometry as EffectiveAreaGeometry;
        if (this.tool === "draw") next = polygon;
        if (this.tool === "add") next = mergeGeometry(this.draft, polygon);
        if (this.tool === "hole") next = subtractGeometry(this.draft, polygon);
      }
      this.commit(next);
    } finally {
      this.tool = "select";
      this.draw.setMode("select");
    }
  }

  private syncVertexEdit(): void {
    if (this.rendering || this.tool !== "select") return;
    const geometry = geometryFromSnapshot(this.draw.getSnapshot());
    if (geometry) this.recordSnapshot(geometry);
  }

  private deleteSelected(id: string | number): void {
    if (this.tool !== "delete") return;
    this.draw.removeFeatures([id]);
    const geometry = geometryFromSnapshot(this.draw.getSnapshot());
    if (geometry) this.recordSnapshot(geometry);
    else this.renderDraft(this.draft);
  }

  private commit(geometry: EffectiveAreaGeometry): void {
    this.draft = this.history.push(geometry);
    this.renderDraft(this.draft);
    this.emit();
  }

  private recordSnapshot(geometry: EffectiveAreaGeometry): void {
    this.draft = this.history.push(geometry);
    this.emit();
  }

  private applyHistory(geometry: EffectiveAreaGeometry): void {
    this.draft = cloneGeometry(geometry);
    this.renderDraft(this.draft);
    this.emit();
  }

  private renderDraft(geometry: EffectiveAreaGeometry): void {
    this.rendering = true;
    this.draw.clear();
    const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
    this.draw.addFeatures(polygons.map((coordinates) => ({
      type: "Feature" as const,
      properties: { mode: "polygon" },
      geometry: { type: "Polygon" as const, coordinates },
    })));
    this.rendering = false;
  }

  private emit(): void {
    const geometry = this.getDraft();
    for (const listener of this.listeners) listener(geometry);
  }
}

function geometryFromSnapshot(features: ReturnType<TerraDraw["getSnapshot"]>): EffectiveAreaGeometry | null {
  const polygons = features
    .filter((feature) => feature.geometry.type === "Polygon")
    .map((feature) => feature.geometry.coordinates as EffectiveAreaGeometry["coordinates"]);
  if (!polygons.length) return null;
  if (polygons.length === 1) return { type: "Polygon", coordinates: polygons[0] as number[][][] };
  return { type: "MultiPolygon", coordinates: polygons as number[][][][] };
}

function mergeAll(geometry: EffectiveAreaGeometry): EffectiveAreaGeometry {
  if (geometry.type === "Polygon" || geometry.coordinates.length < 2) return geometry;
  const polygons = geometry.coordinates.map((coordinates) => ({ type: "Polygon" as const, coordinates }));
  let result: EffectiveAreaGeometry = polygons[0];
  for (const polygon of polygons.slice(1)) result = mergeGeometry(result, polygon);
  return result;
}
