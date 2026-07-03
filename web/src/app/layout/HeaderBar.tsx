import { useState } from "react"
import type { CSSProperties } from "react"
import { Button, Dropdown, Space, Typography } from "antd"
import {
  QuestionCircleOutlined,
  UserOutlined,
} from "@ant-design/icons"
import type { MenuProps } from "antd"
import { AboutModal } from "./AboutModal"

const { Text } = Typography

// 顶栏: 左侧预留页面上下文(面包屑/时相), 右侧帮助与用户菜单。
// 商业外围(关于/隐私/联系)收进右上菜单, 不占主导航。
export function HeaderBar() {
  const [aboutOpen, setAboutOpen] = useState(false)

  const helpMenu: MenuProps["items"] = [
    { key: "about", label: "关于 4estDS" },
    { key: "privacy", label: "隐私策略" },
    { key: "terms", label: "服务条款" },
    { key: "contact", label: "联系我们" },
  ]
  const userMenu: MenuProps["items"] = [
    { key: "profile", label: "个人资料" },
    { key: "admin", label: "系统管理" },
    { type: "divider" },
    { key: "logout", label: "退出登录" },
  ]

  const onHelp: MenuProps["onClick"] = ({ key }) => {
    if (key === "about") setAboutOpen(true)
  }

  return (
    <div style={WRAP}>
      <Text style={CONTEXT}>红树林生态监测与监管平台</Text>
      <Space size={4}>
        <Dropdown menu= items: helpMenu, onClick: onHelp  placement="bottomRight">
          <Button type="text" style={ACTION} icon={<QuestionCircleOutlined />} aria-label="帮助" />
        </Dropdown>
        <Dropdown menu= items: userMenu  placement="bottomRight">
          <Button type="text" style={ACTION} icon={<UserOutlined />} aria-label="用户" />
        </Dropdown>
      </Space>
      <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} />
    </div>
  )
}

const WRAP: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  height: "100%",
  paddingInline: 16,
}
const CONTEXT: CSSProperties = { color: "#c7e0d8", fontSize: 14 }
const ACTION: CSSProperties = { color: "#edf1ef", fontSize: 18 }
