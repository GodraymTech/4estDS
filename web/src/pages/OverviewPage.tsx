import { useState } from "react";
import type { CSSProperties } from "react";
import { Segmented } from "antd";
import { DashboardPanel, OverviewMap } from "../features/overview";

type View = "map" | "board";

// 总览(一张图): 语义缩放地图 ⇄ 数据看板 双视图。
export function OverviewPage() {
  const [view, setView] = useState<View>("map");
  return (
    <div style={WRAP}>
      <div style={TOGGLE}>
        <Segmented
          value={view}
          onChange={(v) => setView(v as View)}
          options={[
            { label: "一张图", value: "map" },
            { label: "数据看板", value: "board" },
          ]}
        />
      </div>
      {view === "map" ? <OverviewMap /> : <DashboardPanel />}
    </div>
  );
}

const WRAP: CSSProperties = {
  position: "relative",
  flex: 1,
  minHeight: 0,
  display: "flex",
  flexDirection: "column",
};
const TOGGLE: CSSProperties = {
  position: "absolute",
  top: 16,
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 6,
};
