import { PageContainer } from "../shared/ui/PageContainer";

// 报告中心: 在线报告预览 + 导出(PDF/GeoJSON) + 审批流(P1/P2)。
export function ReportsPage() {
  return (
    <PageContainer
      title="报告中心"
      subtitle="生成与导出监测报告, 支持盖章归档与审批。"
      phase="P1"
    />
  );
}
