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
- Web 支持图片收藏：选择、拖拽或粘贴一张图片，服务端生成缩略图，可查看原图、替换、编辑标题备注并随回收站清理；Android 只读浏览缩略图与原图。
- Web 与 Android 在图片超过 20 MB、单边 12000 像素或 5000 万像素时会在上传前自动压缩/缩放，并提示原大小与新大小、尺寸或格式变化（动图会提示已转为静态图片）。
- Chrome/Edge 扩展支持在任意网页图片上右键「收藏图片到 MemoIsle」，直接创建图片条目并上传原图，超大图自动压缩后上传并提示；保存来源网页地址。
- 扩展在登录后同步浏览器浏览历史（最近 30 天基线 + 增量），Web「浏览历史」按日期分块展示，可按关键词或日期区间检索并一键收进资料库（每页最多 1000 条，可继续翻页）；已在资料库的网址会标为「已收藏」。历史在服务端长期保留，默认只搜索最近 30 天，到设置里打开「允许搜索更久的历史记录」后可选 90 天、一年或全部时间。
- 服务端可对图片做 OCR 并生成自动标签（本地引擎 / 视觉大模型 / 本地优先回退，默认关闭），识别文字与标签参与搜索；Web 可查看并重新识别，Android 只读展示。
- Web 支持浏览器录音与会议录音（麦克风 + 系统声音混音）；Android 支持原生 AAC/M4A 录音、离线草稿和失败重试。
- 服务端支持受限音频上传、私有读取和跨端播放；普通语音灵感与会议录音都可以下载为带真实扩展名（webm/m4a/mp3/ogg）的原始音频。
- Android 使用 sherpa-onnx SenseVoiceSmall INT8 做设备端 STT；Web 在浏览器支持时实时转写，均保留可编辑文字和原始录音。
- Web 与 Android 的单词、例句和灵感正文支持服务端 sanoTTS，服务不可用时回退到词典音频与系统/浏览器 TTS。
- Web 提供「首页」内容总览和服务端跨类型搜索，Android 提供统一资料库与本地即时搜索。
- Web 与 Android 提供今日回顾：混合到期单词、未读资料和待整理灵感，可跳过或按类型处理。
- Web 支持电子书收藏：粘贴电子书链接后，云盘分享链接走转存、普通直链由服务端下载后上传，统一存进用户自己绑定的阿里云盘或百度网盘；MemoIsle 只保存云盘文件引用与元数据快照，不保存电子书本体，标签与分类复用资料库既有能力。云盘登录态由用户在「☁ 云盘绑定」里粘贴，凭据加密保存、只回显末四位。**注意**：该链路需要自备云盘开放平台应用凭据，且尚未与真实云盘联调验收，详见实现状态文档的当前边界。
- Web 与 Android 密码库支持「AI 订阅」条目：记录 Claude / ChatGPT / Grok 订阅的账号、密码、订阅时间、到期续费日与账户余额，全部在客户端端到端加密，服务器只存密文。
- 服务端支持 AgentlyMail/SMTP 邮箱验证码、密码找回、登录限流和邮箱密码登录，Web 与 Android 使用可撤销 Bearer 会话访问数据。微信、Google、Apple 登录暂缓。
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

Android 首次构建 STT 前需要下载 SenseVoiceSmall INT8 模型：

```bash
./android/scripts/download-sensevoice-model.sh
```

模型权重只保存在本地 assets，不提交到 Git；没有模型时仍可录音、保存并手动填写转写。
服务端 TTS 的安装和环境变量见[后端说明](backend/README.md)。

详细环境、接口和验证结果见[实现状态](docs/implementation-status.md)。

## 项目文档

- [文档索引](docs/README.md)
- [产品需求文档](docs/product-requirements.md)
- [待办清单](docs/backlog.md)
- [交互与页面设计](docs/ux-design.md)
- [技术方案](docs/technical-design.md)
- [视觉设计系统](docs/DESIGN.md)
- [Stitch 设计交付](docs/stitch-delivery.md)
- [实现状态](docs/implementation-status.md)
