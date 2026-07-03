# 4estDS 桌面壳 (Tauri v2 瓦客户端)

方案 A: 桌面壳只承载前端 UI(几 MB~十几 MB), 重型推理(ultralytics + CUDA + GDAL)
作为独立后端部署(见 `deploy/` 的 docker compose)。壳与后端通过 HTTP 通信。

## 为什么壳很小

壳不内嵌 Python/PyTorch/CUDA/GDAL——那些都在后端镜像里。壳里只有:
编译后的前端静态资源 + 一个 Rust 外壳 + 系统自带的 WebView。

## 前置

- Rust 工具链(rustup, 稳定版)
- 各平台系统依赖(参见 Tauri 官方“Prerequisites”):
  - Windows: WebView2 Runtime + MSVC 构建工具
  - macOS: Xcode Command Line Tools
  - Linux: webkit2gtk 等
- Node 依赖: 在 `web/` 执行 `npm install`

## 开发 / 构建

在 `web/` 目录:

```bash
npm run tauri:dev     # 启动桌面壳 + Vite 开发服务(devUrl=http://localhost:5173)
npm run tauri:build   # 产出安装包(当前平台)
```

> 不能交叉编译: macOS 包必须在 macOS 上构建, Windows 包在 Windows 上构建(建议 CI)。

## 后端地址(关键)

打包后的桌面应用没有 nginx/vite 代理, 因此 `VITE_API_BASE` 必须指向
后端的绝对地址(而非默认的相对路径 `/api/v1`)。在构建前设置:

```bash
# 例: 内网 GPU 一体机
VITE_API_BASE=http://10.0.0.8:8080/api/v1 npm run tauri:build
```

后端同时需允许桌面壳的源(CORS): 在 `deploy/.env` 的 `forestds_CORS_ORIGINS`
加入桌面壳的 origin(如 `tauri://localhost` / `http://tauri.localhost`, 以实际为准)。

## 图标

见 `icons/README.md`: 首次构建前需用 `npm run tauri icon <logo.png>` 生成。

## 层次图

```
桌面壳(Tauri, 十几 MB)
  └─ WebView 渲染 React 前端
        └─ HTTP → 独立后端(FastAPI/Worker, GPU 一体机)
              └─ ultralytics + CUDA + GDAL (数 GB, 不进壳)
```
