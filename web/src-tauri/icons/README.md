# 图标占位

`tauri build` 需要下列图标文件(本目录下), 仓库未预置二进制图标:

- `32x32.png`
- `128x128.png`
- `128x128@2x.png`
- `icon.icns` (macOS)
- `icon.ico` (Windows)

## 生成方式

准备一张 1024×1024 的 PNG 品牌图(如 `brand.png`), 在 `web/` 目录执行:

```bash
npm run tauri icon path/to/brand.png
```

该命令会自动生成全平台所需的图标并写入本目录。未生成前, 仅 `tauri dev` 可用, `tauri build` 会因缺图标失败。
