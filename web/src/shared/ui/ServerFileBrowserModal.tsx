import { useEffect, useMemo, useState } from "react";
import {
  Modal,
  Input,
  Button,
  Table,
  Space,
  Breadcrumb,
  message,
} from "antd";
import {
  FolderOutlined,
  FileOutlined,
  ArrowUpOutlined,
  HomeOutlined,
  DesktopOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import type { TableProps } from "antd";
import { endpoints } from "../api/endpoints";
import type { ServerFileItem } from "../api/types";

interface ServerFileBrowserModalProps {
  open: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
  selectType?: "file" | "dir" | "both";
  title?: string;
  defaultPath?: string;
}

export function ServerFileBrowserModal({
  open,
  onClose,
  onSelect,
  selectType = "file",
  title = "选择服务端路径",
  defaultPath,
}: ServerFileBrowserModalProps) {
  const [currentPath, setCurrentPath] = useState("/");
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [items, setItems] = useState<ServerFileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedRowKey, setSelectedRowKey] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [inputValue, setInputValue] = useState("");

  // 当默认路径传入时或者 Modal 打开时，初始化当前路径
  useEffect(() => {
    if (open) {
      const initPath = defaultPath || "/";
      loadDirectory(initPath);
    }
  }, [open, defaultPath]);

  async function loadDirectory(path: string) {
    setLoading(true);
    try {
      const res = await endpoints.browseServerFiles(path);
      setCurrentPath(res.current_path);
      setInputValue(res.current_path);
      setParentPath(res.parent_path ?? null);
      setItems(res.items || []);
      setSelectedRowKey(null);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "读取服务端目录失败");
    } finally {
      setLoading(false);
    }
  }

  // 搜索过滤后的文件列表
  const filteredItems = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return items;
    return items.filter((item) => item.name.toLowerCase().includes(query));
  }, [items, searchQuery]);

  // 找出当前选中的项
  const selectedItem = useMemo(() => {
    return items.find((item) => item.path === selectedRowKey) || null;
  }, [items, selectedRowKey]);

  // 处理确认选择动作
  const handleConfirm = () => {
    if (selectType === "file" && (!selectedItem || selectedItem.is_dir)) {
      message.warning("请选择一个影像文件");
      return;
    }
    if (selectType === "dir") {
      // 选目录模式：如果选中了一个目录行，就返回该目录；如果没选任何行，直接返回当前所处目录
      if (selectedItem && selectedItem.is_dir) {
        onSelect(selectedItem.path);
      } else {
        onSelect(currentPath);
      }
      onClose();
      return;
    }
    // 默认或 both 模式
    if (selectedItem) {
      onSelect(selectedItem.path);
      onClose();
    } else if (selectType === "both") {
      onSelect(currentPath);
      onClose();
    } else {
      message.warning("请选择文件或目录");
    }
  };

  // 生成面包屑项
  const breadcrumbs = useMemo(() => {
    const parts = currentPath.split("/").filter(Boolean);
    const list = [{ name: "根目录", path: "/" }];
    parts.forEach((part, index) => {
      const p = "/" + parts.slice(0, index + 1).join("/");
      list.push({ name: part, path: p });
    });
    return list;
  }, [currentPath]);

  // 格式化文件大小
  function formatBytes(bytes?: number | null) {
    if (bytes == null || typeof bytes !== "number") return "-";
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  const columns: TableProps<ServerFileItem>["columns"] = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      render: (text, record) => (
        <Space size={8}>
          {record.is_dir ? (
            <FolderOutlined style={{ color: "#ffc069", fontSize: 16 }} />
          ) : (
            <FileOutlined style={{ color: "#1890ff", fontSize: 16 }} />
          )}
          <span style={{ fontWeight: record.is_dir ? "bold" : "normal" }}>{text}</span>
        </Space>
      ),
    },
    {
      title: "类型",
      dataIndex: "is_dir",
      key: "is_dir",
      width: 100,
      render: (isDir) => (isDir ? "文件夹" : "文件"),
    },
    {
      title: "大小",
      dataIndex: "size",
      key: "size",
      width: 120,
      render: (size, record) => (record.is_dir ? "-" : formatBytes(size)),
    },
  ];

  return (
    <Modal
      open={open}
      title={title}
      onCancel={onClose}
      onOk={handleConfirm}
      width={780}
      okText="确认选择"
      cancelText="取消"
      destroyOnClose
      okButtonProps={{
        disabled: selectType === "file" && (!selectedItem || selectedItem.is_dir),
      }}
    >
      <Space direction="vertical" size={12} style={{ width: "100%", padding: "8px 0" }}>
        {/* 快捷跳转栏与输入路径栏 */}
        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onPressEnter={() => {
              const val = inputValue.trim();
              if (val) loadDirectory(val);
            }}
            placeholder="输入服务端路径回车直达"
          />
          <Button
            onClick={() => {
              const val = inputValue.trim();
              if (val) loadDirectory(val);
            }}
          >
            跳转
          </Button>
        </Space.Compact>

        <Space size={8} wrap style={{ alignItems: "center" }}>
          <Text type="secondary">快捷跳转：</Text>
          <Button
            size="small"
            icon={<HomeOutlined />}
            onClick={() => loadDirectory("/")}
          >
            系统根目录
          </Button>
          <Button
            size="small"
            icon={<DesktopOutlined />}
            onClick={() => loadDirectory("/mnt")}
          >
            挂载磁盘 (/mnt)
          </Button>
          <Button
            size="small"
            onClick={() => loadDirectory("/mnt/e")}
          >
            E 盘 (/mnt/e)
          </Button>
          {parentPath ? (
            <Button
              size="small"
              icon={<ArrowUpOutlined />}
              onClick={() => loadDirectory(parentPath)}
            >
              返回上级
            </Button>
          ) : null}
        </Space>

        {/* 面包屑导航 */}
        <div
          style={{
            padding: "8px 12px",
            background: "color-mix(in srgb, var(--color-surface, #fff) 90%, var(--color-bg, #f5f5f5))",
            borderRadius: 6,
            border: "1px solid var(--color-border, #d9d9d9)",
          }}
        >
          <Breadcrumb>
            {breadcrumbs.map((crumb, idx) => (
              <Breadcrumb.Item key={crumb.path}>
                {idx === breadcrumbs.length - 1 ? (
                  <span>{crumb.name}</span>
                ) : (
                  <a
                    onClick={(e) => {
                      e.preventDefault();
                      loadDirectory(crumb.path);
                    }}
                  >
                    {crumb.name}
                  </a>
                )}
              </Breadcrumb.Item>
            ))}
          </Breadcrumb>
        </div>

        {/* 当前目录内过滤 */}
        <Input
          prefix={<SearchOutlined style={{ color: "var(--color-text-muted, #bfbfbf)" }} />}
          placeholder="在当前目录下按名字过滤..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          allowClear
        />

        {/* 目录内容表格 */}
        <Table<ServerFileItem>
          rowKey="path"
          size="small"
          loading={loading}
          dataSource={filteredItems}
          columns={columns}
          pagination={false}
          scroll={{ y: 320 }}
          rowSelection={{
            type: "radio",
            selectedRowKeys: selectedRowKey ? [selectedRowKey] : [],
            onChange: (keys) => {
              if (keys.length) setSelectedRowKey(String(keys[0]));
            },
          }}
          onRow={(record) => ({
            onClick: () => {
              setSelectedRowKey(record.path);
            },
            onDoubleClick: () => {
              if (record.is_dir) {
                loadDirectory(record.path);
              } else if (selectType !== "dir") {
                // 如果是文件，且不为仅选目录模式，双击等同于选中并确认选择
                onSelect(record.path);
                onClose();
              }
            },
          })}
          locale={{ emptyText: "暂无目录或符合条件的影像文件" }}
          style={{ cursor: "pointer" }}
        />
      </Space>
    </Modal>
  );
}

// 辅助包装 Antd Typography.Text 以防导入错乱
function Text({ children, type, style }: { children: React.ReactNode; type?: "secondary" | "danger" | "success"; style?: React.CSSProperties }) {
  const color = type === "secondary" ? "var(--color-text-muted, #8c8c8c)" : undefined;
  return <span style={{ color, ...style }}>{children}</span>;
}
