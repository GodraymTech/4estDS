import type { FeatureCollection, GeoFeature } from "../api";

export const DEAD_SPECIES_CODE = "GG";

/** 标准树种英文大写代号 -> 中文展示名称映射 (每个英文代码唯一对应一个中文) */
export const SPECIES_CODE_TO_CN: Record<string, string> = {
  QQ: "秋茄",
  HHL: "红海榄",
  THS: "桐花树",
  ML: "木榄",
  BGR: "白骨壤",
  WBHS: "无瓣海桑",
  TREE: "红树",
  GG: "枯木",
};

/** 中文名称/别名 -> 标准英文大写代号映射 */
export const SPECIES_CN_TO_CODE: Record<string, string> = {
  秋茄: "QQ",
  红海榄: "HHL",
  桐花树: "THS",
  木榄: "ML",
  白骨壤: "BGR",
  无瓣海桑: "WBHS",
  红树: "TREE",
  其他红树: "TREE",
  枯木: "GG",
  死树: "GG",
};

/**
 * 格式化树种展示名称：将英文代码 (如 QQ, TREE, GG) 自动映射为对应唯一中文；
 * 每个英文唯一对应一个中文 (如 TREE -> 红树)；
 * 新树种没有中文映射就保持原样大写展示 (如 DD -> DD)。
 */
export function formatSpeciesName(species?: unknown): string {
  if (typeof species !== "string" || !species.trim()) return "未知树种";
  const trimmed = species.trim();
  if (SPECIES_CN_TO_CODE[trimmed]) {
    const code = SPECIES_CN_TO_CODE[trimmed];
    return SPECIES_CODE_TO_CN[code] ?? trimmed;
  }
  const upper = trimmed.toUpperCase();
  return SPECIES_CODE_TO_CN[upper] ?? upper;
}

/**
 * 将任意树种名称归一化为纯英文大写代号 (如 秋茄 -> QQ, DD -> DD)。
 * 空值时返回默认 "TREE"。
 */
export function toSpeciesCode(species?: unknown): string {
  if (typeof species !== "string" || !species.trim()) return "TREE";
  const trimmed = species.trim();
  if (SPECIES_CN_TO_CODE[trimmed]) return SPECIES_CN_TO_CODE[trimmed];
  return trimmed.toUpperCase();
}

export function isDeadSpecies(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const s = value.trim().toUpperCase();
  return s === DEAD_SPECIES_CODE || s === "枯木" || s === "死树";
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
