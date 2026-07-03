import { PageContainer } from "../shared/ui/PageContainer";
import { ReportHub } from "../features/reports";

// 报告中心: 按地块生成 PDF 报告 / 导出 GeoJSON 成果(P1)。
export function ReportsPage() {
  return (
    <PageContainer
      title="报告中心"
      subtitle="按地块生成监测报告与导出成果，用于合规报送与成效证明。"
    >
      <ReportHub />
    </PageContainer>
  );
}
