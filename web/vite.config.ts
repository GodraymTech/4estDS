import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

declare const process: { env: Record<string, string | undefined> };

// 开发时将 /api 代理到 FastAPI(通过 VITE_API_TARGET 驱动)；生产由 nginx 统一反代。
const port = Number(process.env.VITE_PORT || process.env.PORT || 5173);
const apiTarget = process.env.VITE_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port,
    host: true,
    strictPort: true,
    watch: {
      usePolling: true,
      interval: 150,
    },
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
      "/healthz": {
        target: apiTarget,
        changeOrigin: true,
      },
      "/health": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
