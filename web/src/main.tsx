import React from "react";
import ReactDOM from "react-dom/client";
// 自托管字体(内网友好, 无外部 CDN): IBM Plex 超家族 + 思源黑体。
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-serif/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
// 设计令牌 → 全局基线 → 地图样式。
import "./app/styles/tokens.css";
import "./app/styles/global.css";
import "maplibre-gl/dist/maplibre-gl.css";
import App from "./app/App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
