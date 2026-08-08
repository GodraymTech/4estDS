import { Button, Descriptions, Divider, Drawer, Space, Tag, Typography, message } from "antd";
import {
  CompassOutlined,
  CopyOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  FundProjectionScreenOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import type { TreeObservationItem } from "../../shared/api";

const { Text, Paragraph } = Typography;

interface ObservationDetailDrawerProps {
  open: boolean;
  onClose: () => void;
  item: TreeObservationItem | null;
}

export function ObservationDetailDrawer({ open, onClose, item }: ObservationDetailDrawerProps) {
  const navigate = useNavigate();

  if (!item) return null;

  const handleCopyJson = () => {
    try {
      navigator.clipboard.writeText(JSON.stringify(item, null, 2));
      message.success("已复制单木完整 JSON 数据到剪贴板");
    } catch {
      message.error("复制失败");
    }
  };

  const handleOpenMap = () => {
    if (item.city && item.county && item.tract_id && item.phase_id) {
      navigate(
        [
          "/map",
          encodeURIComponent(item.city),
          encodeURIComponent(item.county),
          encodeURIComponent(item.tract_id),
          encodeURIComponent(item.phase_id),
        ].join("/")
      );
    } else if (item.tract_id) {
      navigate(`/map?tract_id=${encodeURIComponent(item.tract_id)}`);
    } else {
      navigate("/map");
    }
  };

  return (
    <Drawer
      title={
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", paddingRight: 16 }}>
          <Space>
            <FileTextOutlined style={{ color: "var(--color-primary, #1890ff)" }} />
            <span>单木观测详情: <Text code>{item.observation_id}</Text></span>
          </Space>
          <Space size="small">
            <Button size="small" icon={<CopyOutlined />} onClick={handleCopyJson}>
              复制 JSON
            </Button>
            <Button size="small" type="primary" icon={<CompassOutlined />} onClick={handleOpenMap}>
              在地图中查看
            </Button>
          </Space>
        </div>
      }
      placement="right"
      width={560}
      open={open}
      onClose={onClose}
    >
      {/* 1. 核心标识 */}
      <div style={{ marginBottom: 16 }}>
        <Divider orientation="left" style={{ margin: "8px 0 12px" }}>
          <Space size="small">
            <EnvironmentOutlined />
            <span>基本标识与位置</span>
          </Space>
        </Divider>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="观测ID" span={2}>
            <Text copyable code>{item.observation_id}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="单木ID">
            {item.individual_id ? <Text copyable code>{item.individual_id}</Text> : <Text type="secondary">-</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="数据来源">
            <Tag color={item.source === "manual" ? "orange" : item.source === "review" ? "cyan" : "blue"}>
              {item.source}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="运行ID (Run ID)" span={2}>
            <Text copyable code>{item.run_id}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="TIFF ID">
            {item.tiff_id ? <Text code>{item.tiff_id}</Text> : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="时相">
            {item.phase_id || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="地块编号">
            {item.tract_id || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="行政区划">
            {[item.city, item.county, item.town].filter(Boolean).join(" / ") || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="检测时间" span={2}>
            {item.created_at || "-"}
          </Descriptions.Item>
        </Descriptions>
      </div>

      {/* 2. 测树生态指标 */}
      <div style={{ marginBottom: 16 }}>
        <Divider orientation="left" style={{ margin: "8px 0 12px" }}>
          <Space size="small">
            <FundProjectionScreenOutlined />
            <span>测树学指标</span>
          </Space>
        </Divider>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="树种">
            {item.species ? <Tag color="green">{item.species}</Tag> : <Text type="secondary">未分类</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="置信度">
            {item.confidence != null ? `${(item.confidence * 100).toFixed(1)}%` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="树高">
            {item.height != null ? `${item.height.toFixed(2)} m` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="树高来源">
            {item.height_source || "未标明"}
          </Descriptions.Item>
          <Descriptions.Item label="冠幅宽度 (Geo)">
            {item.crown_width_geo != null ? `${item.crown_width_geo.toFixed(2)} m` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="冠幅高度 (Geo)">
            {item.crown_height_geo != null ? `${item.crown_height_geo.toFixed(2)} m` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="估算冠幅面积">
            {item.crown_area_geo_est != null ? `${item.crown_area_geo_est.toFixed(2)} m²` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="真实冠幅面积">
            {item.crown_area_geo_real != null ? `${item.crown_area_geo_real.toFixed(2)} m²` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="估算树冠体积">
            {item.crown_volume_geo_est != null ? `${item.crown_volume_geo_est.toFixed(2)} m³` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="真实树冠体积">
            {item.crown_volume_geo_real != null ? `${item.crown_volume_geo_real.toFixed(2)} m³` : "-"}
          </Descriptions.Item>
        </Descriptions>
      </div>

      {/* 3. 几何与像素检测框 */}
      <div>
        <Divider orientation="left" style={{ margin: "8px 0 12px" }}>
          <span>像素与空间几何 (Geometry)</span>
        </Divider>
        <Descriptions column={2} size="small" bordered style={{ marginBottom: 12 }}>
          <Descriptions.Item label="冠幅像素宽/高">
            {item.crown_width_px != null && item.crown_height_px != null
              ? `${item.crown_width_px.toFixed(1)} × ${item.crown_height_px.toFixed(1)} px`
              : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="冠幅像素面积">
            {item.crown_area_px != null ? `${item.crown_area_px.toFixed(1)} px²` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="切片尺寸">
            {item.slice_size != null ? `${item.slice_size} px` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="切片小图路径">
            {item.source_subimage_path || "-"}
          </Descriptions.Item>
        </Descriptions>

        <div style={{ display: "grid", gap: 12 }}>
          {item.box_px && (
            <div>
              <Text strong style={{ fontSize: 12 }}>全图像素检测框 (box_px):</Text>
              <Paragraph
                code
                copyable
                style={{
                  fontSize: 12,
                  marginTop: 4,
                  padding: "6px 10px",
                  background: "var(--color-bg-layout, #f5f5f5)",
                  borderRadius: 4,
                }}
              >
                {item.box_px}
              </Paragraph>
            </div>
          )}

          {item.box_px_sub && (
            <div>
              <Text strong style={{ fontSize: 12 }}>切片像素检测框 (box_px_sub):</Text>
              <Paragraph
                code
                copyable
                style={{
                  fontSize: 12,
                  marginTop: 4,
                  padding: "6px 10px",
                  background: "var(--color-bg-layout, #f5f5f5)",
                  borderRadius: 4,
                }}
              >
                {item.box_px_sub}
              </Paragraph>
            </div>
          )}

          {item.center_geom && (
            <div>
              <Text strong style={{ fontSize: 12 }}>树冠中心点几何 (center_geom):</Text>
              <Paragraph
                code
                copyable
                style={{
                  fontSize: 12,
                  marginTop: 4,
                  padding: "6px 10px",
                  background: "var(--color-bg-layout, #f5f5f5)",
                  borderRadius: 4,
                }}
              >
                {item.center_geom}
              </Paragraph>
            </div>
          )}

          {item.crown_geom && (
            <div>
              <Text strong style={{ fontSize: 12 }}>树冠多边形轮廓 (crown_geom):</Text>
              <Paragraph
                code
                copyable
                ellipsis={{ rows: 3, expandable: true, symbol: "展开完整几何" }}
                style={{
                  fontSize: 12,
                  marginTop: 4,
                  padding: "6px 10px",
                  background: "var(--color-bg-layout, #f5f5f5)",
                  borderRadius: 4,
                }}
              >
                {item.crown_geom}
              </Paragraph>
            </div>
          )}
        </div>
      </div>
    </Drawer>
  );
}
