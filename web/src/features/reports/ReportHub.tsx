import { useState } from "react";
import type { CSSProperties } from "react";
import { Alert, Button, Card, Select, Space } from "antd";
import { DownloadOutlined, FileTextOutlined } from "@ant-design/icons";
import { useTracts } from "../../entities/tract";
import { endpoints } from "../../shared/api";

// 报告中心: 选地块 → 下载 PDF 报告 / 导出 GeoJSON 成果。
// 报告由服务端按地块最新发布版本生成(复用 v1.0 report/export 端点)。
export function ReportHub() {
  const { data: tracts } = useTracts();
  const [tractId, setTractId] = useState<string | undefined>(undefined);

  const options = (tracts ?? []).map((t) => ({
    value: t.tract_id,
    label: t.name || t.location || t.tract_id,
  }));

  const open = (fmt: "pdf" | "geojson") => {
    if (!tractId) return;
    const url =
      fmt === "pdf"
        ? endpoints.reportUrl(tractId, "pdf")
        : endpoints.exportUrl(tractId, "geojson");
    window.open(url, "_blank");
  };

  return (
    <Card title="生成报告 / 导出成果" style={CARD}>
      <Space direction="vertical" size={16} style={FULL}>
        <Select
          showSearch
          placeholder="选择地块"
          value={tractId}
          onChange={setTractId}
          options={options}
          optionFilterProp="label"
          style={FULL}
        />
        <Space wrap>
          <Button
            type="primary"
            icon={<FileTextOutlined />}
            disabled={!tractId}
            onClick={() => open("pdf")}
          >
            下载 PDF 报告
          </Button>
          <Button
            icon={<DownloadOutlined />}
            disabled={!tractId}
            onClick={() => open("geojson")}
          >
            导出 GeoJSON
          </Button>
        </Space>
        <Alert
          type="info"
          showIcon
          message="报告基于地块最新发布版本生成"
          description="逐图斑台账、变化专题图、批量导出与审批流程将在 P2 接入。"
        />
      </Space>
    </Card>
  );
}

const CARD: CSSProperties = { maxWidth: 640 };
const FULL: CSSProperties = { width: "100%" };
