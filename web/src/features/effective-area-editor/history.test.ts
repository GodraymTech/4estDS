import { describe, expect, it } from "vitest";
import { GeometryHistory } from "./history";

describe("GeometryHistory", () => {
  it("撤销与重做保持分支语义", () => {
    const history = new GeometryHistory({ revision: 0 }, 100);
    history.push({ revision: 1 });
    history.push({ revision: 2 });

    expect(history.undo()).toEqual({ revision: 1 });
    expect(history.redo()).toEqual({ revision: 2 });
    history.undo();
    history.push({ revision: 3 });
    expect(history.redo()).toBeNull();
  });

  it("最多保留 100 个可撤销步骤", () => {
    const history = new GeometryHistory({ revision: 0 }, 100);
    for (let revision = 1; revision <= 130; revision += 1) {
      history.push({ revision });
    }

    let undoCount = 0;
    while (history.undo()) undoCount += 1;
    expect(undoCount).toBe(100);
    expect(history.current()).toEqual({ revision: 30 });
  });

  it("相同快照不污染历史", () => {
    const history = new GeometryHistory({ revision: 1 }, 100);
    history.push({ revision: 1 });
    expect(history.undo()).toBeNull();
  });
});
