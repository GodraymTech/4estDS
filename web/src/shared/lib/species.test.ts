import { describe, expect, it } from "vitest";
import { formatSpeciesName, toSpeciesCode } from "./species";

describe("species utils", () => {
  it("TREE 唯一展示为红树", () => {
    expect(formatSpeciesName("TREE")).toBe("红树");
    expect(formatSpeciesName("tree")).toBe("红树");
    expect(formatSpeciesName("其他红树")).toBe("红树");
    expect(formatSpeciesName("红树")).toBe("红树");
  });

  it("标准已知树种正确映射为中文", () => {
    expect(formatSpeciesName("QQ")).toBe("秋茄");
    expect(formatSpeciesName("HHL")).toBe("红海榄");
    expect(formatSpeciesName("THS")).toBe("桐花树");
    expect(formatSpeciesName("ML")).toBe("木榄");
    expect(formatSpeciesName("BGR")).toBe("白骨壤");
    expect(formatSpeciesName("WBHS")).toBe("无瓣海桑");
    expect(formatSpeciesName("GG")).toBe("枯木");
  });

  it("未映射的新树种保持大写代号原样展示", () => {
    expect(formatSpeciesName("DD")).toBe("DD");
    expect(formatSpeciesName("dd")).toBe("DD");
    expect(formatSpeciesName("XYZ")).toBe("XYZ");
  });

  it("空值或非字符串返回未知树种", () => {
    expect(formatSpeciesName(null)).toBe("未知树种");
    expect(formatSpeciesName("")).toBe("未知树种");
    expect(formatSpeciesName("   ")).toBe("未知树种");
  });

  it("toSpeciesCode 正确归一化为纯大写代号", () => {
    expect(toSpeciesCode("DD")).toBe("DD");
    expect(toSpeciesCode("dd")).toBe("DD");
    expect(toSpeciesCode("秋茄")).toBe("QQ");
    expect(toSpeciesCode("红树")).toBe("TREE");
    expect(toSpeciesCode("其他红树")).toBe("TREE");
    expect(toSpeciesCode(undefined)).toBe("TREE");
  });
});
