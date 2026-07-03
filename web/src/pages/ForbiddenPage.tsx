import { Button, Result } from "antd";
import { useNavigate } from "react-router-dom";

// 无权限占位: 前端门控命中时的兑底(安全边界仍在后端)。
export function ForbiddenPage() {
  const navigate = useNavigate();
  const goHome = () => navigate("/overview");
  return (
    <Result
      status="403"
      title="无访问权限"
      subTitle="当前角色无权访问该模块, 请联系管理员调整角色。"
      extra={
        <Button type="primary" onClick={goHome}>
          返回总览
        </Button>
      }
    />
  );
}
