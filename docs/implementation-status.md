# MemoIsle 实现状态

| 字段 | 内容 |
| --- | --- |
| 里程碑 | M10：图片 OCR 与自动标签 |
| 状态 | 图片 OCR（本地引擎 / 视觉大模型 / 本地优先回退）与自动标签已实现，OCR 文本和标签参与搜索；后端测试、Web 构建、Android 单元测试与 APK 均通过；微信/Google/Apple 登录暂缓 |
| 更新日期 | 2026-09-20 |

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
  → 跨灵感、网页资料、英语单词和图片返回统一结果

图片收藏
  → Web 选择/拖拽/粘贴，Android 从系统相册选择，扩展右键网页图片
  → 先创建 type=image 条目（正文可为空），再上传受限格式的原始图片字节
  → 服务端校验真实格式并生成 WebP 缩略图，按所有者私有读取
  → Web 查看原图、替换、编辑；Android 只读浏览缩略图与原图
  → 永久删除或过期清理时同时移除原图与缩略图

图片 OCR 与自动标签
  → 上传/替换后后台排队，按配置渠道识别（本地引擎 / 视觉大模型 / 本地优先回退）
  → 写入 OCR 文本、状态、来源与自动标签（模型标签 + 本地关键词）
  → 识别文字与标签进入跨端搜索；Web 可手动重新识别，Android 只读展示

网页资料增强流程
  → 新版扩展直接读取当前浏览器书签，HTML 作为本地解析备用入口
  → 结构化书签统一预览去重
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
- `POST /api/v1/words/lookup` 提供查词预览，优先返回中文释义，并附带规范化词形、音标、英美音频和例句。
- `POST /api/v1/words/import` 支持从 MemoIsle JSON 导出或常见 CSV 批量导入单词，按词形去重并返回逐行错误。
- 词典预览应用所选内容时保留手工填写；后台词典补全只填充空白字段，不覆盖用户内容。
- 提供到期复习队列以及“忘记 / 模糊 / 记得”三档反馈接口。
- 英语单词按规范化词形检测重复；默认 409 提示已有条目，可合并例句或 `allow_duplicate` 仍然保存。
- `POST /api/v1/words/{id}/merge` 把新释义、例句或来源合并进已有单词。
- `GET/PATCH /api/v1/review-settings` 支持按账号配置每日回顾队列上限和六档复习间隔；未配置时保持 10 条、1/3/7/14/30/60 天默认行为。
- `GET /api/v1/review-queue` 返回今日回顾混合队列：到期单词、未读网页资料和收件箱灵感，按复习计划限制队列条数，可按类型筛选；`POST /api/v1/review-queue/{id}/skip` 将条目移出当天回顾。
- 新灵感默认进入收件箱，整理完成后变为 active，不再出现在待整理队列。
- Web 侧栏与 Android 顶栏提供收件箱页面，列出全部 `inbox` 条目，支持整理完成和归档。
- 支持原始音频上传和播放，限制为受支持音频格式、20 MB 和一小时以内；Android 录音停止后使用 sherpa-onnx SenseVoiceSmall INT8 在设备端转写。
- 图片收藏使用 `image` 类型：正文可为空，保存标题与备注，并支持一张原图。上传接受 PNG/JPEG/WebP/GIF、单张 20 MB、单边 12000 像素且不超过 5000 万像素，服务端校验真实格式并用 EXIF 方向生成最大边 1280 像素的 WebP 缩略图；超限字节在解码前返回 413/422 作为安全兜底。
- Web 与 Android 客户端在图片超过服务端限制时先自动压缩/缩放再上传（未超限不改动原图），并提示原大小→新大小、尺寸/格式变化和动图转静态；压缩在客户端完成，服务端不做二次编码。
- 图片元数据（MIME、字节数、宽高、SHA-256）随条目返回；原图与缩略图都按所有者校验后读取，文件名完全由服务端条目 ID 生成；永久删除、清空回收站和过期清理会同时移除图片文件。
- 图片收藏计入 `/memos/counts` 的 `image_count`，可参与类型筛选与跨类型搜索；条目类型在图片与其他类型之间暂不支持互转。
- 服务端提供可插拔图片 OCR：`MEMOISLE_IMAGE_OCR_PROVIDER` 支持 `none`/`local`/`llm`/`auto`（默认 `none` 关闭）。`local` 用 rapidocr-onnxruntime（pip 安装、模型随包、离线）或 pytesseract（需系统 tesseract），图片不出本机；`llm` 复用 OpenAI 兼容视觉模型，先把图片压成最大边 1600 的 JPEG data URL 再发送；`auto` 本地优先、本地不可用时回退视觉模型。
- 上传或替换图片后在后台识别，结果写入 `image_ocr_text`、`image_ocr_status`、`image_ocr_error`、`image_ocr_source`、`image_auto_tags` 和 `image_ocr_updated_at`；识别失败或未启用不影响图片本身保存，`POST /api/v1/memos/{id}/image/ocr` 可手动重试，服务重启会恢复遗留的 `pending`/`processing` 条目。
- 自动标签由视觉模型返回的标签与本地关键词（英文词频、中文 4 字窗口，均过滤噪声）合并去重；`q` 搜索覆盖 OCR 文本与自动标签，`tag` 过滤同样命中自动标签；备份导入会恢复 OCR 文本与标签（二进制仍需重新上传）。
- 提供 `POST /api/v1/speech/tts` 服务端语音合成接口，使用可选 sanoTTS 生成 WAV；Web 与 Android 均有词语、例句或正文播放入口，并带词典/系统/浏览器回退。
- 音频文件名完全由服务端生成，下载前检查条目所有者。
- 已有 SQLite 数据库自动补充资料来源字段，不清空原有灵感。
- SQLite 本地开发持久化；连接地址可通过环境变量替换。
- SQLite 连接启用 WAL 与 `busy_timeout=5000`：后台巡检读取不再阻塞界面保存和浏览器扩展同步写入，偶发同时写入改为短暂等待而不是直接报 `database is locked`。
- 使用 `user_id + client_id` 保证离线重试幂等。
- 使用 `version` 检测跨设备更新冲突，冲突返回 HTTP 409 和服务端当前内容。
- Android 首次同步完成全量校准，之后按 `updated_at + id` 游标分页增量同步；游标持久化在本地 SQLite，远端刷新保留本机录音路径和离线失败草稿。
- 永久删除、回收站清空和过期清理同事务保存最小删除通知；更新与删除共用分页游标和 `has_more`。Android 升级至数据库版本 13 后完整校准，再按通知清理本地记录、录音及图片缓存，已删除内容的离线重放返回 410。
- `POST /memos/batch` 对 1–100 条明确选择的版本逐项移入回收站、还原或永久删除；冲突和状态变化跳过，其他选择继续完成，附件在永久删除提交后清理。
- 图片批量整理使用本地 PyTorch EasyOCR 中英文识别，预先准备权重、运行时禁用下载；Jev 只接收识别文字和标题，按现有模板判断。任务记录版本及文件哈希、持久化游标和租约，已处理或人工分类跳过，服务故障可继续，低置信度或无文字保留分类。精确重复图片按文件 SHA-256 分组和分页，不自动删除。
- `GET /memos?q=` 支持模糊搜索，并可与类型、分类、资源形态、阅读进度、健康状态、标签、收藏夹、星标、状态、创建日期和排序组合。
- 模糊搜索按空白与常见分隔符拆分关键词，关键词之间是「与」关系且与词序无关；中英文连写会按边界继续拆分，因此「React教程」也能命中「React 教程」。
- 搜索覆盖标题、正文、来源、页面元数据、分类、导入文件夹、自动标签、单词字段和转写，并转义 LIKE 通配符。
- 网页资料按规范网址去重，新增资料立即进入搜索和后台处理队列；书签批量导入对重复项自动跳过。
- 重复网址会返回可处理提示，Web 与 Android 均可查看已有资料或确认仍然保存；书签批量导入仍按重复项记账。
- 普通列表与搜索在执行条数限制前按更新时间倒序，确保最新收藏不会被旧数据截掉；增量同步按 `updated_at + id` 正序游标推进，兼容同一时间戳的分页边界。
- 网页资料支持文章、视频、课程、工具、书籍、其他六种资源形态，以及未读、阅读中、已完成、归档四种阅读进度；个人收藏夹和星标与系统自动分类分开保存。
- 网页元数据任务具备公网 URL/重定向 SSRF 防护、大小/超时限制和重启恢复。
- 自动分类提供“用户分类模板/规则 → 用户口径判定 → 系统七类兜底 → 关键词 → 其他”的处理链，并校验模型返回的分类白名单。
- 每个自定义分类可写“分类口径”：判定说明、属于的例子、边界反例；判定时连同该账号已人工确认的历史样本一起发给模型。口径为空时仍按分类名称和路径判断网页用途。
- 自动分类在配置了对话模型和 Jev 时分两步：对话模型根据当前网页和已确认样本列出所有成立的功能标签（白名单内，可多选），再由 Jev 在这份候选里做最终分类；其余成立的标签作为附加分类和自动标签保留，并写入 `proposed_categories` 供界面展示。没有 Jev 时对话模型的列表直接作为分类结果。DeepSeek 请求失败时 Jev 回退到完整模板判定。两者都未配置时后台任务按配置错误报出，不会用规则结果冒充模型分类。已完成的模型分类可通过「重新分类已完成」再排队一轮，人工确认和确认失效的网页不纳入。
- 「智能生成分类」先列出当前顶级分类，由用户确认是否够用。够用后按这些大类生成细类；不够则先补顶级分类，加入模板后再细分。读取最近网页的标题、站点和公开摘要。结果直接显示在网页资料页。加入模板后需再跑分类才会写到网页上。
- 有更具体的子类时不会停在大类。有自定义细类时高置信度关键词规则不再抢先定案。
- 人工在确认中心指定或采纳分类后，该条目立即成为目标分类的正例；被改掉的模型首选则成为原分类的反例，下一次判定即可用。
- 自动分类置信度阈值按账号保存在模型服务设置里（默认 0.7），低于阈值的结果进分类确认中心，可在设置页调整以平衡自动分类与人工确认。
- Web 支持创建、停用自定义分类模板，配置域名、网址或标题/描述关键词规则；规则会应用到已有网页资料，Android 同步显示自定义分类名称。
- Web「分类确认中心」完整分页复核未确定分类，支持搜索、原因、首选候选和置信度筛选，以及批量采纳候选、指定分类、保留原分类。也可把全部待确认网页重新交给大模型和 Jev 分类，不把其余未处理网页一并排队。版本冲突、停用候选和确认失效条目逐项跳过；人工确认保留原模型证据并停止自动分类，旧批次未保存候选的网页也可指定或保留分类。
- 网页健康调度支持同站点单轮限流、连续失败阈值、指数退避、审计事件、账号开关、账号频率和站点暂停；单条资料可在巡检中心暂停或恢复。
- 微信、Google 和 Apple ID OAuth 授权码登录代码已保留，`state` 使用 HMAC 签名并限制回跳来源；默认关闭，需显式设置 `MEMOISLE_OAUTH_LOGIN_ENABLED=true` 且凭据完整才会对外授权。
- 支持邮箱密码注册与登录，密码使用 PBKDF2-SHA256、随机盐和 600,000 次迭代保存。
- 邮箱注册先发送六位验证码，验证码只保存哈希并限制有效期、重发间隔和错误次数；注册成功后邮箱立即验证，旧版本未验证账号仍支持验证链接。
- 邮件发送优先调用 `agently-cli`，自动完成确认令牌流程；CLI 不可用时回退 SMTP，开发模式可写入本地 `.eml` 收件箱。
- 支持一次性密码重置链接；重置成功后更新密码、验证邮箱并撤销既有会话。
- 同一邮箱 15 分钟内连续 5 次登录失败后返回 429，并携带 `Retry-After`。
- 登录成功创建 `user` 与 `auth_identity`，签发 opaque Bearer 会话；数据库只保存令牌哈希，支持撤销。
- 所有业务接口通过认证依赖取得当前用户，不接收客户端传入的 `user_id`。
- 显式开启 `MEMOISLE_AUTH_DEV_MODE` 时提供本地开发登录，生产环境默认关闭该入口。
- 删除进入回收站并记录 `deleted_at`；默认保留 30 天，到期后读取回收站或巡检循环会永久删除条目和录音文件。
- `DELETE /memos/{id}` 移入回收站，`POST /memos/{id}/restore` 恢复到进入回收站前的状态，`DELETE /memos/{id}/permanent` 永久删除。
- `PATCH /memos/{id}` 支持在保留标题、正文和来源链接的前提下转换条目类型，并清理不适用的扩展字段。

当前接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/auth/providers` | 读取可用登录方式；第三方登录默认全部关闭 |
| POST | `/api/v1/auth/register` | 使用邮箱和密码注册 |
| POST | `/api/v1/auth/login` | 使用邮箱和密码登录 |
| POST | `/api/v1/auth/verification-code` | 发送六位邮箱注册验证码 |
| POST | `/api/v1/auth/verify-email/request` | 重新发送邮箱验证链接 |
| POST | `/api/v1/auth/verify-email` | 验证邮箱所有权 |
| POST | `/api/v1/auth/password-reset/request` | 请求密码重置链接 |
| POST | `/api/v1/auth/password-reset` | 使用一次性令牌重置密码 |
| GET | `/api/v1/auth/{provider}/authorize` | 跳转第三方授权页 |
| GET/POST | `/api/v1/auth/{provider}/callback` | 处理 OAuth 回调并回跳 Web 或 Android |
| GET | `/api/v1/auth/me` | 读取当前登录用户 |
| POST | `/api/v1/auth/logout` | 撤销当前登录会话 |
| POST | `/api/v1/memos` | 幂等创建条目 |
| GET | `/api/v1/memos` | 读取条目；支持关键词、类型、分类、资源形态、阅读进度、标签、收藏夹、星标、状态、日期和排序参数；网页资料支持 `limit`/`offset` 分页，并返回当前筛选条件的 `total_count` |
| GET | `/api/v1/memos/counts` | 读取未删除的单词、网页资料、灵感和全部内容数量 |
| GET | `/api/v1/exports/json` | 下载当前账号的 JSON 数据副本，不含访问令牌和录音二进制 |
| GET | `/api/v1/exports/csv` | 下载当前账号的 CSV 数据副本 |
| GET | `/api/v1/exports/markdown` | 下载当前账号的 Markdown 数据副本 |
| POST | `/api/v1/imports` | 导入 JSON 或 CSV 备份；JSON 同时恢复自定义分类模板 |
| POST | `/api/v1/words/import` | 导入 JSON/CSV 单词并返回新增、重复、跳过和失败摘要 |
| GET | `/api/v1/resource-categories` | 读取系统分类和当前用户自定义分类模板 |
| POST | `/api/v1/resource-categories` | 创建用户自定义分类模板，可同时写入分类口径、属于与不属于的例子 |
| PATCH | `/api/v1/resource-categories/{id}` | 修改或停用用户自定义分类模板；可更新口径和正反例 |
| GET | `/api/v1/resource-classification/review` | 当前账号未确定网页的完整分页与候选、原因（含“口径都不匹配”）、置信度筛选 |
| POST | `/api/v1/resource-classification/review/retry` | 把待确认网页重新排队给大模型和 Jev；任务进行中返回 409，不沿用暂停任务的已处理游标 |
| POST | `/api/v1/resource-classification/classified/retry` | 把已完成模型分类的网页重新排队给大模型和 Jev；人工确认、规则保护和确认失效的条目跳过 |
| POST | `/api/v1/resource-classification/review/confirm` | 按所见版本批量采纳候选、保留分类或指定分类；逐项返回冲突和其他跳过原因 |
| GET | `/api/v1/resource-category-rules` | 读取当前用户分类规则 |
| POST | `/api/v1/resource-category-rules` | 创建分类规则并应用到已有资料 |
| PATCH | `/api/v1/resource-category-rules/{id}` | 修改分类规则 |
| DELETE | `/api/v1/resource-category-rules/{id}` | 删除分类规则 |
| GET | `/api/v1/model-settings` | 读取各模型服务的生效配置，含自动分类置信度阈值与服务器默认值 |
| PUT | `/api/v1/model-settings/{provider}` | 保存模型配置；`min_confidence` 留空恢复默认阈值 |
| DELETE | `/api/v1/model-settings/{provider}` | 删除账号配置并恢复服务器默认值 |
| GET | `/api/v1/memos/{id}` | 读取详情 |
| PATCH | `/api/v1/memos/{id}` | 带版本号编辑 |
| DELETE | `/api/v1/memos/{id}` | 移入回收站 |
| POST | `/api/v1/memos/{id}/restore` | 从回收站恢复 |
| DELETE | `/api/v1/memos/{id}/permanent` | 永久删除回收站条目 |
| GET | `/api/v1/sync/changes` | 按 `updated_at + id` 游标增量同步 |
| POST | `/api/v1/words/lookup` | 查词预览并返回可选择的词义、例句、音标和音频 |
| GET | `/api/v1/review-queue` | 读取今日回顾；可按 `type` 筛选单词、资料或灵感，并返回各类待回顾数量 |
| POST | `/api/v1/review-queue/{id}/skip` | 跳过当前回顾条目，当天不再出现 |
| POST | `/api/v1/words/{id}/merge` | 把新语境合并进已有单词 |
| POST | `/api/v1/words/{id}/reviews` | 提交三档复习反馈 |
| POST | `/api/v1/memos/{id}/audio` | 上传原始录音 |
| GET | `/api/v1/memos/{id}/audio` | 在线播放或下载录音 |
| POST | `/api/v1/memos/{id}/image` | 上传或替换图片收藏的原图（裸二进制 + `Content-Type`） |
| GET | `/api/v1/memos/{id}/image` | 查看图片收藏原图 |
| GET | `/api/v1/memos/{id}/image/thumbnail` | 查看图片收藏 WebP 缩略图 |
| POST | `/api/v1/memos/{id}/image/ocr` | 手动重试图片文字识别与自动标签；未启用返回 503 |
| POST | `/api/v1/meeting/summary` | 通过 OpenAI 兼容模型生成会议纪要 |
| POST | `/api/v1/speech/tts` | 使用 sanoTTS 生成私有 WAV 语音 |
| POST | `/api/v1/bookmark-imports/preview` | 书签校验、文件夹保留与去重预览 |
| POST | `/api/v1/bookmark-imports` | 创建异步书签导入批次 |
| GET | `/api/v1/bookmark-imports/{id}` | 获取批次和逐项进度 |
| POST | `/api/v1/bookmark-imports/{id}/retry` | 重试失败项目 |
| POST | `/api/v1/bookmark-imports/{id}/undo` | 撤销未编辑的本批资料 |
| GET | `/api/v1/browser-extension/download` | 下载可解压安装的浏览器扩展 ZIP |
| POST | `/api/v1/browser-tabs/sync` | 扩展同步当前浏览器打开网页快照 |
| POST | `/api/v1/browser-bookmarks/sync` | 扩展同步当前浏览器书签树快照 |
| GET | `/api/v1/browser-bookmarks/current` | Web 读取最近书签快照 |
| GET | `/api/v1/browser-tabs/open` | Web 读取当前浏览器可选择的打开网页 |
| POST | `/api/v1/browser-captures` | 扩展提交当前页并换取短时凭据 |
| POST | `/api/v1/browser-captures/exchange` | Web 一次性消费当前页凭据 |
| POST | `/api/v1/resources/{id}/enrich` | 重试网页元数据与分类 |
| POST | `/api/v1/resources/{id}/open` | 记录一次打开原网页；只累加打开次数和最近打开时间，不改版本号与 `updated_at` |
| GET | `/api/v1/resources/quick-access` | 快速访问：打开过、未移除、不在回收站的网页资料，按打开次数降序 |
| PUT | `/api/v1/resources/{id}/quick-access` | 从快速访问移除或恢复；移除后继续计数，不改版本号 |
| GET | `/api/v1/resources/link-health` | 读取巡检中心、状态摘要和账号巡检设置 |
| PATCH | `/api/v1/resources/link-health/settings` | 更新账号巡检开关和检查频率 |
| POST | `/api/v1/resources/link-health/site-pauses` | 暂停或恢复某个网站的全部巡检 |
| POST | `/api/v1/resources/{id}/link-checks` | 人工触发链接巡检 |
| POST | `/api/v1/resources/{id}/link-health-actions` | 重试、更新、忽略或删除巡检结果 |
| GET | `/api/v1/cloud-accounts` | 列出当前用户已绑定的云盘账号 |
| POST | `/api/v1/cloud-accounts` | 绑定云盘：先校验凭据，再加密保存 |
| DELETE | `/api/v1/cloud-accounts/{id}` | 解绑云盘账号 |
| POST | `/api/v1/cloud-accounts/{id}/verify` | 重新校验云盘凭据并刷新状态 |
| GET | `/api/v1/ebooks/jobs` | 列出最近的电子书任务 |
| POST | `/api/v1/ebooks/jobs` | 提交电子书链接并后台开始转存/上传 |
| GET | `/api/v1/ebooks/jobs/{id}` | 查询单个电子书任务进度 |
| POST | `/api/v1/ebooks/jobs/{id}/retry` | 重试失败的电子书任务 |

- 云盘绑定：凭据使用 `cryptography` Fernet 加密落库，接口只回显末四位提示；密钥来自 `MEMOISLE_CLOUD_CREDENTIAL_SECRET`，未设置时回退到登录密钥，因此生产环境必须显式设置，否则重启后旧凭据无法解密。
- 电子书任务：链接判定（阿里/百度云盘分享链接 → 转存；其他 http(s) 直链 → 服务端下载后上传）、进度与错误落库、失败可重试、服务重启自动恢复未完成任务。
- 直链下载复用网页抓取的安全设施：每一次重定向都重新做公网地址校验，并有硬性大小上限（`MEMOISLE_EBOOK_MAX_BYTES`，默认 2GB）与超时。
- 电子书以「书籍形态的资料」落库：`type=resource` + `resource_kind=book` + `ebook_*` 字段（云盘 file_id、路径、格式、大小、元数据快照），因此标签、分类、搜索、回收站全部直接复用；电子书本体不落在 MemoIsle。
- 任务成功后自动创建 Memo 并写入快照；命中重复链接时复用已有资料，不产生重复项。
- 资料接口返回 `ebook_provider` / `ebook_file_id` / `ebook_path` / `ebook_format` / `ebook_size_bytes` / `ebook_snapshot`，Web 列表用「云盘 · EPUB · 3.0 MB」徽标标出存储位置，客户端不依赖电子书本体即可确认文件存在哪。
- 电子书落库后不进入网页元数据抓取与链接巡检队列：云盘分享链接不是可巡检的公开网页，抓取它只会拿到分享页或错误，还会用分享页内容覆盖书名；改为在任务完成时用书名与链接就地做规则分类，分类状态直接为完成。
- 任务派发做了防重：只有失败任务可以重试，执行中的任务拒绝二次执行（后台派发与启动恢复可能同时碰到同一任务）；服务启动时先把上一次进程残留的「执行中」任务退回排队，避免它们永远卡住。

### Web

- 内容列表与回收站统一支持每页 10/25/50/100 条、当前页全选及选中条目操作，翻页、筛选和排序清除选择；删除最后一页内容后回到有效页码。
- 图片工作区支持全库或选中的 OCR 与模板归类、进度和暂停续跑；可按分类筛选，在详情查看依据或手动选择模板。重复图片支持组分页及大组内分页，选中移入回收站后可还原。

- React + TypeScript + Vite。
- 提供登录门禁，当前只展示邮箱密码注册/登录；服务端开启第三方登录后才会显示微信、Google、Apple 入口。令牌保存在本地存储并自动附加 Bearer 请求头。
- 侧栏提供回收站：列出已删除内容、剩余天数、恢复和永久删除二次确认；详情和网页资料行可移入回收站。
- 登录后侧栏显示当前账号，可退出并撤销服务端会话。
- 录音上传和详情播放均携带认证凭据，音频 Blob 通过对象 URL 播放。
- 资料库工具栏提供「☁ 云盘绑定」与「▤ 收藏电子书」两个入口：前者粘贴云盘登录态、设置默认转存目录、重新校验或解绑；后者提交电子书链接（可选提取码、目录、标签、备注），并轮询展示任务阶段、进度与失败原因，失败可重试。
- 遵循 Stitch 的暖白背景、深青主色、柔和边框和 10/14 px 圆角体系。
- 侧栏以「首页」作为内容总览入口：展示今日回顾、快速捕获和最近内容，并可在灵感、网页资料、英语单词和图片工作区之间切换；Web 不再单独保留重复的「全部内容」项。
- 侧栏新增「图片收藏」工作区并显示图片数量：选择文件、拖拽图片或 `Ctrl/⌘+V` 粘贴截图即可创建条目并上传原图，逐个文件显示上传进度和错误。
- 超出服务端限制的图片先用 Canvas 缩放并按需降低 WebP/JPEG 质量（PNG/GIF 保留透明），上传后在任务行和全局提示里显示压缩说明。
- 图片以认证缩略图网格展示标题、上传时间与尺寸/大小；详情支持大图预览、查看原图、下载、替换图片、编辑标题与备注（备注可清空）、星标和移入回收站。
- 图片详情提供「图片文字识别」区：状态、识别文字（可滚动）、自动标签（点击直接搜索该标签）、来源与更新时间，以及「识别文字/重新识别」按钮；上传后排队中会自动轮询结果，服务端未启用时给出原因。缩略图卡片在识别完成后显示最多 2 个标签。
- 图片条目在首页总览、混合搜索和回收站中显示缩略图并可打开图片详情；图片不进入灵感收件箱，也不提供与其他类型的转换。
- 顶部全局搜索支持 `/` 快捷键、输入防抖、清除和无结果状态。
- 网页资料视图提供独立搜索框（`/` 在该视图聚焦它），搜索时留在当前视图并保留分类与星标筛选，不再跳回「全部」；搜索词变化会重置到第一页并刷新结果计数。
- 混合结果按内容类型展示图标、摘要，并可打开对应编辑界面。
- 支持粘贴网址、填写可选标题和备注、读取资料列表和编辑原链接。
- 网页资料列表展示一个主分类、星标、网页摘要和站点；资料保存后先显示处理状态。
- 支持按自动分类筛选，网页资料重复规范网址自动跳过。
- 支持分类模板管理：创建自定义分类、填写分类说明、设置域名/网址/标题关键词规则，并异步应用到已有资料。
- Web 网页资料列表只按一个主分类和星标筛选，并可按更新时间、创建时间或标题排序。
- 资料库支持列表和卡片两种视图；Web 网页资料不打开右侧栏，分类与星标直接在最近内容列表修改，标题和域名直接打开原网页。
- 支持扩展直接读取当前 Chrome/Edge 书签并自动进入预览；HTML 本地解析作为备用方式，两种来源均支持文件夹追溯、批次进度、失败重试和撤销。
- 书签导入先完成可搜索写入，再由后台补充元数据与分类；服务重启会自动恢复等待中或处理中批次。
- 支持 Chrome Manifest V3 扩展同步当前浏览器各窗口的 HTTP(S) 打开网页和书签树，Web 输入 `@` 可选择任意打开网页，并可直接读取书签；扩展动作仍通过一次性令牌直接捕获当前页。
- Web 登录后通过本地内容脚本把当前 Bearer 凭证同步给扩展，扩展请求按用户保存书签；下载包包含清单、内容脚本、后台脚本和安装说明。
- 扩展不再写死 Web 与 API 端口：内容脚本注入 MemoIsle 页面时登记本页源，页面回答自己的 API 地址（开发环境为 `http://localhost:<Web端口>/api/v1`，由 Vite 代理到后端），生效优先级为显式 `chrome.storage.sync` 配置 > 页面登记 > 内置默认；本地开发端口只接受同源 API 地址，跨源 API 必须显式配置，登记结果存在 `chrome.storage.local` 的 `memoisle_web_context`。连接失败时跳转链接会带上 `memoisle_capture_api`，页面提示里显示扩展实际尝试的地址。
- 扩展在用户明确触发动作时可读取当前页选中文本并作为网页正文保存，最多 10000 字；未选中时仍只保存网址和元数据。
- 扩展提供「收藏图片到 MemoIsle」右键菜单：在任意网页图片上右键即可创建图片条目并上传原图，保存来源网页地址；超过 20 MB/12000 像素/5000 万像素时先用 `createImageBitmap` + `OffscreenCanvas` 压缩（WebP，GIF 只留第一帧）并提示压缩前后大小；`blob:` 临时图片、不支持的格式和取图失败都会给出明确原因。
- 为支持任意站点取图，扩展清单新增 `<all_urls>` 主机权限，仅用于后台读取用户右键点中的那张图片；内容脚本仍只匹配本地 MemoIsle 页面用于凭证桥接，不读取历史、Cookie、表单或未选中的正文。
- 支持网页巡检中心、失效网页角标、状态摘要、人工重试、采用跳转网址、更新网址/资料、单条暂停、站点暂停、账号开关/频率、忽略和删除。
- 支持单词、音标、释义、例句和出处链接的收藏与编辑。
- 快速捕获会根据网址、英语词形和正文给出非强制类型建议；用户可一键切换并继续确认。
- 网页资料可打开预览详情，支持复制链接、归档、移入回收站和转换为单词/灵感；重复网址提供查看已有或仍然保存。
- 单词捕获支持查词预览、逐条选择释义；输入词形后会自动填入中文释义、音标和例句，不覆盖手工填写内容。
- Web 顶栏支持选择 JSON/CSV 文件批量导入单词；完整 MemoIsle 导出会自动跳过非单词条目，重复词形和错误行分别统计。
- 点击单词捕获时自动读取剪贴板词形；Web 与 Android 均提供“从剪贴板填入”，网址、文件路径、文件名和完整句子不会误填。
- 相同词形保存时提示查看、合并例句或仍然保存；保存成功可撤销到回收站。
- 灵感、网页资料和语音灵感保存成功后均提供撤销入口，撤销会移入回收站。
- 单词详情和复习卡片展示最近复习时间、下次复习时间，以及英式/美式发音入口；优先使用词典音频，失败后请求 sanoTTS，再回退系统/浏览器 TTS。
- 回顾页可切换到专用单词复习队列，并显示进度。
- Web 回顾页和 Android 回顾页均可调整账号级复习计划；队列上限与反馈间隔由服务端统一计算。
- 首页展示今日回顾摘要；回顾页混合到期单词、未读资料和待整理灵感，可跳过、复习、打开原网页或整理归档。
- 单词复习默认隐藏答案，显示后可提交三档反馈。
- 支持浏览器麦克风录音、计时、实时输入音量、暂停/继续、取消二次确认、浏览器 SpeechRecognition 实时转写、可编辑配套文字、失败回退和详情播放。
- 支持快速创建文字灵感、读取最近内容、打开详情和编辑。
- HTTP 409 时提示跨设备冲突并重新读取服务端内容。
- 提供桌面侧栏、移动底部导航、加载、空和失败状态。

### Android

- 原生 Jetpack Compose，最低 API 26，目标 API 36。
- 提供邮箱密码登录/注册。微信、Google、Apple 登录暂缓；后端未开启第三方登录时，登录页不展示这些入口。重新启用后通过系统浏览器授权并以 `memoisle://auth/callback` 深链返回。
- 顶栏提供回收站入口：可恢复或永久删除，永久删除前二次确认；详情页可将内容移入回收站。
- 登录令牌保存在私有偏好存储；切换账号或退出登录时清空本机 SQLite 缓存。
- API 客户端统一附加 Bearer 请求头，录音上传同步携带认证凭据。
- 使用 Android SQLite 保存本地灵感，不依赖 Room/KSP。
- Android SQLite 已升级到版本 11，可同时缓存灵感、网页资料与图片元数据、分类名称、资源形态、阅读进度、收藏夹、星标和巡检状态。
- 图片收藏在 Android 为只读浏览加相册上传：资料库新增「图片」筛选，列表显示认证缩略图，详情先显示缩略图、可展开原图，并展示尺寸、大小和 MIME。
- 相册上传的图片超限时先用 `inSampleSize` 降采样再缩放/重编码（PNG 保留透明，其余转 JPEG），保证 ≤ 20 MB；压缩结果通过 Snackbar 提示原大小→新大小、尺寸/格式变化和动图转静态，上传失败时也会说明已压缩。
- 首页快速动作和图片工作区可通过系统相册选择器（`PickVisualMedia`，无需存储权限）创建图片条目并上传，失败会保留本地草稿并在同步时重试上传图片字节。
- Android SQLite 版本 12 缓存图片 OCR 文本、状态、来源、错误与自动标签；图片详情只读展示识别状态、文字、标签和来源/更新时间，OCR 文本与标签纳入本地即时搜索（不提供重试，重试在 Web 端）。
- 图片字节缓存在应用缓存目录，退出登录、切换账号或永久删除时清理。
- 灵感和英语单词支持本地创建/编辑；网页资料仅在系统分享确认时保存，已保存网页资料只读。
- 启动、登录后或手动刷新时重试本地待同步内容，再拉取服务端数据；WorkManager 的周期任务要求联网、非低电量且存储充足，主动同步只要求联网和存储充足，并使用指数退避。
- 注册 `ACTION_SEND` 的 `text/plain` 分享目标，可从浏览器或其他应用接收链接。
- 分享链接后自动打开最小确认表单，并预填原始网址和可识别标题；保存后不提供资料编辑入口。
- Android 分享已收藏网址时会原子移除本地临时行并采用服务端原资料，避免重复和永久待同步状态。
- 支持英语单词本地缓存、离线创建、详情编辑和复习反馈。
- 分享网页遇到重复网址时可查看已有资料或确认仍然另存；网页资料详情支持打开、复制、分享、归档和回收站。
- 单词创建支持查词预览、逐条选择释义，并保留用户手工填写内容。
- Android 本地数据库升级会保留旧版灵感和资料，并补充页面摘要、自动分类、导入来源和健康状态。
- 支持运行时麦克风权限、AAC/M4A 原生录音、实时输入音量、暂停/继续、取消二次确认、本地草稿和失败重试上传。
- 语音灵感详情提供原始录音播放入口。
- 首页今日回顾卡片显示到期单词、待读资料和待整理灵感数量；底部“回顾”入口打开按账号计划限制的混合队列，可跳过、复习、打开原网页或整理归档。
- 底部“资料库”入口可浏览各类本地内容的统一列表，包括图片缩略图。
- 搜索在本地即时完成，覆盖标题、正文、网址、单词字段、转写和标签。
- 网页资料列表与详情展示一个主分类、星标、摘要、站点、原始网址和网页巡检状态，支持打开、复制和分享；Android 端只读并支持显示用户自定义分类名称、最近检查时间。
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

点击 Web 顶栏“下载扩展”，解压 `memoisle-browser-extension-<version>.zip`，然后在
Chrome 或 Edge 的扩展管理页启用开发者模式并选择“加载已解压的扩展”。加载后刷新
MemoIsle 页面并登录，使页面把当前用户凭证同步给扩展。
本地开发也可以直接加载仓库中的 `extension` 目录。

## 4. 已执行验证

| 范围 | 命令/方式 | 结果 |
| --- | --- | --- |
| Python 静态检查 | `ruff check backend` | 通过 |
| 后端测试 | `pytest -q` | 全部通过，覆盖 AgentlyMail 两阶段调用、邮箱验证码、密码重置、登录限流、第三方登录、Bearer 会话、撤销、用户隔离、回收站恢复/永久删除和 30 天清理 |
| Web 类型与生产构建 | `npm run build` | 通过 |
| 优先级 4–6 后端回归 | `python -m pytest -o addopts='' -q` | 421 项通过；覆盖删除通知、混合分页、账号隔离、批量部分成功、本地 OCR、队列续跑、并发修改和重复组 |
| 优先级 4–6 浏览器验收 | 隔离数据库 + Chromium | 通过；237 条列表、273 条回收站、63 条重复组内分页、图片 OCR/模板归类、人工改分类、分类筛选和移动端无横向溢出 |
| 本地 PyTorch OCR 真推理 | 合成英文图片 + 本地中英文权重 | 通过；识别出 `MEMOISLE PYTORCH 2026`，不上传图像 |
| 优先级 4–6 Android | 完整 OpenJDK 25 + `testDebugUnitTest assembleDebug lintDebug` | 通过；新版 APK 已生成，删除通知与附件缓存清理已编译验证，真机跨设备验收仍需安装新版 |
| Android 单元测试 | `JAVA_HOME=<JDK17> ./gradlew testDebugUnitTest` | 通过 |
| Android APK | `JAVA_HOME=<JDK17> ./gradlew assembleDebug` | 通过 |
| Android lint | `JAVA_HOME=<JDK17> ./gradlew lintDebug` | 通过 |
| Android STT 资源 | SenseVoiceSmall INT8 按需下载 | 通过；Release APK 不包含 229 MB 权重，首次使用下载后校验 SHA-256，Debug 可选内置模型 |
| Web STT/TTS | `npm run build` | 通过，浏览器转写与服务端语音播放代码通过 TypeScript/Vite 构建 |
| TTS 接口契约 | `pytest -q` | 通过，覆盖 WAV 响应和 sanoTTS 未安装时的 503 回退 |
| API 真实联调 | health → create → list → update | 200/201，版本 1 → 2 |
| Android 系统分享 | `ACTION_SEND` → 资料表单 → 保存 → API | 201，列表显示“已同步” |
| 单词真实联调 | Android 创建 → 显示答案 → “记得” | 版本 1 → 2，熟悉度 0 → 1 |
| 语音真实联调 | Android 录音 → 创建灵感 → 上传 → 下载 | 243,944 字节有效 MP4 |
| 搜索 API 联调 | `GET /memos?q=...` → 跨类型结果 | 通过 |
| Chrome 扩展静态检查 | `node --check extension/background.js`、`node --check extension/content.js`、Manifest JSON 校验 | 通过 |
| Chrome 扩展下载 | Web 按钮 → 下载 ZIP → 校验运行文件和 Manifest V3 权限 | 通过（接口测试） |
| Chrome 扩展行为测试 | `cd extension && npm test` | 54 项测试通过，覆盖书签直读权限与快照、登录凭证桥接、打开网页快照、标签页变化、协议/地址拦截、失败回退、配置地址、Web/API 地址学习与信任边界，以及右键收藏图片、超大图压缩提示、格式/地址拒绝和未登录引导 |
| 右键收藏图片 | `npm test` 图片用例 | 通过（模拟 `createImageBitmap`/`OffscreenCanvas`）；真实跨域取图与右键菜单需在 Chrome 开发者模式加载后手动验收 |
| Chrome Web 捕获 | 当前浏览器多个打开网页快照 → Web `@网页` 选择 → 附件标题/网址渲染；当前页动作仍支持一次性凭据 | 自动化通过；需在现有 Chrome 加载扩展后手动验收 |
| 书签导入接口 | 预览 → 去重 → 导入 → 搜索 → 重试 → 撤销 | 通过（测试覆盖） |
| 书签任务恢复 | `processing` 项重置 → 服务重启恢复 → 批次完成 | 通过（测试覆盖） |
| 网页巡检接口 | 失败阈值 → 变化/跳转 → 处理动作 → 调度限流 → 账号/站点暂停与频率 | 通过（测试覆盖） |
| Android URL 去重 | 分享服务端已有网址 → 保存 → 本地 SQLite 核对 | 1 行且 `SYNCED` |
| Android 资料只读字段 | 服务端同步分类、星标与巡检状态 → 资料详情 | 显示分类、星标、巡检状态和最近检查时间，无编辑表单 |
| 今日回顾接口 | 混合队列 → 跳过 → 类型筛选 → 整理灵感后移出 | 通过（测试覆盖） |
| 今日回顾客户端 | Web 构建、Android 单元测试 | Web `npm run build` 通过；Android 单元测试通过 |
| 会议总结接口 | `pytest -q backend/tests/test_meeting_service.py` | 通过（测试覆盖） |
| 会议转写备份 | JSON/CSV/Markdown 导出与 JSON 导入测试 | 通过（测试覆盖） |
| 云盘绑定 | `pytest -q backend/tests/test_cloud_accounts.py` | 8 项通过；覆盖凭据加密往返、脱敏提示、重复绑定、凭据被服务商拒绝、列表与解绑、API 校验 |
| 电子书任务 | `pytest -q backend/tests/test_ebook_service.py` | 11 项通过；覆盖链接判定、格式识别、云盘转存、直链下载上传与临时文件清理、超限拦截、云盘失败落库、重试状态机（排队中/执行中/已完成都拒绝重复派发）、进程退出后残留任务退回排队、用户隔离 |
| 电子书接口 | `pytest -q backend/tests/test_ebook_api.py` | 5 项通过；覆盖未绑定云盘拒绝、提交/列表/查询/重试、分享链接判定、非法协议拒绝，以及任务跑通后资料接口返回云盘引用与快照（含 `link_next_check_at` 为空） |
| 阿里云盘客户端 | `pytest -q backend/tests/test_aliyun_client.py` | 12 项通过；覆盖凭据解析与校验、默认云盘识别、目录复用与创建、分片上传与秒传跳过、分享转存、错误映射、网络异常兜底 |
| 电子书全链路衔接 | `pytest -q backend/tests/test_ebook_pipeline.py` | 4 项通过；注入**真实** AliyunDriveClient（仅替换底层 HTTP），验证分享转存与直链上传两条链路、目录复用不重复创建、快照字段落库、凭据失效时任务落库为失败而非抛异常，以及电子书不被网页元数据抓取/链接巡检的挑选条件命中但完成规则分类 |
| 百度网盘客户端 | `pytest -q backend/tests/test_baidu_client.py` | 9 项通过；覆盖凭据解析、缺 BDUSS 拒绝、昵称与 bdstoken 获取、errno 映射、目录复用与创建、提取码校验后的分享转存、以及上传缺 access_token 的明确报错与 precreate→分片→create 时序 |
| Web 云盘与电子书界面 | `npm run build` | 通过；云盘绑定与电子书收藏对话框随主包构建 |
| 图片接口 | `pytest -q backend/tests/test_images.py` | 通过，覆盖空正文创建、上传/替换、缩略图、真实格式校验、统计、搜索、导出和永久删除清理 |
| 图片备份迁移 | `pytest -q backend/tests/test_import.py` | 通过，图片条目只恢复标题备注与元数据，二进制需重新上传 |
| 图片 OCR 与自动标签 | `pytest -q backend/tests/test_image_ocr.py` | 通过，22 项覆盖模型响应解析、本地关键词、渠道选择与回退、后台识别、搜索命中、手动重试与未启用状态 |
| Web 图片 OCR 展示 | `npm run build` | 通过（tsc --noEmit + Vite 生产构建） |
| Android 图片 OCR 字段与搜索 | `./gradlew --rerun-tasks testDebugUnitTest assembleDebug lintDebug` | 通过；`MemoTest` 37 项含 OCR 搜索与标签用例，lint 0 error |
| Web 图片工作区 | `npm run build` | 通过（`tsc --noEmit` + Vite 生产构建） |
| Android 图片字段与工具 | `./gradlew testDebugUnitTest` | 通过，`MemoTest` 25 项含图片 MIME/标题/尺寸/搜索用例 |
| Android 图片构建 | `./gradlew assembleDebug` | 通过（需可写的 `ANDROID_USER_HOME` 生成 debug keystore） |
| 图片压缩策略（Web） | `npm run build` + Node 运行超限判定/文案 | 通过：20 MB / 12000 px / 5000 万像素边界判定与提示文案符合预期 |
| 图片压缩（Android） | `./gradlew testDebugUnitTest` | 通过，`MemoTest` 覆盖压缩策略判定、目标尺寸与提醒文案 |

## 5. 当前边界

- 网页资料核心 P0 已完成代码、接口和 Web/Android 运行时验收；扩展已覆盖当前浏览器打开网页快照、当前页一次性捕获、用户选中文本摘录，以及任意页面图片右键收藏。地址学习已通过自动化测试和真实链路检查（Web 5174 + 后端 8011：右键收藏按登记地址请求 `/api/v1/memos` 并跳转回 5174）；扩展的图标/快捷键和图片右键菜单属于浏览器安装态入口，仍需在现有 Chrome 的开发者模式下手动加载 v0.4.1 后点击确认。
- 扩展新增 `<all_urls>` 主机权限以支持任意站点取图；生产发布前需在商店说明中解释该权限只用于用户主动右键收藏的那张图片，且本地 `file://` 图片需要用户额外开启「允许访问文件网址」。
- 生产部署时需将扩展清单中的本地 API 主机权限和内容脚本 Web 匹配地址替换为正式 API/Web 域名。
- 微信、Google、Apple 登录已按产品决定暂缓：OAuth 代码保留，但默认关闭，Web 与 Android 登录页不展示入口。
- 邮箱验证码、密码找回和登录频率限制已实现；生产环境还需配置 AgentlyMail CLI 或正式 SMTP，并完成真实邮件验收。
- Android 认证代码已通过单元测试、APK 构建和 lint。
- 开发环境默认 SQLite，生产环境迁移 PostgreSQL 时需要补数据库迁移脚本。
- Web 按账号将新建表单和未提交编辑保存到本地草稿；恢复旧版本草稿时仍通过服务端版本检查处理冲突，浏览器不支持本地存储时自动降级为在线编辑。
- Web 网页资料已收敛为“一个分类 + 星标”的组织模型；旧的资源形态、阅读进度、标签、收藏夹和状态字段仅保留接口与历史数据兼容，不再出现在 Web/Android 资料界面；Web 在巡检中心处理，Android 在资料详情只读展示巡检状态。
- Android 已加入 WorkManager 后台同步，并按周期/主动同步区分联网、低电量和存储约束；实际设备的电量和网络策略仍需验收。
- Android 退出前检查待同步内容；编辑冲突会保留本地草稿并暂停后台覆盖，可选择保留本地修改或采用服务端版本。
- Android 顶栏支持通过系统文件选择器保存当前账号 JSON 数据副本，导出网络流直接写入用户选择的文件。
- Web 遇到 409 编辑冲突时保留当前编辑内容，提供保留本地修改或采用服务端版本的选择。
- Web 顶栏支持选择 JSON、CSV 或 Markdown 下载当前账号数据副本，也支持导入 JSON/CSV 单词；导出包含保留期内的回收站条目，不缓存访问令牌和录音二进制。
- Android 已接入 sherpa-onnx SenseVoiceSmall INT8 设备端 STT；Release 首次使用时按需下载官方固定版本，下载包和解压文件均校验后原子安装，缺少模型或网络失败时仍可保存原始录音并手工填写。
- Web STT 依赖浏览器 SpeechRecognition，仅在浏览器支持且允许识别服务时自动转写；不可用时不阻塞录音保存。浏览器语音识别可能由浏览器服务处理，隐私提示已在界面展示。
- Web 录音支持 MediaRecorder 暂停/继续、AudioContext 输入音量反馈和取消二次确认；暂停时长不会计入最终录音时长，取消会释放麦克风并丢弃临时 Blob。
- Android 录音支持 MediaRecorder 暂停/继续、maxAmplitude 输入音量反馈和取消二次确认；有效时长由录音器扣除暂停区间。
- 服务端 TTS 通过可选 `sanotts` 生成 WAV；未安装或合成失败时 Web/Android 回退到词典音频与系统/浏览器 TTS。生产发布需审查 sanoTTS GPL-3.0-or-later 及音色包许可。
- 常见复数、进行时、过去式、比较级和不规则词形已做保守归并；尚未覆盖完整的词性识别与词形变化分析。
- Web 录音依赖浏览器 `MediaRecorder`；不支持时会回退并提示使用文字或 Android。
- 开发环境音频保存在本机 `data/audio`，生产环境需迁移到私有对象存储。
- 图片收藏当前每条只保存一张图片，格式限 PNG/JPEG/WebP/GIF、20 MB、单边 12000 像素；开发环境原图与缩略图保存在本机 `data/images`，生产环境需迁移到私有对象存储，并补充压缩、同哈希去重和配额策略。
- 图片二进制不随 JSON/CSV/Markdown 导出迁移，导入只恢复标题、备注、图片元数据与已识别的 OCR 文本/标签；图片与其他条目类型之间暂不支持转换。
- 图片 OCR 默认关闭，需部署方设置 `MEMOISLE_IMAGE_OCR_PROVIDER`；选择 `llm`/`auto` 时会回退到视觉模型并把图片发送到所配置的服务，生产前需确认数据区域与合规要求。本地引擎需要自行安装依赖，缺失时条目记录为 `disabled`/`failed` 而不影响图片保存。
- 自动标签中的本地关键词是启发式规则（英文词频、中文 4 字窗口），与语义标签合并后可能包含不够精确的词；按账号的 OCR 开关、已有图片批量补识别和表格/手写增强尚未实现（见待办 P1-13/P1-14）。
- Web / Android 的 OCR 展示与重试已通过构建和单元测试，浏览器轮询、对话框轮询与真机渲染仍需人工验收。
- Android 的图片 UI 已通过编译、单元测试和接口契约验证；相册选择器、缩略图排版和真机图片加载仍需在 Android 模拟器/真机上人工验收。
- 电子书收藏的**云盘协议层已按阿里云盘官方 OpenAPI 实现**：凭据校验与默认云盘识别、逐级建目录、分享链接换令牌后转存、分片上传（含秒传 `rapid_upload` 跳过）、文件元数据读取，并统一映射凭据失效/分享失效/空间不足/限流四类错误。使用前需要在阿里云盘开放平台注册应用，并在设置页粘贴 `refresh_token` + `client_id` + `client_secret`（或尚未过期的 `access_token`）。
- **网页 cookie 直调（非官方接口）尚未实现**：网页端需要 `x-signature` 签名头，算法必须按真实抓包确认，当前遇到只含 cookie 的凭据会给出明确提示而不是静默失败。
- 百度网盘客户端走浏览器登录态（BDUSS/STOKEN cookie）：凭据校验与昵称、`bdstoken` 获取、逐级建目录、列表、元数据、分享转存（含提取码校验与分享页解析）均已实现。**上传需要开放平台应用的 `access_token`**：PCS `superfile2` 只给 cookie 会被百度拒绝，因此缺少 `access_token` 时上传会给出明确错误，而目录与转存不受影响。
- 两个服务商都是非官方或半官方接入：平台策略变更、风控或接口调整都可能导致失败，需要用户重新粘贴登录态；生产环境必须显式设置 `MEMOISLE_CLOUD_CREDENTIAL_SECRET`，否则进程重启后旧凭据无法解密。
- 云盘凭据来自浏览器登录态，属于非官方接口：平台策略变更或触发风控时可能失效，失败后需要用户重新粘贴；生产环境必须显式设置 `MEMOISLE_CLOUD_CREDENTIAL_SECRET`，否则进程重启后旧凭据无法解密。
- 电子书直链下载与上传在后台任务线程内同步执行，尚未引入独立队列、并发上限与带宽限速；超大文件可能长时间占用工作线程。
- 本里程碑没有上传数据集、临床图像、密码或 API 密钥。

## 6. 下一里程碑建议

未完成项以 [待办清单](backlog.md) 为准。下一步是完成真实设备的模型下载、录音转写和 TTS 联调，并在 Android 真机上完成图片收藏的交互验收。微信、Google、Apple 登录暂缓。
