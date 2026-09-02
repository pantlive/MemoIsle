# MemoIsle `@网页` Chrome 扩展

从 MemoIsle Web 安装：

1. 点击 MemoIsle Web 顶部的“下载扩展”，保存 ZIP 文件并解压。
2. 打开 `chrome://extensions`，启用“开发者模式”。
3. 选择“加载已解压的扩展程序”，加载解压后的 `memoisle-extension` 文件夹。
4. 在普通 HTTP(S) 网页点击扩展图标，或使用 `Ctrl+Shift+M`；扩展会同步当前浏览器中已打开的网页。

本地开发也可以在第三步直接选择仓库中的 `extension` 目录。后端位于 WSL 时需让 Uvicorn 监听 `0.0.0.0`，保证 Windows 浏览器能访问 `127.0.0.1:8000`。

扩展申请 `tabs` 权限，用于读取当前浏览器各窗口中已打开标签页的 URL、标题和图标，供 Web 输入 `@` 选择。它不会读取浏览历史、Cookie、表单或页面正文；只同步 HTTP(S) 公网页面，浏览器内部页、本地文件和内网地址会被过滤。当前开发清单只允许连接本机 MemoIsle API；生产部署时应把 `manifest.json` 中的 API 主机权限和 `background.js` 默认地址替换为正式同源地址。

无需启动浏览器即可执行扩展触发逻辑的自动化回归测试：

```bash
cd extension
npm test
```
