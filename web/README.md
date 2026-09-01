# MemoIsle Web

## 运行

先启动仓库中的后端服务，再执行：

```bash
cd web
npm install
npm run dev
```

开发服务器会将 `/api` 代理到 `http://127.0.0.1:8000`。部署时可通过
`VITE_API_BASE_URL` 指向实际的 `/api/v1` 地址。

## 当前功能

- 创建文字灵感。
- 从共享 API 拉取灵感列表。
- 编辑标题与正文。
- 使用版本号检测跨设备更新冲突。
- 响应式桌面和移动布局。
