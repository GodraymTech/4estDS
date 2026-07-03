import { PageContainer } from "../shared/ui/PageContainer";

// 变化检测: 时相卷帘 + 时相选择滑块 + 新增/消失/退化图斑(P1)。
export function ChangePage() {
  return (
    <PageContainer
      title="变化检测"
      subtitle="时相卷帘对比两期影像, 量化面积与株数变化; 单一时相自动降级为现状展示。"
      phase="P1"
    />
  );
}
