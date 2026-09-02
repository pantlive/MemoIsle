# MemoIsle Chrome / Edge 网页收藏扩展

从 MemoIsle Web 安装：

1. 点击 MemoIsle Web 顶部的“下载扩展”，保存 ZIP 文件并解压。
2. 打开 `chrome://extensions`，启用“开发者模式”。
3. 选择“加载已解压的扩展程序”，加载解压后的 `memoisle-extension` 文件夹。
4. 首次加载或升级时确认“读取和更改书签”权限。
5. 打开 MemoIsle 的“导入浏览器书签”，扩展读取的书签会直接进入预览，无需导出 HTML。
6. 在普通 HTTP(S) 网页点击扩展图标，或使用 `Ctrl+Shift+M`；扩展也会同步当前浏览器中已打开的网页。

本地开发也可以在第三步直接选择仓库中的 `extension` 目录。后端位于 WSL 时需让 Uvicorn 监听 `0.0.0.0`，保证 Windows 浏览器能访问 `127.0.0.1:8000`。

扩展申请 `tabs` 权限，用于读取当前浏览器各窗口中已打开标签页的 URL、标题和图标，供 Web 输入 `@` 选择；申请 `bookmarks` 权限，用于同步书签标题、网址和文件夹路径，供 Web 直接预览并确认导入。扩展不会读取浏览历史、Cookie、表单或页面正文。打开网页快照只保留 HTTP(S) 公网页面，浏览器内部页、本地文件和内网地址会被过滤；书签中的非 HTTP(S) 地址会在导入预览中标为无效，不会创建资料。当前开发清单只允许连接本机 MemoIsle API；生产部署时应把 `manifest.json` 中的 API 主机权限和 `background.js` 默认地址替换为正式同源地址。

Chrome 不允许普通 Web 页面无授权读取浏览器书签，因此该能力必须由扩展提供。没有安装新版扩展时，Web 仍保留 Chrome 书签 HTML 本地解析入口作为备用方式，原始 HTML 文件不会上传。

无需启动浏览器即可执行扩展触发逻辑的自动化回归测试：

```bash
cd extension
npm test
```
