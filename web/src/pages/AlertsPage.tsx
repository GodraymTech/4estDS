import { useMemo } from "react";
import { Spin } from "antd";
import { PageContainer } from "../shared/ui/PageContainer";
import { useTracts } from "../entities/tract";
import { groupPhasesByLocation } from "../entities/phase";
import { AlertsCenter } from "../features/alerts";

// 预警中心: 基于两期变化派生的退化/疑似清除/株数骤降信号。
// 违法占用/入侵种专项分类器归 P3。
export function AlertsPage() {
  const { data: tracts, isLoading } = useTracts();
  const groups = useMemo(() => groupPhasesByLocation(tracts ?? []), [tracts]);
  return (
    <PageContainer
      title="预警中心"
      subtitle="基于两期变化派生的退化、疑似清除、株数骤降信号(按严重度排序)。"
    >
      {isLoading ? <Spin /> : <AlertsCenter groups={groups} />}
    </PageContainer>
  );
}
