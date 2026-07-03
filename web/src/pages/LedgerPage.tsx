import { PageContainer } from "../shared/ui/PageContainer";
import { LedgerTable } from "../features/ledger";

// 合规监管台账: 地块/时相/运行/报告的可检索记录(P1)。
export function LedgerPage() {
  return (
    <PageContainer
      title="监管台账"
      subtitle="面向政府监管的可追溯台账: 面积现状与变化、修复成效、合规证据链。"
    >
      <LedgerTable />
    </PageContainer>
  );
}
