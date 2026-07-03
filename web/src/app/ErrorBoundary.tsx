import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button, Result } from "antd";

type Props = { children: ReactNode };
type State = { error: Error | null };

// 路由级错误边界 + 全局兜底。捕获渲染异常, 给出人话提示与恢复动作。
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 开发期记录; 生产可接入审计/上报。
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <Result
          status="error"
          title="页面出错了"
          subTitle="可尝试重新加载; 若反复出现请联系系统管理员。"
          extra={
            <Button type="primary" onClick={() => window.location.reload()}>
              重新加载
            </Button>
          }
        />
      );
    }
    return this.props.children;
  }
}
