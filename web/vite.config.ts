import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// 开发时将 /api 代理到 FastAPI，避免跨域；生产由 nginx 统一反代。
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.VITE_PORT || process.env.PORT || 5173),
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
})
