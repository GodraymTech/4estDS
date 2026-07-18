import { describe, expect, it } from "vitest";
import {
  effectiveAreaErrorMessage,
  buildInvalidAreaMask,
  formatAreaLedgerValue,
  formatHm2,
  geometryVertexCount,
} from "./model";

describe("有效区域展示逻辑", () => {
  it("按台账规范展示地块面积与有效面积", () => {
    expect(formatAreaLedgerValue(12.34, 10.84)).toBe("12.3（10.8）");
    expect(formatAreaLedgerValue(12.34, null)).toBe("12.3（—）");
  });

  it("面积缺失时使用中文占位，有限值保留一位小数", () => {
    expect(formatHm2(undefined)).toBe("—");
    expect(formatHm2(Number.NaN)).toBe("—");
    expect(formatHm2(0)).toBe("0.0");
  });

  it("统计 Polygon、MultiPolygon 与洞的可编辑顶点", () => {
    expect(geometryVertexCount({
      type: "Polygon",
      coordinates: [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [2, 1], [2, 2], [1, 1]],
      ],
    })).toBe(7);
    expect(geometryVertexCount({
      type: "MultiPolygon",
      coordinates: [
        [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        [[[2, 2], [3, 2], [3, 3], [2, 2]]],
      ],
    })).toBe(6);
  });

  it("把有效区外的地块范围构造成带洞遮罩", () => {
    const mask = buildInvalidAreaMask(
      { type: "Polygon", coordinates: [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]] },
      { type: "Polygon", coordinates: [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]] },
    );
    const feature = mask.features?.[0] as { geometry: { coordinates: unknown[] } };
    expect(feature.geometry.coordinates).toHaveLength(2);
  });

  it("有效区自身的洞仍作为无效区遮罩", () => {
    const mask = buildInvalidAreaMask(
      { type: "Polygon", coordinates: [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]] },
      {
        type: "Polygon",
        coordinates: [
          [[0.5, 0.5], [3.5, 0.5], [3.5, 3.5], [0.5, 3.5], [0.5, 0.5]],
          [[1, 1], [2, 1], [2, 2], [1, 1]],
        ],
      },
    );
    expect(mask.features).toHaveLength(2);
  });
});

describe("有效区域错误文案", () => {
  it("明确区分并发冲突和越界裁剪确认", () => {
    expect(effectiveAreaErrorMessage({ status: 409, code: "effective_area_conflict" }))
      .toContain("其他操作更新");
    expect(effectiveAreaErrorMessage({ status: 422, code: "outside_boundary" }))
      .toContain("确认裁剪");
  });
});
