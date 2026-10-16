import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 读取启动命令注入的代理地址，端口由 DevDeck 配置控制。
const apiProxy = (
  globalThis as { process?: { env?: Record<string, string | undefined> } }
).process?.env?.MEMOISLE_API_PROXY || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxy,
        changeOrigin: true,
        // 聚类生成最多两次模型请求，合计可能接近 180+80 秒。
        timeout: 400_000,
        proxyTimeout: 400_000,
      },
    },
  },
});
