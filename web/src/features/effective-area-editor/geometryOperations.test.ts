import { describe, expect, it } from "vitest";
import { areaHm2, mergeGeometry, splitGeometryByLine, subtractGeometry } from "./geometryOperations";

const square = {
  type: "Polygon" as const,
  coordinates: [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
};

describe("编辑器几何操作", () => {
  it("按 hm² 计算预览面积", () => {
    expect(areaHm2(square)).toBeGreaterThan(100);
  });

  it("合并重叠面并保留不相交多岛", () => {
    const shifted = {
      type: "Polygon" as const,
      coordinates: [[[0.02, 0], [0.03, 0], [0.03, 0.01], [0.02, 0.01], [0.02, 0]]],
    };
    expect(mergeGeometry(square, shifted).type).toBe("MultiPolygon");
  });

  it("挖洞后减少面积", () => {
    const hole = {
      type: "Polygon" as const,
      coordinates: [[[0.002, 0.002], [0.008, 0.002], [0.008, 0.008], [0.002, 0.008], [0.002, 0.002]]],
    };
    expect(areaHm2(subtractGeometry(square, hole))).toBeLessThan(areaHm2(square));
  });

  it("用直线把单面分成两个岛", () => {
    const result = splitGeometryByLine(square, [[0.005, -1], [0.005, 1]]);
    expect(result.type).toBe("MultiPolygon");
    expect(result.type === "MultiPolygon" ? result.coordinates : []).toHaveLength(2);
  });
});
