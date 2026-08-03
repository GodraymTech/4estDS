import { PageContainer } from "../shared/ui/PageContainer";
import { LedgerTable } from "../features/ledger";

// 合规监管台账: 地块/时相/运行/报告的可检索记录(P1)。
export function LedgerPage() {
  return (
    <PageContainer
      title="监管台账"
      subtitle="生态资产的结构化清单：覆盖影像类型、飞行时相、有效面积与检测统计。"
    >
      <LedgerTable />
    </PageContainer>
  );
}
