import type { CSSProperties, ReactNode } from "react";
import { Empty, Typography } from "antd";
import { AppFooter } from "../../app/layout/AppFooter";

const { Title, Paragraph } = Typography;

// 非地图页的标准容器: 标题 + 内容区 + 页脚。
// P0 下多为占位; 空状态作为行动邀请(技能写作章)。
export function PageContainer({
  title,
  subtitle,
  phase,
  children,
  withFooter = true,
}: {
  title: string;
  subtitle?: string;
  phase?: string;
  children?: ReactNode;
  withFooter?: boolean;
}) {
  return (
    <div style={OUTER}>
      <div style={BODY}>
        <Title level={3} style={TITLE}>
          {title}
        </Title>
        {subtitle ? <Paragraph type="secondary">{subtitle}</Paragraph> : null}
        {children ?? (
          <div style={EMPTY_WRAP}>
            <Empty description={(phase ? phase + " · " : "") + "建设中"} />
          </div>
        )}
      </div>
      {withFooter ? <AppFooter /> : null}
    </div>
  );
}

const OUTER: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  height: "100%",
  overflow: "auto",
  background: "var(--color-bg)",
  color: "var(--color-text)",
};
const BODY: CSSProperties = { flex: 1, padding: 24 };
const TITLE: CSSProperties = { fontFamily: "var(--font-display)" };
const EMPTY_WRAP: CSSProperties = { paddingTop: 48 };
