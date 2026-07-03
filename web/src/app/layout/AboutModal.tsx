import { Modal, Descriptions, Typography } from "antd";
import { APP_META } from "../../shared/config/appMeta";

const { Paragraph, Link } = Typography;

// 关于弹窗: 产品名/版本/许可与合规/开源声明。
export function AboutModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={onClose}
      title="关于 4estDS"
      footer={null}
    >
      <Paragraph type="secondary">{APP_META.tagline}</Paragraph>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="产品">{APP_META.name}</Descriptions.Item>
        <Descriptions.Item label="版本">
          <span className="mono">{APP_META.version}</span>
        </Descriptions.Item>
        <Descriptions.Item label="提供方">{APP_META.vendor}</Descriptions.Item>
        <Descriptions.Item label="备案">{APP_META.icp}</Descriptions.Item>
      </Descriptions>
      <Paragraph type="secondary" style={NOTE}>
        本系统含开源组件(React / AntD / MapLibre 等), 遵循各自许可。
        <Link href="/privacy">隐私策略</Link>
      </Paragraph>
    </Modal>
  );
}

const NOTE = { marginTop: 12, marginBottom: 0 } as const;
