# MemoIsle `@网页` Chrome 扩展

开发环境安装：

1. 启动 MemoIsle 后端（Windows 可访问的 `127.0.0.1:8000`）和 Web（`localhost:5173`）。后端位于 WSL 时需让 Uvicorn 监听 `0.0.0.0`。
2. 打开 `chrome://extensions`，启用“开发者模式”。
3. 选择“加载已解压的扩展程序”，加载本目录。
4. 在普通 HTTP(S) 网页点击扩展图标，或使用 `Ctrl+Shift+M`。

扩展只申请 `activeTab`，不会持续读取浏览历史、Cookie、表单、页面正文或后台标签页。当前开发清单只允许连接本机 MemoIsle API；生产部署时应把 `manifest.json` 中的 API 主机权限和 `background.js` 默认地址替换为正式同源地址。

无需启动浏览器即可执行扩展触发逻辑的自动化回归测试：

```bash
cd extension
npm test
```
