# MemoIsle 实现状态

| 字段 | 内容 |
| --- | --- |
| 里程碑 | M6：网页资料核心闭环 |
| 状态 | P0 核心代码与 Web/Android 运行时冒烟已通过；扩展图标/快捷键仍需在现有 Chrome 开发者模式下手动点击验收 |
| 更新日期 | 2026-09-01 |

## 1. 已实现范围

```text
Web 创建网页资料、灵感或英语单词；Android 接收系统分享的网页
  → 客户端生成幂等 client_id
  → FastAPI 写入共享数据库
  → Web / Android 拉取同一条内容
  → Web 编辑；Android 网页资料只读
  → 其他客户端刷新后获得新版本

Android / Web 录制语音
  → 先创建可恢复的文字灵感
  → 上传受限格式和大小的原始音频
  → 服务端保存音频元数据与私有文件
  → Web / Android 从详情播放

Web / Android 搜索
  → Web 以 250 毫秒防抖请求服务端
  → Android 直接检索本地 SQLite 缓存
  → 跨灵感、网页资料和英语单词返回统一结果

网页资料增强流程
  → 书签 HTML 在 Web 本地解析并预览去重
  → 批次异步导入，保留原文件夹并支持重试/撤销
  → 受限读取标题、站点、描述、封面和图标
  → 规则分类；模糊内容可调用大模型并自动降级
  → 定时巡检链接，提醒失效、跳转和信息变化
```

### 后端

- FastAPI 版本化 API：`/api/v1`。
- 统一 `Memo` 数据模型，已预留 `word`、`resource`、`idea` 三种类型。
- 网页资料保存 `source_url` 和 `source_title`，只接受 HTTP(S) 链接。
- 英语单词保存音标、释义、例句、熟悉度和复习时间。
- 提供到期复习队列以及“忘记 / 模糊 / 记得”三档反馈接口。
- 支持原始音频上传和播放，限制为受支持音频格式、20 MB 和一小时以内。
- 音频文件名完全由服务端生成，下载前检查条目所有者。
- 已有 SQLite 数据库自动补充资料来源字段，不清空原有灵感。
- SQLite 本地开发持久化；连接地址可通过环境变量替换。
- 使用 `user_id + client_id` 保证离线重试幂等。
- 使用 `version` 检测跨设备更新冲突，冲突返回 HTTP 409 和服务端当前内容。
- 支持按更新时间游标进行增量同步。
- `GET /memos?q=` 支持跨类型搜索，并可与类型、分类、资源形态、阅读进度、健康状态、标签、收藏夹、星标、状态、创建日期和排序组合。
- 搜索覆盖标题、正文、来源、页面元数据、分类、导入文件夹、自动标签、单词字段和转写，并转义 LIKE 通配符。
- 网页资料按规范网址去重，新增资料立即进入搜索和后台处理队列。
- 普通列表与搜索在执行条数限制前按更新时间倒序，确保最新收藏不会被旧数据截掉；增量同步仍保持正序游标。
- 网页资料支持文章、视频、课程、工具、书籍、其他六种资源形态，以及未读、阅读中、已完成、归档四种阅读进度；个人收藏夹和星标与系统自动分类分开保存。
- 网页元数据任务具备公网 URL/重定向 SSRF 防护、大小/超时限制和重启恢复。
- 自动分类提供固定七类规则判断、可选大模型适配器和非法输出降级。
- 网页健康调度支持同站点单轮限流、连续失败阈值、指数退避和审计事件。
- 本地开发用户由服务端配置产生，不接收客户端传入的 `user_id`。

当前接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/memos` | 幂等创建条目 |
| GET | `/api/v1/memos` | 读取条目；支持关键词、类型、分类、资源形态、阅读进度、标签、收藏夹、星标、状态、日期和排序参数 |
| GET | `/api/v1/memos/{id}` | 读取详情 |
| PATCH | `/api/v1/memos/{id}` | 带版本号编辑 |
| GET | `/api/v1/sync/changes` | 按游标增量同步 |
| GET | `/api/v1/review-queue` | 获取到期英语单词 |
| POST | `/api/v1/words/{id}/reviews` | 提交三档复习反馈 |
| POST | `/api/v1/memos/{id}/audio` | 上传原始录音 |
| GET | `/api/v1/memos/{id}/audio` | 在线播放或下载录音 |
| POST | `/api/v1/bookmark-imports/preview` | 书签校验、文件夹保留与去重预览 |
| POST | `/api/v1/bookmark-imports` | 创建异步书签导入批次 |
| GET | `/api/v1/bookmark-imports/{id}` | 获取批次和逐项进度 |
| POST | `/api/v1/bookmark-imports/{id}/retry` | 重试失败项目 |
| POST | `/api/v1/bookmark-imports/{id}/undo` | 撤销未编辑的本批资料 |
| GET | `/api/v1/browser-extension/download` | 下载可解压安装的浏览器扩展 ZIP |
| POST | `/api/v1/browser-tabs/sync` | 扩展同步当前浏览器打开网页快照 |
| GET | `/api/v1/browser-tabs/open` | Web 读取当前浏览器可选择的打开网页 |
| POST | `/api/v1/browser-captures` | 扩展提交当前页并换取短时凭据 |
| POST | `/api/v1/browser-captures/exchange` | Web 一次性消费当前页凭据 |
| POST | `/api/v1/resources/{id}/enrich` | 重试网页元数据与分类 |
| GET | `/api/v1/resources/link-health` | 读取巡检中心和状态摘要 |
| POST | `/api/v1/resources/{id}/link-checks` | 人工触发链接巡检 |
| POST | `/api/v1/resources/{id}/link-health-actions` | 重试、更新、忽略或删除巡检结果 |

### Web

- React + TypeScript + Vite。
- 遵循 Stitch 的暖白背景、深青主色、柔和边框和 10/14 px 圆角体系。
- 支持在全部内容、灵感、网页资料和英语单词工作区之间切换。
- 顶部全局搜索支持 `/` 快捷键、输入防抖、清除和无结果状态。
- 混合结果按内容类型展示图标、摘要，并可打开对应编辑界面。
- 支持粘贴网址、填写可选标题和备注、读取资料列表和编辑原链接。
- 网页资料列表展示一个主分类、星标、网页摘要和站点；资料保存后先显示处理状态。
- 支持按自动分类筛选，网页资料重复规范网址自动跳过。
- Web 网页资料列表只按一个主分类和星标筛选，并可按更新时间、创建时间或标题排序。
- 资料库支持列表和卡片两种视图；网页详情只编辑分类与星标两个组织属性，标题、网址和备注作为资料内容编辑。
- 支持 Chrome 书签 HTML 本地解析、预览、文件夹追溯、批次进度、失败重试和撤销。
- 书签导入先完成可搜索写入，再由后台补充元数据与分类；服务重启会自动恢复等待中或处理中批次。
- 支持 Chrome Manifest V3 扩展同步当前浏览器各窗口的 HTTP(S) 打开网页，Web 输入 `@` 可选择任意网页；扩展动作仍通过一次性令牌直接捕获当前页。
- Web 顶栏和 `@网页` 未连接提示提供扩展 ZIP 下载入口，下载包只包含清单、后台脚本和安装说明。
- 支持网页巡检中心、失效网页角标、状态摘要、人工重试、采用跳转网址、更新网址/资料、忽略和删除。
- 支持单词、音标、释义和例句的收藏与编辑。
- 单词复习默认隐藏答案，显示后可提交三档反馈。
- 支持浏览器麦克风录音、计时、配套文字、失败重试和详情播放。
- 支持快速创建文字灵感、读取最近内容、打开详情和编辑。
- HTTP 409 时提示跨设备冲突并重新读取服务端内容。
- 提供桌面侧栏、移动底部导航、加载、空和失败状态。

### Android

- 原生 Jetpack Compose，最低 API 26，目标 API 36。
- 使用 Android SQLite 保存本地灵感，不依赖 Room/KSP。
- Android SQLite 已升级到版本 7，可同时缓存灵感与网页资料元数据、分类、资源形态、阅读进度、收藏夹、星标和巡检状态。
- 灵感和英语单词支持本地创建/编辑；网页资料仅在系统分享确认时保存，已保存网页资料只读。
- 启动或手动刷新时重试本地待同步内容，再拉取服务端数据。
- 注册 `ACTION_SEND` 的 `text/plain` 分享目标，可从浏览器或其他应用接收链接。
- 分享链接后自动打开最小确认表单，并预填原始网址和可识别标题；保存后不提供资料编辑入口。
- Android 分享已收藏网址时会原子移除本地临时行并采用服务端原资料，避免重复和永久待同步状态。
- 支持英语单词本地缓存、离线创建、详情编辑和复习反馈。
- Android 本地数据库升级会保留旧版灵感和资料，并补充页面摘要、自动分类、导入来源和健康状态。
- 支持运行时麦克风权限、AAC/M4A 原生录音、本地草稿和失败重试上传。
- 语音灵感详情提供原始录音播放入口。
- 底部“资料库”入口可浏览三类本地内容的统一列表。
- 搜索在本地即时完成，覆盖标题、正文、网址、单词字段、转写和标签。
- 网页资料列表与详情展示一个主分类、星标、摘要、站点和原始网址，支持打开、复制和分享；Android 端只读。
- Debug 模拟器默认连接宿主机 `10.0.2.2:8000`。
- Release API 地址必须通过 `MEMOISLE_API_BASE_URL` Gradle 属性设置。

## 2. 工程结构

```text
MemoIsle/
├── backend/       FastAPI、SQLAlchemy 与 API 测试
├── web/           React 响应式客户端
├── android/       Jetpack Compose Android 客户端
├── docs/          产品、设计、技术与交付文档
├── environment.yml
└── pyproject.toml
```

## 3. 本地运行

### 3.1 后端

```bash
conda env create -f environment.yml
conda activate memoisle
uvicorn app.main:app --app-dir backend --reload
```

默认数据库位于 `data/memoisle.db`。Swagger 文档位于
`http://127.0.0.1:8000/docs`。

如果后端运行在 WSL，而 Chrome 与 Android 模拟器运行在 Windows，使用
`--host 0.0.0.0` 启动 Uvicorn，以便 Windows 本机转发访问 `8000` 端口。

### 3.2 Web

```bash
cd web
npm install
npm run dev
```

开发服务器将 `/api` 转发到 `http://127.0.0.1:8000`。

### 3.3 Android

确保 `android/local.properties` 中的 `sdk.dir` 指向 Android SDK，并使用 JDK 17：

```bash
cd android
./gradlew testDebugUnitTest assembleDebug lintDebug
```

Debug APK 生成在：

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

### 3.4 浏览器扩展

点击 Web 顶栏“下载扩展”，解压 `memoisle-browser-extension.zip`，然后在
Chrome 或 Edge 的扩展管理页启用开发者模式并选择“加载已解压的扩展”。
本地开发也可以直接加载仓库中的 `extension` 目录。

## 4. 已执行验证

| 范围 | 命令/方式 | 结果 |
| --- | --- | --- |
| Python 静态检查 | `ruff check backend` | 通过 |
| 后端测试 | `pytest -q` | 32 个测试通过 |
| Web 类型与生产构建 | `npm run build` | 通过 |
| Android 单元测试 | `./gradlew testDebugUnitTest` | 通过（7 项） |
| Android APK | `./gradlew assembleDebug` | 通过 |
| Android lint | `./gradlew lintDebug` | 通过 |
| API 真实联调 | health → create → list → update | 200/201，版本 1 → 2 |
| Android 系统分享 | `ACTION_SEND` → 资料表单 → 保存 → API | 201，列表显示“已同步” |
| 单词真实联调 | Android 创建 → 显示答案 → “记得” | 版本 1 → 2，熟悉度 0 → 1 |
| 语音真实联调 | Android 录音 → 创建灵感 → 上传 → 下载 | 243,944 字节有效 MP4 |
| 搜索 API 联调 | `GET /memos?q=...` → 跨类型结果 | 通过 |
| Chrome 扩展静态检查 | `node --check extension/background.js`、Manifest JSON 校验 | 通过 |
| Chrome 扩展下载 | Web 按钮 → 下载 ZIP → 校验运行文件和 Manifest V3 权限 | 通过（接口测试） |
| Chrome 扩展行为测试 | `cd extension && npm test` | 17 项测试通过，覆盖清单权限、打开网页快照、标签页变化、协议/地址拦截、失败回退和配置地址 |
| Chrome Web 捕获 | 当前浏览器多个打开网页快照 → Web `@网页` 选择 → 附件标题/网址渲染；当前页动作仍支持一次性凭据 | 自动化通过；需在现有 Chrome 加载扩展后手动验收 |
| 书签导入接口 | 预览 → 去重 → 导入 → 搜索 → 重试 → 撤销 | 通过（测试覆盖） |
| 书签任务恢复 | `processing` 项重置 → 服务重启恢复 → 批次完成 | 通过（测试覆盖） |
| 网页巡检接口 | 失败阈值 → 变化/跳转 → 处理动作 → 调度限流 | 通过（测试覆盖） |
| Android URL 去重 | 分享服务端已有网址 → 保存 → 本地 SQLite 核对 | 1 行且 `SYNCED` |
| Android 资料只读字段 | 服务端同步分类与星标 → 资料详情 | 显示一个主分类和星标，无编辑表单 |

## 5. 当前边界

- 网页资料核心 P0 已完成代码、接口和 Web/Android 运行时验收；扩展已覆盖当前浏览器打开网页快照和当前页一次性捕获。扩展的图标/快捷键属于浏览器安装态入口，仍需在现有 Chrome 的开发者模式下手动加载后点击确认。
- 生产部署时需将扩展清单中的本地 API 主机权限替换为正式 API 域名，并配置正式 Web 地址。
- 账号认证尚未实现，目前使用服务端固定的本地开发用户。
- 开发环境默认 SQLite，生产环境迁移 PostgreSQL 时需要补数据库迁移脚本。
- Web 暂未提供离线编辑。
- Web 网页资料已收敛为“一个分类 + 星标”的组织模型；旧的资源形态、阅读进度、标签、收藏夹和状态字段仅保留接口与历史数据兼容，不再出现在 Web/Android 资料界面；巡检状态只在网页巡检中心处理。
- Android 当前在应用启动或手动刷新时同步，尚未加入 WorkManager 后台任务。
- 已支持原始录音和用户配套文字，但自动语音转写服务尚未实现。
- 单词自动词典、英美发音音源和词形去重尚未实现。
- Web 录音依赖浏览器 `MediaRecorder`；不支持时会回退并提示使用文字或 Android。
- 开发环境音频保存在本机 `data/audio`，生产环境需迁移到私有对象存储。
- 本里程碑没有上传数据集、临床图像、密码或 API 密钥。

## 6. 下一里程碑建议

下一步优先完成现有 Chrome 扩展手动点击与 Android 实体设备验收、正式域名配置和账号认证；随后处理生产数据库迁移、
WorkManager 后台同步、私有对象存储、语音转写和单词词典数据源。
