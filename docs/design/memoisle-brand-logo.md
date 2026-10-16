# MemoIsle Web 品牌图标

设计日期：2026-09-30。通过 Stitch MCP，在既有 MemoIsle 设计系统下生成。

- [Stitch 项目](https://stitch.withgoogle.com/projects/18165090606050486099)
- 设计屏幕：`7f68dcbb9f294d37a8a36a95c410ba11`
- 设计系统：`assets/0d02dfa6aa6e4a049d60dee33ff10970`
- 原始设计稿：[memoisle-brand-stitch.html](memoisle-brand-stitch.html)
- 实际尺寸预览：[memoisle-brand-preview.png](memoisle-brand-preview.png)

图标保留原有 M 字母身份，将字形简化成折页式圆角几何线条，表达记忆、阅读和知识岛屿。使用 `#177A72` 深青色笔画和 `#E2F2EE` 浅薄荷底板，适配现有页面配色。

## 统一使用

`web/public/favicon.svg` 是唯一矢量源，采用 `64 × 64` 视图、`16` 单位底板圆角、`7` 单位圆角笔画；符号不依赖字体或远程资源。

- 浏览器标签：SVG 图标，兼容回退为包含 16/32/48 像素尺寸的 ICO。
- 工作台侧栏：`BrandLogo` 组件，显示为 36 像素。
- 登录与登录加载页：同一组件，显示为 48 像素。
- Apple 触屏图标：同一 SVG 渲染为 180 像素 PNG，以浅薄荷色填充四角。
- 浏览器扩展：同一 SVG 渲染为 16/32/48/128 像素 PNG（`extension/icons/generate.py`）。

页面与标签图标共用相同文件，保持字形、比例和颜色一致。更新矢量源时需同时重新生成 ICO 与触屏 PNG。
