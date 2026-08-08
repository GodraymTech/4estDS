import { useState } from "react";
import { Button, Checkbox, Modal, Space, Tag, Typography, message } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { TreeObservationItem } from "../../shared/api";

const { Text } = Typography;

export interface ColumnDefinition {
  key: keyof TreeObservationItem;
  label: string;
  category: "basic" | "metrics" | "geometry";
  defaultSelected?: boolean;
}

export const ALL_EXPORT_COLUMNS: ColumnDefinition[] = [
  // 基本标识
  { key: "observation_id", label: "观测ID (observation_id)", category: "basic", defaultSelected: true },
  { key: "individual_id", label: "单木ID (individual_id)", category: "basic", defaultSelected: true },
  { key: "species", label: "树种 (species)", category: "basic", defaultSelected: true },
  { key: "confidence", label: "置信度 (confidence)", category: "basic", defaultSelected: true },
  { key: "run_id", label: "运行ID (run_id)", category: "basic", defaultSelected: true },
  { key: "tiff_id", label: "TIFF ID (tiff_id)", category: "basic", defaultSelected: true },
  { key: "phase_id", label: "时相 (phase_id)", category: "basic", defaultSelected: true },
  { key: "tract_id", label: "地块 (tract_id)", category: "basic", defaultSelected: true },
  { key: "city", label: "市 (city)", category: "basic" },
  { key: "county", label: "县/区 (county)", category: "basic" },
  { key: "town", label: "乡镇 (town)", category: "basic" },

  // 测树学指标
  { key: "height", label: "树高/m (height)", category: "metrics", defaultSelected: true },
  { key: "height_source", label: "树高来源 (height_source)", category: "metrics" },
  { key: "crown_width_geo", label: "冠幅宽/m (crown_width_geo)", category: "metrics", defaultSelected: true },
  { key: "crown_height_geo", label: "冠幅高/m (crown_height_geo)", category: "metrics", defaultSelected: true },
  { key: "crown_area_geo_est", label: "估算冠幅面积/m² (crown_area_geo_est)", category: "metrics", defaultSelected: true },
  { key: "crown_area_geo_real", label: "精确冠幅面积/m² (crown_area_geo_real)", category: "metrics" },
  { key: "crown_volume_geo_est", label: "估算树冠体积/m³ (crown_volume_geo_est)", category: "metrics", defaultSelected: true },
  { key: "crown_volume_geo_real", label: "精确树冠体积/m³ (crown_volume_geo_real)", category: "metrics" },
  { key: "source", label: "数据来源 (source)", category: "metrics", defaultSelected: true },
  { key: "created_at", label: "检测时间 (created_at)", category: "metrics", defaultSelected: true },

  // 几何与像素信息
  { key: "center_geom", label: "中心点几何 (center_geom)", category: "geometry" },
  { key: "crown_geom", label: "树冠多边形 (crown_geom)", category: "geometry" },
  { key: "box_px", label: "全图像素框 (box_px)", category: "geometry" },
  { key: "box_px_sub", label: "切片像素框 (box_px_sub)", category: "geometry" },
  { key: "box_geo", label: "地理检测框 (box_geo)", category: "geometry" },
  { key: "crown_width_px", label: "冠幅像素宽 (crown_width_px)", category: "geometry" },
  { key: "crown_height_px", label: "冠幅像素高 (crown_height_px)", category: "geometry" },
  { key: "crown_area_px", label: "冠幅像素面积 (crown_area_px)", category: "geometry" },
  { key: "slice_size", label: "切片尺寸/px (slice_size)", category: "geometry" },
  { key: "source_subimage_path", label: "切片小图路径 (source_subimage_path)", category: "geometry" },
];

const DEFAULT_KEYS = ALL_EXPORT_COLUMNS.filter((c) => c.defaultSelected).map((c) => c.key);
const ALL_KEYS = ALL_EXPORT_COLUMNS.map((c) => c.key);

interface ExportColumnsModalProps {
  open: boolean;
  onClose: () => void;
  items: TreeObservationItem[];
  total: number;
  filenamePrefix?: string;
}

export function ExportColumnsModal({
  open,
  onClose,
  items,
  total,
  filenamePrefix = "tree_observations",
}: ExportColumnsModalProps) {
  const [selectedKeys, setSelectedKeys] = useState<string[]>(DEFAULT_KEYS);

  const handleSelectDefaults = () => setSelectedKeys(DEFAULT_KEYS);
  const handleSelectAll = () => setSelectedKeys(ALL_KEYS);
  const handleClearAll = () => setSelectedKeys([]);

  const handleExport = () => {
    if (selectedKeys.length === 0) {
      message.warning("请至少勾选一个导出列");
      return;
    }
    if (!items || items.length === 0) {
      message.warning("暂无数据可导出");
      return;
    }

    const columnsToExport = ALL_EXPORT_COLUMNS.filter((col) =>
      selectedKeys.includes(col.key)
    );

    // CSV 表头
    const headerRow = columnsToExport.map((col) => `"${col.label.replace(/"/g, '""')}"`).join(",");

    // CSV 数据行
    const dataRows = items.map((row) => {
      return columnsToExport
        .map((col) => {
          const val = row[col.key];
          if (val === null || val === undefined) return '""';
          const str = typeof val === "object" ? JSON.stringify(val) : String(val);
          return `"${str.replace(/"/g, '""')}"`;
        })
        .join(",");
    });

    // 组合为带 UTF-8 BOM 的 CSV 文本
    const csvContent = "\uFEFF" + [headerRow, ...dataRows].join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    link.setAttribute("href", url);
    link.setAttribute("download", `${filenamePrefix}_${timestamp}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    message.success(`成功导出 ${items.length} 条单木观测记录 (${selectedKeys.length} 列)`);
    onClose();
  };

  const renderGroup = (title: string, category: "basic" | "metrics" | "geometry", tagColor: string) => {
    const groupCols = ALL_EXPORT_COLUMNS.filter((c) => c.category === category);
    return (
      <div style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 8, display: "flex", alignItems: "center", gap: 8 }}>
          <Tag color={tagColor}>{title}</Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            已选 {groupCols.filter((c) => selectedKeys.includes(c.key)).length} / {groupCols.length}
          </Text>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 6, paddingLeft: 4 }}>
          {groupCols.map((col) => (
            <Checkbox
              key={col.key}
              checked={selectedKeys.includes(col.key)}
              onChange={(e) => {
                const checked = e.target.checked;
                setSelectedKeys((prev) =>
                  checked ? [...prev, col.key] : prev.filter((k) => k !== col.key)
                );
              }}
            >
              <span style={{ fontSize: 13 }}>{col.label}</span>
            </Checkbox>
          ))}
        </div>
      </div>
    );
  };

  return (
    <Modal
      title={
        <Space>
          <DownloadOutlined style={{ color: "var(--color-primary, #1890ff)" }} />
          <span>自定义列导出 CSV</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={720}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="export" type="primary" icon={<DownloadOutlined />} onClick={handleExport}>
          导出当前数据 ({items.length} 条)
        </Button>,
      ]}
    >
      <div style={{ paddingBottom: 12, borderBottom: "1px solid var(--color-border, #f0f0f0)", marginBottom: 16 }}>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Text type="secondary">
            当前将导出当前筛选条件下的 {items.length} 条记录（总库计 {total.toLocaleString()} 条）。请勾选需包含的列：
          </Text>
          <Space size="small">
            <Button size="small" onClick={handleSelectDefaults}>
              恢复推荐列 ({DEFAULT_KEYS.length})
            </Button>
            <Button size="small" onClick={handleSelectAll}>
              全选 ({ALL_KEYS.length})
            </Button>
            <Button size="small" onClick={handleClearAll}>
              清空
            </Button>
          </Space>
        </Space>
      </div>

      <div style={{ maxHeight: 420, overflowY: "auto", paddingRight: 8 }}>
        {renderGroup("核心标识与地块", "basic", "blue")}
        {renderGroup("测树生态指标", "metrics", "green")}
        {renderGroup("空间几何与像素信息", "geometry", "purple")}
      </div>
    </Modal>
  );
}
