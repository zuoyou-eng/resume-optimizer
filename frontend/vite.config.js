import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 后端地址可用环境变量覆盖（默认 8000）：
//   API_TARGET=http://127.0.0.1:8010 npm run dev
// 用于本机 8000 被其他进程占用时切换端口，不改动默认约定。
const API_TARGET = process.env.API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 开发时代理到 FastAPI，避免跨域
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
});
