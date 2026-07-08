import type { FeatureCollection, GeoFeature } from "../api";

export const DEAD_SPECIES_CODE = "GG";

export function isDeadSpecies(value: unknown): boolean {
  return typeof value === "string" && value.trim().toUpperCase() === DEAD_SPECIES_CODE;
}

export function isDeadFeature(feature: GeoFeature): boolean {
  return isDeadSpecies(feature.properties?.species);
}

export function liveFeatureCollection(fc?: FeatureCollection): FeatureCollection | undefined {
  if (!fc) return undefined;
  return {
    type: "FeatureCollection",
    features: fc.features.filter((feature) => !isDeadFeature(feature)),
  };
}

export function deadFeatureCollection(fc?: FeatureCollection): FeatureCollection | undefined {
  if (!fc) return undefined;
  return {
    type: "FeatureCollection",
    features: fc.features.filter(isDeadFeature),
  };
}
