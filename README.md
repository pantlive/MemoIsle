# MemoIsle

我看到 / 想到一个以后可能有用的东西 → 快速记下来 → 以后能找到、复习或继续使用。

MemoIsle 是一个面向 Web 与 Android 的统一收藏、记录与回顾工具。首个版本聚焦英语单词、网页资料和灵感三类内容，并支持文字与语音输入。

## 当前实现

三类内容、语音输入与统一搜索的核心里程碑已经完成：

- FastAPI + SQLite 共享 API，支持灵感的幂等创建、读取、编辑、版本冲突检测与增量同步。
- React 响应式 Web，支持文字灵感创建、列表和编辑。
- Jetpack Compose Android，支持 SQLite 本地缓存、离线创建、失败重试和跨端同步。
- Web 负责网页资料收藏、整理和原链接编辑；Android 主要用于只读浏览与打开来源。
- Android 已注册系统分享入口，可从浏览器轻量保存网页资料，后续编辑在 Web 完成。
- Web 与 Android 支持英语单词、音标、释义和例句收藏，以及三档复习反馈。
- Web 支持浏览器录音；Android 支持原生 AAC/M4A 录音、离线草稿和失败重试。
- 服务端支持受限音频上传、私有读取和跨端播放。
- Web 提供全部内容页和服务端跨类型搜索，Android 提供统一资料库与本地即时搜索。
- Web 与 Android 提供今日回顾：混合到期单词、未读资料和待整理灵感，可跳过或按类型处理。
- Web 与 Android 视觉样式均来自 Stitch 设计系统。

## 快速运行

后端：

```bash
conda env create -f environment.yml
conda activate memoisle
uvicorn app.main:app --app-dir backend --reload
```

Web：

```bash
cd web
npm install
npm run dev
```

Android 使用 Android Studio 打开 `android/`，或在已配置 Android SDK 与 JDK 17
的环境中运行：

```bash
cd android
./gradlew assembleDebug
```

详细环境、接口和验证结果见[实现状态](docs/implementation-status.md)。

## 项目文档

- [文档索引](docs/README.md)
- [产品需求文档](docs/product-requirements.md)
- [交互与页面设计](docs/ux-design.md)
- [技术方案](docs/technical-design.md)
- [视觉设计系统](docs/DESIGN.md)
- [Stitch 设计交付](docs/stitch-delivery.md)
- [实现状态](docs/implementation-status.md)
