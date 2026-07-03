import { Button, Result } from "antd";
import { useNavigate } from "react-router-dom";

// 404: 路由兵底。
export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title="404"
      subTitle="页面不存在或已移除。"
      extra={
        <Button type="primary" onClick={() => navigate("/overview")}>
          回到总览
        </Button>
      }
    />
  );
}
