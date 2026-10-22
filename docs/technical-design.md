# MemoIsle 技术方案

## 1. 方案目标

本方案支持响应式 Web 与 Android 共用账号、数据和业务规则，并重点保证快速捕获不丢数据、离线可用、语音可恢复以及异步任务失败不阻塞核心流程。

## 2. 总体架构

```text
Web Client ───────┐
                  ├── HTTPS API ── Application Service ── PostgreSQL
Android Client ───┘                       │
                                         ├── Object Storage（录音/封面）
                                         ├── Search Index
                                         └── Job Queue
                                              ├── 网页元数据任务
                                              ├── 网页资料分类任务
                                              ├── Chrome 书签导入任务
                                              ├── 网页健康巡检任务
                                              └── 语音转写任务
```

### 2.1 推荐技术边界

- Web：响应式单页或服务端渲染应用，具体框架在实现阶段确认。
- Chrome 扩展：Manifest V3，同步当前浏览器打开网页与书签树，并提供 `@网页` 选择、当前页快速捕获和书签直接导入桥接。
- Android：原生客户端，使用本地数据库、后台任务与系统分享能力。
- 服务端：Python API 服务；依赖统一使用 conda 管理。
- 数据库：PostgreSQL，使用结构化字段保存核心查询字段，JSON 字段承载低频扩展。
- 文件存储：兼容 S3 的对象存储，数据库只保存对象标识和元数据。
- 异步任务：持久化队列，支持重试、幂等和失败状态查询。
- 机器学习：若部署自托管转写、文本分类或向量模型，严格使用 PyTorch，禁止引入其他深度学习框架。

## 3. 客户端职责

### 3.1 Web

- 提供批量整理、高密度资料库、搜索、详情编辑与完整复习体验。
- 负责网页资料的完整创建、标题与备注编辑、状态整理和来源修正。
- 快速捕获解析 `@网页` 附件，从扩展同步的当前浏览器网页快照中选择页面；扩展当前页动作仍使用一次性页面上下文交换。
- 草稿优先写入浏览器本地存储，再提交服务端。
- 浏览器录音能力不可用时，隐藏录音主动作并解释原因，文字输入保持可用。

### 3.2 Android

- 使用本地数据库作为界面读取来源，可编辑内容先落本地再同步。
- 通过后台任务上传录音和执行增量同步；Android 本地 SQLite 持久化 `updated_at + id` 游标，首次同步做远端快照校准，后续只拉取服务端变更。
- 注册系统分享目标，接收 `text/plain` 及常见链接并执行最小资料保存。
- 网页资料列表和详情保持只读，不调用资料更新 API；整理与编辑跳转 Web 完成。
- 使用临时文件安全保存录音，条目落库后再进入上传队列。
- 设备相关代码不得假定特定厂商或硬件能力。

### 3.3 账号认证

- Web 与 Android 当前只开放邮箱密码注册和登录，凭据使用 PBKDF2-SHA256 加盐哈希保存。
- 微信、Google 和 Apple ID OAuth 授权码登录代码保留，但默认关闭；仅当 `MEMOISLE_OAUTH_LOGIN_ENABLED=true` 且对应凭据配置完整时才对外授权。
- 邮箱注册先发送六位验证码，验证码只保存基于应用密钥的哈希；发送成功后再创建已验证账号。旧版验证链接和密码重置令牌仍只保存 SHA-256 哈希。
- 认证邮件优先由后端通过 `agently-cli message +send` 发送并自动完成确认令牌流程，CLI 不可用时回退 SMTP。
- 同一邮箱连续登录失败触发账号维度限流；密码重置成功后撤销既有 Bearer 会话。
- 服务端保存 `user`、`auth_identity` 和 `auth_session`；第三方主体可绑定到同一账号，已验证邮箱可用于跨提供方归并。
- OAuth `state` 使用服务端密钥 HMAC 签名并设置短时效；回调后的跳转地址必须来自 Web CORS 白名单或显式配置的 Android 深链。
- 登录成功签发 opaque Bearer 令牌，数据库仅保存 SHA-256 哈希；所有业务接口通过依赖注入取得当前用户并按用户隔离数据。
- Android 使用系统浏览器授权，通过 `memoisle://auth/callback` 深链返回；切换账号前清空本机 SQLite 缓存，避免跨用户数据混用。

## 4. 核心数据模型

### 4.1 memo

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID | 服务端主键 |
| user_id | UUID | 所有者 |
| client_id | UUID | 离线创建幂等键 |
| type | enum | word/resource/idea/image |
| title | text | 标题 |
| body | text | 正文或备注 |
| source_url | text nullable | 来源链接 |
| source_title | text nullable | 来源名称 |
| status | enum | inbox/active/archived/trashed |
| is_favorite | boolean | 星标 |
| version | integer | 乐观并发控制版本 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |
| deleted_at | timestamptz nullable | 回收站时间 |
| status_before_trash | text nullable | 进入回收站前的状态，用于恢复 |

### 4.2 类型扩展表

- `word_detail`：`memo_id`、`lemma`、`normalized_lemma`、`phonetics`、`meanings`、`context_sentence`、`familiarity`、`next_review_at`。
- `resource_detail`：`memo_id`、`site_name`、`resource_type`、`auto_category`、`category_status`、`category_confidence`、`classifier_version`、`cover_object_key`、`reading_status`、`estimated_minutes`、`metadata_status`、`link_health_status`、`last_checked_at`、`last_success_at`、`next_check_at`、`consecutive_failures`、`effective_url`、`metadata_fingerprint`。
- `idea_detail`：`memo_id`、`idea_stage`、`transcript`、`transcript_status`。
- `audio_asset`：`id`、`memo_id`、`object_key`、`duration_ms`、`mime_type`、`size_bytes`、`upload_status`、`checksum`。
- `image_asset`：`memo_id`、`object_key`、`thumbnail_object_key`、`mime_type`、`size_bytes`、`width`、`height`、`hash`；当前每条图片收藏一张，文件名由服务端条目 ID 生成。
- 图片压缩在客户端完成：超过 20 MB、单边 12000 像素或 5000 万像素时，各端先按尺寸/像素上限缩放并重新编码（Web 优先 WebP，Android 用 JPEG/PNG），迭代降低质量/尺寸到 20 MB 以内，再按正常上传流程提交，并用提示告知用户压缩前后的大小与变化。服务端只保留上限校验，不做二次编码。
- 图片 OCR 结果直接落在 memo 上：`image_ocr_text`、`image_ocr_status`（none/pending/processing/ready/failed/disabled）、`image_ocr_error`、`image_ocr_source`（local/llm）、`image_auto_tags`、`image_ocr_updated_at`，跨端同步与搜索共用这些字段。
- OCR 采用可插拔渠道：`local` 用本地引擎（rapidocr-onnxruntime 优先、pytesseract 兜底，图片不出本机），`llm` 用 OpenAI 兼容视觉模型（图片转 data URL，按最大边 1600 预览压缩后发送），`auto` 本地优先、不可用时回退；默认 `none` 关闭。自动标签为“模型标签 + 本地关键词（英文词频、中文 4 字窗口）”合并去重。

数组型释义在 MVP 可使用 JSONB，但需要为常用搜索文本维护扁平化索引字段。

### 4.3 组织关系

- `tag` 与 `memo_tag`：多对多标签。
- `collection` 与 `memo_collection`：多对多收藏夹。
- `review_event`：记录单词反馈、复习时间和计划结果。
- `memo_revision`：保留正文冲突或显式版本历史，至少支持最近版本恢复。
- `async_job`：记录元数据、自动分类和转写任务状态，避免只依赖队列内状态。
- `resource_category_template`：记录用户自定义分类编码、名称、说明、启用状态和版本。
- `resource_category_rule`：记录用户规则的目标分类、匹配范围、匹配文本、优先级、启用状态和版本。
- `bookmark_import_batch`：记录用户、来源、总数、成功/跳过/失败数、状态、创建时间和撤销时间。
- `bookmark_import_item`：记录批次、原文件夹路径、规范化网址、关联条目、处理状态和错误码。
- `link_check_event`：记录资料、检查时间、结果类型、HTTP 状态码、耗时、重定向目标和错误码，不保存响应正文。

### 4.4 网页资料自动分类

- 分类输入仅使用规范化网址、域名、标题、描述和可合规读取的页面元数据，不使用用户登录态或受限网页正文。
- 分类按用户规则、系统规则、大模型、其他的顺序执行；用户规则支持域名、网址包含和标题/描述关键词三种匹配范围。
- 大模型只能从系统分类和当前用户启用的分类模板中返回结构化结果，不允许生成新分类；响应必须经过 JSON Schema 和服务端白名单校验。
- 网页标题、描述和网址都按不可信数据处理：分类提示词固定，大模型不获得工具调用能力，网页内容中的指令不得改变分类规则。
- 云端大模型只接收分类所需的最小元数据，不发送用户备注、Cookie、访问令牌或受限网页正文；服务商凭证通过密钥管理注入。
- 调用设置短超时、有限重试、并发限制和熔断；超时、限流、无效响应或服务不可用时降级到规则结果或“其他”。
- 元数据任务完成后触发分类任务；同一资料与分类器版本组合必须幂等，并支持失败重试。
- Web 修正分类时写入人工覆盖值，后续自动重跑不得覆盖人工选择。
- 用户分类模板说明会传给分类适配器作为最小分类上下文；用户新增或修改规则后，后台只重新处理受影响的自动分类资料。
- 若使用自托管文本分类模型，训练与推理严格使用 PyTorch；推理使用 `@torch.inference_mode()`，设备由运行时配置决定。外部大模型通过独立适配器调用，业务层不绑定具体供应商。
- 仅记录分类代码、置信度、规则或模型版本和耗时，不在日志中记录标题、网址或用户备注。

### 4.5 浏览器书签导入

- 扩展使用 Manifest V3 `bookmarks` 权限读取当前 Chrome/Edge 书签树，只同步标题、网址和原文件夹路径；后端按用户和扩展标识持久化最近完整快照，Web 打开导入窗口后直接读取该快照。
- 扩展安装、浏览器启动、书签增删改移动以及批量导入完成时刷新完整快照；连续变更通过防抖合并，单次最多同步 5000 条并返回截断状态。
- 未安装新版扩展时，Web 可在浏览器本地解析 Chrome 导出的标准书签 HTML，只提交相同的结构化字段；服务端不保存原始书签文件。
- HTML 仅作为数据解析，禁止执行脚本、加载远程资源或渲染其中的活动内容。
- 只接收 HTTP(S) 链接；统一规范化协议、主机、默认端口和可安全移除的片段后，再按用户与规范化网址去重。
- 导入预览和确认分离；确认后创建批次，分块提交，避免大文件占用单次请求与数据库事务。
- 每个导入项使用批次标识与源项目标识保证幂等，重试不得产生重复资料。
- 新条目提交后立即写入基础搜索字段，再异步执行元数据抓取、自动分类和自动标签。
- 撤销批次只将该批次新建且之后未被用户独立修改的条目移入回收站，不删除导入前已存在的资料。
- 文件大小、书签数量和单批并发数由服务端配置限制；错误响应只返回项目序号和错误码，不回显完整私人网址列表。

### 4.6 `@网页` 浏览器扩展

- 扩展使用 Manifest V3 的 `tabs` 权限，读取当前浏览器各窗口中已打开标签页的 URL、标题和可用图标，供 Web 的 `@网页` 菜单选择；`activeTab`/`scripting` 仅在用户触发当前页动作时用于读取选中文本。
- 扩展在安装、浏览器启动以及标签页创建、URL/标题/图标更新、切换、关闭时提交完整打开网页快照；服务端将快照中缺失的标签页标记为关闭，超过 10 分钟未同步的过期快照不展示。
- 扩展只同步 HTTP(S) 公网页面的基础信息，不读取 Cookie、表单内容、未选中的页面正文或用户登录态；用户明确触发动作时最多读取 10000 字选中文本。`chrome://`、`file://`、扩展页和本地/内网目标在客户端与服务端双重过滤。浏览历史需要 `history` 权限：首次同步备份**全部历史**（先二分定位最早记录，再按 7 天窗口从近到远扫描，命中单次 1000 条上限就对半二分；每轮最多推进 30 个窗口约 7 个月，断点存 `backfillCursor`。MV3 后台空闲约 30 秒会被回收，`setTimeout` 不能用来续跑：平时浏览时每次推进一轮，电脑闲置 5 分钟或锁屏时由 `chrome.idle` 触发连续推进，单次最多 4 分钟；保持闲置时由 `chrome.alarms` 每 5 分钟唤醒续跑，补完即撤销闹钟。浏览触发和闲置触发共用同一个互斥入口，不会并发扫描同一段历史），之后按 `chrome.history.search` 的 `startTime` 游标增量上报，游标与重叠窗口存在 `chrome.storage.local`；未登录不读取，退出登录清空游标；浏览器清空历史时以 `replace_all` 请求清空当前设备的记录（保留回填断点，避免重扫）。服务端按 `(user_id, device_id, url_key)` 去重写入 `browser_history_entry`：扩展首次安装生成 `device_id`（存 `chrome.storage.local`）随每次上报提交，同一账号的多台电脑各存各的。列表默认按网址合并所有设备（访问次数相加、时间取最近、设备取最近访问的那台），传 `device_id` 则只看单台设备；`replace_all` 只清当前设备的记录，不会误删其他电脑的数据。

设备识别不依赖 MAC 地址（浏览器无此 API，且各系统默认随机化 MAC）。扩展用「系统 + 架构 + 时区 + 语言 + CPU 核心数」算 SHA-256 得到 `hardware_key`，这些属性重装扩展后不变；另有一个每次安装重新生成的 `install_id`。服务端据此区分三种情况：指纹与 `install_id` 都一致是同一台机器；指纹相同但 `install_id` 不同，要么是重装、要么是同款电脑，返回 `possible_same_device_id` 由用户确认；指纹不同则直接当作新设备。确认合并时 `POST /browser-history/devices/{id}/merge` 把来源设备的记录并入目标（重复网址累加次数、时间取并集），还提供 `PATCH`（改名）与 `DELETE`（删除单台设备）用于清理不再同步的旧设备。设备 ID 另写一份到 `memoisle_device` Cookie（HttpOnly、一年有效）：卸载扩展会清空 `chrome.storage.local`，但 Cookie 不会被删，重装后可据此认回原设备；仅在 Cookie 中设备的 `install_id` 与本次上报一致时启用，避免同浏览器的另一个扩展实例被误吞。MV3 的 service worker 没有 DOM，`localStorage`/`document`/`screen`/`matchMedia` 均不可用，因此网页端的字体、屏幕、媒体查询类指纹在扩展里无法采集。合并视图用 `NOT EXISTS` 让每个 `url_key` 恰好剩最新一行，配合 `(user_id, url_key, last_visited_at)` 索引，游标分页天然精确且代价与库大小无关。`visit_count` 取浏览器累计次数的较大值，因此重复上报不会虚增。
- 用户触发扩展动作时，当前页仍保存为短时一次性记录并打开 Web 快速捕获；在 Web 输入 `@` 时可选择当前浏览器其他已打开网页，切换标签页不得改变已生成附件。
- Web 与扩展的外部消息连接只允许生产和本地开发的 MemoIsle 来源；消息校验来源、扩展标识、随机 nonce、过期时间和一次性消费状态。
- 页面上下文只接受 HTTP(S) URL，并再次通过服务端 URL 校验；拒绝 `chrome://`、`file://`、扩展页和本地/内网目标。
- 扩展默认只提供页面基础信息，公开元数据仍由服务端 SSRF 防护任务抓取；只有用户明确选择的文本才作为网页正文上传。
- 扩展提供图片右键菜单：用户右键网页图片时，后台仅在用户点中的那张图片地址上读取二进制，按服务端限制（20 MB / 12000 px / 5000 万像素）判断是否需要压缩，再创建 `type=image` 条目并上传原图；`blob:` 临时地址和不支持的格式（如 SVG）会给出明确提示而不静默失败。
- 为支持任意站点取图，清单新增 `<all_urls>` 主机权限；该权限只扩大后台 `fetch` 的可访问范围，不向网页注入内容脚本，内容脚本仍只匹配本地 MemoIsle 页面用于凭证桥接，也不读取历史、Cookie、表单或未选中的页面正文。
- 扩展不写死 Web 与 API 端口：内容脚本在 MemoIsle 页面登记本页源，页面回答自己的 API 地址；后台只在来源通过信任校验（显式配置的 Web 源或本地开发端口 5173–5178）且登记的是发送者自身源时写入 `chrome.storage.local`，本地开发来源只接受同源 API 地址。地址优先级为显式配置 > 页面登记 > 内置默认，连接失败时把实际尝试的 API 地址通过 `memoisle_capture_api` 交给 Web 展示。
- 扩展授权或通信失败不能清空用户已输入的备注；Web 回退到粘贴网址流程。
- 身份认证使用可撤销、短期且仅具收藏权限的扩展令牌，不把 Web 会话 Cookie 或长期访问令牌写入页面 URL。
- 后端按请求将 `manifest.json`、后台脚本和安装说明打包为 ZIP；下载包不包含测试、依赖、数据或密钥，Web 顶栏与未连接状态均指向该接口。

### 4.7 网页健康巡检

- 调度器按 `next_check_at` 分批生成任务，并加入随机抖动，避免同一时间集中访问外部站点。
- 每个站点设置并发和速率上限，使用明确的产品 User-Agent；连续失败采用指数退避。
- 优先进行轻量请求；站点不支持时再使用限制响应大小的 GET。不得下载完整大文件、视频或受限正文。
- 每次请求及每次重定向都重新执行协议、DNS、IP 和端口校验，阻止本机、内网、云元数据地址及 DNS 重绑定造成的 SSRF。
- 2xx 记为正常；永久重定向记录候选新网址；401/403 记为访问受限；429 和 5xx 记为暂时失败；404/410、DNS、TLS 或超时只有连续达到配置阈值后才确认失效。
- 元数据指纹只覆盖标题、描述、规范网址等允许保存的字段，用于提示信息变化；不保存或对比完整网页正文。
- 确认失效后写入系统视图“失效网页”，不修改用户分类、不移入回收站，也不从搜索索引删除。
- 用户采用重定向网址时通过带版本号更新，保留旧网址修订记录并重新触发元数据、分类和索引任务。
- 全站暂停、单资料忽略和人工重试必须可审计；忽略状态不再自动提醒，但用户可恢复巡检。

## 5. API 边界

建议使用版本化 JSON API：

| 方法与路径 | 作用 |
| --- | --- |
| `GET /v1/auth/providers` | 读取可用登录方式 |
| `POST /v1/auth/register` | 使用邮箱和密码注册 |
| `POST /v1/auth/verification-code` | 发送六位邮箱注册验证码 |
| `POST /v1/auth/login` | 使用邮箱和密码登录 |
| `POST /v1/auth/verify-email/request` | 重新发送邮箱验证链接 |
| `POST /v1/auth/verify-email` | 验证邮箱所有权 |
| `POST /v1/auth/password-reset/request` | 请求密码重置链接 |
| `POST /v1/auth/password-reset` | 使用一次性令牌重置密码 |
| `GET /v1/auth/{provider}/authorize` | 跳转到第三方授权页 |
| `GET/POST /v1/auth/{provider}/callback` | 处理 OAuth 回调并回跳客户端 |
| `GET /v1/auth/me` | 读取当前登录用户 |
| `POST /v1/auth/logout` | 撤销当前 Bearer 会话 |
| `GET /v1/exports/json` | 导出 JSON 数据副本 |
| `GET /v1/exports/csv` | 导出 CSV 数据副本 |
| `GET /v1/exports/markdown` | 导出 Markdown 数据副本 |
| `POST /v1/memos` | 幂等创建条目 |
| `GET /v1/memos` | 分页、搜索、筛选和增量拉取；网页资料默认由 Web 每页读取 10 条 |
| `GET /v1/memos/counts` | 返回未删除条目的类型数量，用于导航和列表摘要 |
| `GET /v1/memos/{id}` | 获取条目详情 |
| `PATCH /v1/memos/{id}` | 带版本号更新条目 |
| `DELETE /v1/memos/{id}` | 移入回收站 |
| `POST /v1/memos/{id}/restore` | 从回收站恢复 |
| `DELETE /v1/memos/{id}/permanent` | 永久删除回收站条目 |
| `POST /v1/memos/{id}/audio-upload` | 获取录音上传凭证 |
| `POST /v1/memos/{id}/transcriptions` | 创建或重试转写任务 |
| `POST /v1/memos/{id}/image` | 上传或替换图片原图（受限格式/大小，服务端生成缩略图） |
| `GET /v1/memos/{id}/image` | 按所有者读取图片原图 |
| `GET /v1/memos/{id}/image/thumbnail` | 按所有者读取 WebP 缩略图 |
| `POST /v1/memos/{id}/image/ocr` | 手动重试图片文字识别与自动标签；未启用时返回 503 |
| `POST /v1/speech/tts` | 使用可选 sanoTTS 生成 WAV 语音 |
| `POST /v1/words/lookup` | 查词预览并返回可选择的词义、例句、音标和音频 |
| `POST /v1/words/import` | 导入 MemoIsle JSON 或常见 CSV 单词，按词形去重并返回逐行结果 |
| `POST /v1/words/{id}/merge` | 合并已有单词的新语境 |
| `POST /v1/words/{id}/reviews` | 提交单词复习反馈 |
| `GET/PATCH /v1/review-settings` | 读取或更新账号级每日队列上限与复习间隔 |
| `GET /v1/review-queue` | 获取今日回顾混合队列 |
| `POST /v1/review-queue/{id}/skip` | 跳过当前回顾条目 |
| `GET /v1/sync/changes` | 按 `updated_at + id` 游标增量同步，包含回收站变更 |
| `GET /v1/exports/json` | 下载当前用户的 JSON 数据副本；包含保留期内的回收站条目，不含令牌和录音二进制 |
| `POST /v1/bookmark-imports/preview` | 校验结构化书签并返回去重预览 |
| `POST /v1/bookmark-imports` | 创建并执行确认后的导入批次 |
| `GET /v1/bookmark-imports/{id}` | 获取导入进度与失败摘要 |
| `POST /v1/browser-bookmarks/sync` | 扩展同步当前浏览器书签树快照 |
| `GET /v1/browser-bookmarks/current` | Web 读取最近书签快照并进入导入预览 |
| `POST /v1/bookmark-imports/{id}/retry` | 重试失败项目 |
| `POST /v1/bookmark-imports/{id}/undo` | 撤销本批次新建资料 |
| `GET /v1/browser-extension/download` | 下载可解压安装的浏览器扩展 ZIP |
| `POST /v1/browser-tabs/sync` | 扩展同步当前浏览器打开网页快照 |
| `GET /v1/browser-tabs/open` | Web 读取当前浏览器可选择的打开网页 |
| `POST /v1/browser-history/sync` | 扩展上报浏览历史；按规范化网址摘要合并，`visit_count` 取较大值 |
| `GET /v1/browser-history` | Web 读取浏览历史，支持 `q`、`offset`、`cursor`、`limit`（≤1000）、`days`、`from`/`to`（本地日期）与 `tz_offset`（分钟）；`days` 只在账号开启扩展搜索后生效（30/90/365/0=全部）；`from`/`to` 优先于 `days`；响应按日期分块（`days[].date/count/items`），并回传 `window_days` 与分页字段 `page_size`/`offset`/`has_more`/`next_offset`/`next_cursor` |
| `GET /v1/browser-history/settings` | 读取账号是否允许搜索更久的历史 |
| `PATCH /v1/browser-history/settings` | 打开/关闭「搜索更久的历史」，写入 `user.browser_history_extended_search` |
| `DELETE /v1/browser-history` | 清空当前账号的浏览历史与同步状态；资料库条目保留 |
| `POST /v1/browser-captures/exchange` | 使用一次性凭据交换扩展授权的当前页上下文 |
| `GET /v1/resources/link-health` | 分页读取失效、重定向和待更新资料 |
| `POST /v1/resources/{id}/link-checks` | 人工触发一次受限健康检查 |
| `POST /v1/resources/{id}/link-health-actions` | 忽略、恢复、采用新网址或确认元数据更新 |

创建接口使用 `client_id` 保证离线重试幂等；更新接口提交 `version`，冲突时返回服务端当前版本和可恢复的客户端内容。

浏览历史按 `offset` 分页，每页最多 1000 条（`MAX_HISTORY_PAGE_SIZE`），翻页没有总量上限；响应回传 `page_size`、`offset`、`has_more` 和 `next_offset`，前端用服务端的 `next_offset` 继续翻，不会被本地去重影响。

历史列表的性能约束：

- 索引 `(user_id, last_visited_at, id)` 覆盖排序键，翻页整段走索引，不需要临时 B 树；旧库启动时由 `_upgrade_browser_history_indexes` 自动换成三列版本。
- 查询用 `LIMIT page_size + 1` 探测是否还有下一页，末页直接用 `offset + len(items)` 得到总数，避免无谓的 `count(*)`；只有确实还有下一页时才精确计数。
- 分页只取列表需要的 7 列，不实例化整实体。
- 同步时 `total_count` 按「本次新增网址数」累加，只在首轮或 `replace_all` 后校准一次，不再每次同步都全表 count。
- 清空历史和 `replace_all` 都走批量 `DELETE`，几万条记录比逐条 ORM 删除快一个数量级。

深翻页用游标而非 OFFSET：

- OFFSET 分页要先跳过前面所有行，5 万条时约 14 ms，50 万条时约 23 ms，成本随深度线性增长。
- 响应在还有下一页时回传 `next_cursor`，是 `(last_visited_at, id)` 排序键的 base64 编码；下次请求改传 `cursor` 即可。
- 服务端用**行值比较** `(last_visited_at, id) < (?, ?)` 定位，索引范围直接命中，实测 50 万条下恒定 0.11 ms，与深度无关。拆成 `A < a OR (A = a AND id < b)` 会退化成整段扫描，慢 40 倍。
- 传了 `cursor` 就忽略 `offset`，且不再返回 `next_offset`，避免前端混用两种模式导致跳行；坏游标静默退回 offset 分页。
- 前端优先使用 `next_cursor`，没有时才退回 `next_offset`。

日期分块按浏览器时区（`tz_offset`，范围 ±840 分钟）换算本地日期，`from`/`to` 的边界同样按该偏移换算成 UTC 半开区间 `[start, end)`。

网页资料除原始 `source_url` 外还保存 `canonical_url`（规范化网址），并建有 `(user_id, canonical_url)` 索引：查重、书签导入预览和历史面板的「已收藏」标记都走这个索引，不再把整个资料库读进内存逐条比较。`canonical_url` 在创建时写入、来源网址变化时重算、转换为非网页资料时清空；旧库升级时按现有 `source_url` 回填一次。

## 6. 同步策略

### 6.1 写入流程

1. 客户端生成 `client_id` 和本地时间，先写本地数据库或草稿存储。
2. 同步队列按创建、文件上传、扩展更新的依赖顺序执行。
3. 服务端按 `user_id + client_id` 去重并返回正式 `id`、`version` 和服务端时间。
4. 客户端替换本地映射并标记同步完成。

### 6.2 冲突策略

- 标签、收藏夹采用集合合并。
- 状态字段采用显式版本检查，避免旧设备把归档内容恢复为活动状态。
- 标题和短字段默认保留最近服务端提交，并展示冲突提示。
- 正文、转写编辑和个人备注发生冲突时保存双方版本，用户可在详情页恢复。
- 删除操作使用墓碑记录，保证离线设备不会重新创建已删除内容。

### 6.3 失败恢复

- 同步任务采用指数退避并设置最大自动重试次数。
- 永久错误与临时错误分开显示。
- 未上传录音不得在清理缓存时删除。
- 用户退出账号前检查待同步队列，必要时阻止直接清除本地数据。

## 7. 语音处理

```text
Android 本地录音完成
  → MediaCodec 解码 AAC/M4A 为 16 kHz 单声道 PCM
  → sherpa-onnx SenseVoiceSmall INT8 设备端推理
  → 转写结果填入可编辑草稿
  → 原始录音独立保存并按原流程上传

Web 浏览器录音完成
  → 浏览器支持时用 SpeechRecognition 实时转写
  → 转写结果填入可编辑草稿
  → MediaRecorder 原始 Blob 按原流程上传

单词/句子/正文播放
  → 请求 `POST /speech/tts`
  → 服务端 sanoTTS 生成并缓存 WAV
  → Web/Android 播放
  → 服务不可用时回退词典音频或系统/浏览器 TTS
```

要求：

- 录音与转写是两个独立状态，转写失败不能影响录音保存和播放。
- Android sherpa-onnx 只使用 CPU provider，应用层不硬编码具体硬件；Release 首次使用时按需下载固定版本模型，校验 SHA-256 后原子安装到 `noBackupFilesDir`，模型文件不提交到 Git。
- Web SpeechRecognition 为可选浏览器能力，可能由浏览器语音服务处理，界面必须告知用户并保留手工输入。
- sanoTTS 依赖与音色包按其 GPL-3.0-or-later 许可单独审核；服务端合成结果使用内容哈希缓存，避免重复推理。
- 日志只记录任务标识、时长、模型版本、错误码和耗时，不记录音频或转写正文。

## 8. 搜索方案

MVP 可先使用 PostgreSQL 全文搜索与前缀匹配：

- 中文正文使用适合中文的分词或 n-gram 策略。
- 英文词形同时索引原文和规范化小写词形。
- 网页资料创建事务完成后立即索引标题、规范化网址、域名和用户备注。
- 元数据与自动分类任务完成后增量索引页面描述、站点、自动分类和自动标签。
- 自动分类作为结构化筛选字段建立索引，不依赖全文搜索解析。
- 语音只在转写成功后加入文本索引，录音本身不参与搜索。
- 搜索查询按所有者隔离，并对 `trashed` 默认过滤。
- 异步索引更新必须幂等；任务失败时保留创建阶段的基础索引，不能让已收藏资料从搜索中消失。

当数据规模或语义检索需求明确后再引入独立搜索服务或 PyTorch 向量模型，MVP 不提前增加该复杂度。

## 9. 安全与隐私

- 所有查询必须以认证用户为边界，服务端不接受客户端传入的任意 `user_id` 作为授权依据。
- 第三方客户端凭据和 `MEMOISLE_AUTH_TOKEN_SECRET` 只能来自密钥管理环境，不写入仓库或客户端。
- 传输使用 TLS；对象存储默认私有，下载使用短时签名地址。
- 访问令牌、密码、第三方 API 密钥通过密钥管理注入，不进入配置文件或仓库。
- 网页元数据服务阻止访问本机、内网、云元数据地址，防止 SSRF。
- 上传校验 MIME、大小和时长，文件名不作为可信输入。
- 账号注销进入可审计的异步删除流程，覆盖数据库、对象存储、索引与备份策略。
- 不上传数据集、临床图像或其他敏感测试资料到仓库。

## 10. 可观测性

- 指标：API 延迟与错误率、同步积压、上传成功率、分类成功率与低置信度比例、巡检成功率与站点退避、转写队列长度、任务耗时、搜索延迟。
- 日志：使用结构化日志和关联 ID，敏感内容在进入日志前脱敏。
- 追踪：捕获请求、文件上传、异步转写可通过同一关联 ID 串联。
- 产品事件：只发送事件名、内容类型、耗时区间和结果码，不发送用户内容。

## 11. 测试策略

- 单元测试：类型转换、重复检测、复习计划、同步合并和权限判断。
- 契约测试：Web、Android 与 API 的请求响应模型。
- 集成测试：离线创建后恢复、录音上传中断、Chrome 书签解析/去重/幂等/撤销、扩展消息来源与一次性凭据、大模型分类模拟与降级、巡检重定向/限流/连续失败/SSRF、自动分类重试、异步任务重试、回收站恢复。
- 端到端测试：三类内容创建、当前浏览器多个打开网页的 `@网页` 免复制收藏、Chrome 书签导入、资料自动分类与筛选、网页巡检与失效处理、跨端同步、搜索、单词复习、分享保存。
- 安全测试：越权访问、签名地址过期、恶意网址、异常文件上传。
- 性能测试：大资料库分页、并发同步、转写任务积压和搜索 P95。

## 12. 实施顺序

1. 统一数据模型、账号、基础 CRUD 和增量同步。
2. Web/Android 资料库与文字快速捕获。
3. Android 系统分享和网页元数据任务。
4. 语音本地草稿、上传、播放与转写。
5. 单词详情、复习事件和今日回顾。
6. 导出、可观测性、异常状态和发布验收。
