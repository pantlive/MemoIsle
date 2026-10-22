# 上架 Chrome 网上应用店 / Edge 加载项商店

商店版和本地开发版的区别只有地址：开发版只信任 `localhost` / `127.0.0.1` 的 5173–5178 端口，商店版只信任你部署的正式 Web 地址，默认 Web / API 地址也换成正式地址。代码和权限相同。

## 需要你自己完成的事

1. **准备正式地址**：MemoIsle Web 和 API 都要能通过 HTTPS 访问。商店版拒绝 `http://` 和本机地址。
2. **注册开发者账号**
   - Chrome：在 [Chrome Web Store 开发者控制台](https://chrome.google.com/webstore/devconsole) 注册，一次性支付 5 美元注册费。
   - Edge：在 [Microsoft 合作伙伴中心](https://partner.microsoft.com/dashboard/microsoftedge/overview) 注册，免费。
3. **发布隐私政策**：把 [privacy-policy.md](privacy-policy.md) 改成你的联系方式后放到一个公开网址（例如正式站点的 `/privacy`），商店表单里要填这个网址。
4. **截图**：至少 1 张 1280×800 或 640×400 的截图，建议拍「一键收藏后的通知」「Web 里直接导入书签」「`@` 选择打开的网页」三张。
5. **提交审核**：申请了 `<all_urls>` 和 `tabs`、`bookmarks`、`history`、`idle`、`alarms`，审核通常会更久，需要在表单里逐项说明用途，见 [permissions.md](permissions.md)。

## 生成上传用的 ZIP

```bash
cd extension
npm run package:store -- --web https://memo.example.com
# API 不在同一个域名时另外指定：
npm run package:store -- --web https://memo.example.com --api https://api.example.com/api/v1
```

生成的 `extension/dist/memoisle-extension-store-<版本>.zip` 里 `manifest.json` 在根目录，只包含运行需要的文件，不含测试、安装脚本和说明文档，可直接上传。

每次发新版前把 `manifest.json` 和 `package.json` 的 `version` 一起加一；商店不接受版本号相同的包。上架后用户会自动更新，不再需要「下载扩展 → 解压 → 加载已解压的扩展程序」。

## 商店文案

| 字段 | 内容 |
| --- | --- |
| 名称 | MemoIsle 网页收藏 |
| 简短说明（≤132 字符） | 一键把当前网页、选中文本和网页图片收藏到 MemoIsle，导入书签，并在浏览历史里快速收藏。 |
| 类别 | 工作效率（Productivity） |
| 语言 | 中文（简体） |

详细说明：

> MemoIsle 是你自己部署的个人资料库。安装这个扩展后：
>
> - 点击扩展图标、右键菜单或按 Ctrl+Shift+M，把当前网页收藏到 MemoIsle；选中了文字时，文字会一起保存。
> - 在网页图片上右键，选择「收藏图片到 MemoIsle」。
> - 在 MemoIsle 里直接读取浏览器书签并批量导入，保留原来的文件夹，不用先导出 HTML。
> - 在 MemoIsle 里输入 @，从当前打开的网页中选一个收藏。
> - 在 MemoIsle 的「浏览历史」里搜索最近访问过的网页，一键收进资料库。
>
> 扩展只和你配置的 MemoIsle 服务器通信，不收集 Cookie 或表单内容，也不向第三方发送任何数据。浏览历史仅在你登录 MemoIsle 时同步，用于搜索并一键收藏。
