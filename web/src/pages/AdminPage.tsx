import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import {
  Alert,
  Card,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { CheckOutlined, MinusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { PageContainer } from "../shared/ui/PageContainer";
import {
  ALL_PERMISSIONS,
  hasPermission,
  ROLE_META,
  ROLES,
  useRole,
  type Permission,
  type Role,
} from "../shared/auth";

const { Text, Paragraph } = Typography;

// 权限 → 中文名(展示用; 权限本体单一真相在 shared/auth)。
const PERM_LABEL: Record<Permission, string> = {
  "view:overview": "总览查看",
  "view:atlas": "地块工作台",
  "view:change": "变化检测",
  "view:ledger": "台账查看",
  "view:reports": "报告查看",
  "view:alerts": "预警查看",
  "view:carbon": "蓝碳/MRV",
  "view:invasion": "入侵监测",
  "run:infer": "发起推理任务",
  "manage:reports": "报告审批/导出",
  "admin:system": "系统管理",
};

interface PermRow {
  key: Permission;
  label: string;
}

// 系统管理: 会话角色/租户切换 + 角色×权限矩阵(只读展示)。
export function AdminPage() {
  const { role, tenant, setRole, setTenant } = useRole();
  const [tenantDraft, setTenantDraft] = useState(tenant);

  const roleOptions = ROLES.map((r) => ({
    value: r,
    label: ROLE_META[r].label,
  }));

  const rows: PermRow[] = useMemo(
    () => ALL_PERMISSIONS.map((p) => ({ key: p, label: PERM_LABEL[p] })),
    [],
  );

  const columns: ColumnsType<PermRow> = useMemo(() => {
    const roleCols = ROLES.map((r) => ({
      title: ROLE_META[r].label,
      dataIndex: r,
      key: r,
      align: "center" as const,
      render: (_: unknown, row: PermRow) =>
        hasPermission(r, row.key) ? (
          <CheckOutlined style={CHECK} />
        ) : (
          <MinusOutlined style={MUTED} />
        ),
    }));
    return [{ title: "权限", dataIndex: "label", key: "label" }, ...roleCols];
  }, []);

  const applyTenant = () => setTenant(tenantDraft.trim() || "default");

  return (
    <PageContainer
      title="系统管理"
      subtitle="用户与角色、组织与多租户、系统参数。"
    >
      <Space direction="vertical" size={16} style={FULL}>
        <Alert
          type="info"
          showIcon
          message="前端仅作体验层门控"
          description="角色与租户切换用于演示与最小暴露; 真正的访问控制在后端(PostGIS RLS + 鉴权)。"
        />
        <Card size="small" title="当前会话">
          <Space size={24} wrap align="start">
            <span>
              <Text type="secondary">角色</Text>
              <br />
              <Select
                value={role}
                options={roleOptions}
                onChange={(v) => setRole(v as Role)}
                style={FIELD}
              />
            </span>
            <span>
              <Text type="secondary">租户 (X-Tenant-Id)</Text>
              <br />
              <Input
                value={tenantDraft}
                onChange={(e) => setTenantDraft(e.target.value)}
                onPressEnter={applyTenant}
                onBlur={applyTenant}
                style={FIELD}
              />
            </span>
            <span>
              <Text type="secondary">当前生效</Text>
              <br />
              <Space size={4} style={TAGS}>
                <Tag color="#0e6e63">{ROLE_META[role].label}</Tag>
                <Tag>{tenant}</Tag>
              </Space>
            </span>
          </Space>
          <Paragraph type="secondary" style={DESC}>
            {ROLE_META[role].desc}
          </Paragraph>
        </Card>
        <Card size="small" title="角色 × 权限矩阵">
          <Table<PermRow>
            columns={columns}
            dataSource={rows}
            rowKey="key"
            size="small"
            pagination={false}
          />
        </Card>
      </Space>
    </PageContainer>
  );
}

const FULL: CSSProperties = { width: "100%" };
const FIELD: CSSProperties = { width: 200 };
const TAGS: CSSProperties = { marginTop: 4 };
const DESC: CSSProperties = { marginTop: 12, marginBottom: 0 };
const CHECK: CSSProperties = { color: "#3e8e5a" };
const MUTED: CSSProperties = { color: "#c0c8c4" };
