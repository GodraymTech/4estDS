import { useMemo } from "react";
import type { CSSProperties } from "react";
import { Spin } from "antd";
import { PageContainer } from "../shared/ui/PageContainer";
import { useTracts } from "../entities/tract";
import { groupPhasesByLocation } from "../entities/phase";
import { AlertsCenter } from "../features/alerts";

// 预警中心: 从各地点最新两期变化客户端派生退化/清除/株数骤降预警。
export function AlertsPage() {
  const { data: tracts, isLoading } = useTracts();
  const groups = useMemo(() => groupPhasesByLocation(tracts ?? []), [tracts]);

  return (
    <PageContainer
      title="预警中心"
      subtitle="基于两期变化的生态退化、图斑清除、株数骤降预警（客户端派生）。"
      phase="P2"
    >
      {isLoading ? (
        <div style={CENTER}>
          <Spin />
        </div>
      ) : (
        <AlertsCenter groups={groups} />
      )}
    </PageContainer>
  );
}

const CENTER: CSSProperties = {
  display: "flex",
  justifyContent: "center",
  padding: 48,
};
