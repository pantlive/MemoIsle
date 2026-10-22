# MemoIsle API

## 本地运行

在仓库根目录创建并进入 conda 环境：

```bash
conda env create -f environment.yml
conda activate memoisle
uvicorn app.main:app --app-dir backend --reload
```

默认使用 `data/memoisle.db` SQLite 数据库，API 地址为
`http://127.0.0.1:8000/api/v1`，交互文档位于
`http://127.0.0.1:8000/docs`。

可通过环境变量覆盖：

- `MEMOISLE_DATABASE_URL`：SQLAlchemy 数据库连接地址。
- `MEMOISLE_CORS_ORIGINS`：逗号分隔的 Web 来源。
- `MEMOISLE_AUTH_DEV_MODE`：设为 `true` 时开放本地开发登录；生产环境必须保持关闭。
- `MEMOISLE_AUTH_TOKEN_SECRET`：登录 state 与 Bearer 会话签名密钥。未设置时自动生成并保存到数据库旁的 `.memoisle-auth.key`（权限 0600），重启后沿用；多机部署或数据库不在本地磁盘时必须显式配置同一个值。
- `MEMOISLE_OAUTH_LOGIN_ENABLED`：设为 `true` 时才开放微信、Google、Apple 登录；当前产品范围默认关闭。
- `MEMOISLE_GOOGLE_CLIENT_ID` / `MEMOISLE_GOOGLE_CLIENT_SECRET`：Google OAuth 客户端凭据。
- `MEMOISLE_WECHAT_APP_ID` / `MEMOISLE_WECHAT_APP_SECRET`：微信开放平台网站应用凭据。
- `MEMOISLE_APPLE_CLIENT_ID` / `MEMOISLE_APPLE_CLIENT_SECRET`：Apple Services ID 与预生成的 client secret。
- `MEMOISLE_AUTH_MOBILE_REDIRECT_URI`：Android 登录回跳地址，默认 `memoisle://auth/callback`。
- `MEMOISLE_LOCAL_USER_ID`：本地开发登录使用的用户标识。
- `MEMOISLE_WEB_BASE_URL`：邮箱验证和密码重置链接使用的 Web 地址。
- `MEMOISLE_AUTH_LOGIN_RATE_LIMIT_ATTEMPTS`：登录失败限流阈值，默认 5 次。
- `MEMOISLE_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS`：登录失败限流窗口，默认 900 秒。
- `MEMOISLE_SMTP_HOST` / `MEMOISLE_SMTP_PORT`：SMTP 服务器与端口。
- `MEMOISLE_SMTP_USERNAME` / `MEMOISLE_SMTP_PASSWORD`：SMTP 认证信息。
- `MEMOISLE_SMTP_FROM_ADDRESS`：认证邮件发件人地址；为空时使用 SMTP 用户名。
- `MEMOISLE_SMTP_USE_TLS` / `MEMOISLE_SMTP_USE_SSL`：SMTP 加密方式。
- `MEMOISLE_SMTP_TIMEOUT_SECONDS`：SMTP 建连和发送超时时间，默认 15 秒。
- `MEMOISLE_EMAIL_PROVIDER`：邮件渠道，支持 `auto`、`agently`、`smtp`、`outbox`；默认 `auto`。生产环境优先使用可执行的 `agently-cli`，再回退 SMTP。`MEMOISLE_AUTH_DEV_MODE=true` 且渠道为 `auto`/`outbox` 时写入本地收件箱，不会因为本机有 `agently-cli` 而改走 Agently。
- `MEMOISLE_AGENTLY_CLI_PATH`：`agently-cli` 可执行文件路径，默认从 `PATH` 查找。
- `MEMOISLE_AUTH_VERIFICATION_CODE_EXPIRE_MINUTES`：注册验证码有效分钟数，默认 10。
- `MEMOISLE_AUTH_VERIFICATION_CODE_RESEND_SECONDS`：同一邮箱的重发间隔，默认 60 秒。
- `MEMOISLE_AUTH_VERIFICATION_CODE_MAX_ATTEMPTS`：验证码最大错误次数，默认 5 次。
- `MEMOISLE_EMAIL_OUTBOX_DIRECTORY`：开发模式下未配置 SMTP 时保存 `.eml` 的目录。
- `MEMOISLE_AUDIO_DIRECTORY`：原始录音的本地开发存储目录。
- `MEMOISLE_IMAGE_DIRECTORY`：图片收藏原图与缩略图的本地开发存储目录，默认 `data/images`。
- `MEMOISLE_LLM_BASE_URL`：OpenAI 兼容接口地址（例如 DeepSeek 的 `https://api.deepseek.com/v1`）；用于会议总结。
- `MEMOISLE_LLM_API_KEY`：OpenAI 兼容接口密钥；本地无需鉴权的模型服务可留空。
- `MEMOISLE_LLM_MODEL`：会议总结使用的模型名称，例如 `deepseek-chat`。
- `MEMOISLE_LLM_TIMEOUT_SECONDS`：会议总结请求超时秒数，默认 30。
- `MEMOISLE_DEEPSEEK_API_KEY` / `DEEPSEEK_API_KEY`：分类模板生成的服务器默认 DeepSeek 凭证；也可在 Web 设置里按账号保存，优先使用账号凭据。
- `MEMOISLE_DEEPSEEK_BASE_URL`：分类生成接口地址，默认 `https://api.deepseek.com/v1`。
- `MEMOISLE_DEEPSEEK_MODEL`：分类生成模型，默认 `deepseek-flash`，支持覆盖为部署中可用的 DeepSeek 模型。
- `MEMOISLE_DEEPSEEK_TIMEOUT_SECONDS`：分类生成请求超时秒数，默认 30。
- `MEMOISLE_JEV_API_KEY` / `TYPESAFE_API_KEY`：Jev 网页归类的服务器默认凭证；也可在 Web 设置中配置。
- `MEMOISLE_JEV_BASE_URL` / `MEMOISLE_JEV_MODEL`：默认 `https://api.typesafe.ai/v1` 和 `jev-1.13.0`。
- `MEMOISLE_JEV_MIN_CONFIDENCE`：Jev 自动归类的最低置信度，默认 0.7；应使用实际收藏样本评估后调整。
- `MEMOISLE_IMAGE_OCR_PROVIDER`：图片 OCR 渠道，支持 `none`、`local`、`llm`、`auto`；默认 `none`（关闭）。`local` 只用本地引擎，`llm` 只用视觉大模型，`auto` 本地优先、不可用时回退视觉大模型。
- `MEMOISLE_VISION_MODEL`（或 `MEMOISLE_IMAGE_OCR_MODEL`）：图片 OCR 使用的视觉模型名称；未设置时回退 `MEMOISLE_LLM_MODEL`。复用 `MEMOISLE_LLM_BASE_URL` 与 `MEMOISLE_LLM_API_KEY`。
- `MEMOISLE_IMAGE_OCR_TIMEOUT_SECONDS`：视觉模型请求超时秒数，默认 60。
- `MEMOISLE_IMAGE_OCR_MAX_TAGS`：单张图片自动标签上限，默认 8，范围 1–20。
- `MEMOISLE_IMAGE_OCR_PREVIEW_MAX_SIDE`：发给视觉模型的 JPEG 预览图最大边，默认 1600，范围 320–4096。
- `MEMOISLE_IMAGE_OCR_LANGUAGES`：本地 pytesseract 语言包，默认 `chi_sim+eng`。
- `MEMOISLE_TTS_PROVIDER`：服务端语音合成渠道，支持 `auto`、`sanotts`、`none`；默认 `auto`。
- `MEMOISLE_TTS_ENABLED`：是否开启服务端 TTS，默认开启；未安装 `sanotts` 时客户端自动回退。
- `MEMOISLE_SANOTTS_VOICE`：默认 sanoTTS 音色，默认 `amy`。首次合成会按 sanoTTS 规则缓存音色包。
- `MEMOISLE_SANOTTS_CACHE_DIRECTORY`：sanoTTS 音色和 WAV 缓存目录，默认 `data/sanotts`。
- `MEMOISLE_TTS_MAX_TEXT_LENGTH`：单次合成最大字符数，默认 2000。
- `MEMOISLE_WORD_DICTIONARY_BASE_URL`：英英词典 API 地址，默认使用 Free Dictionary API；在中文释义缺失时作为回退。
- `MEMOISLE_WORD_BILINGUAL_ENABLED`：是否查询中英词典，默认开启。
- `MEMOISLE_WORD_BILINGUAL_DICTIONARY_URL`：中英词典地址，默认使用有道公开查词接口。
- `MEMOISLE_WORD_DICTIONARY_TIMEOUT_SECONDS`：词典请求超时秒数，默认 6 秒。
- `MEMOISLE_WORD_DICTIONARY_TRUST_ENV`：是否继承 `HTTP(S)_PROXY` 等环境代理，默认 `false`；只有网络必须经代理时才设为 `true`。
- `MEMOISLE_TRASH_RETENTION_DAYS`：回收站保留天数，默认 30；到期后读取回收站或后台巡检时永久删除。

## 回收站

回收站支持 `POST /api/v1/memos/trash/restore` 一键还原和 `DELETE /api/v1/memos/trash` 一键清空。接口仅处理当前登录账号的全部回收站条目，返回 `restored_count` 或 `deleted_count`。还原保留原有状态、收藏内容和附件，并更新版本及同步时间；超过保留期限的条目按现有规则清理。清空永久删除条目及其录音、原图和缩略图。

单条永久删除、一键清空及保留期清理均会在同一数据库事务保存最小删除通知
（条目标识、客户端标识、时间，不含收藏内容）。`GET /api/v1/sync/changes`
新增 `deleted_items` 与 `has_more`；更新与删除共享 `cursor` / `cursor_id` 和分页额度。
即使页面只有删除通知，也须依照 `has_more` 继续读取。旧客户端标识重建已删除条目
返回 410，避免离线设备把旧收藏重新上传。通知持久化且按账号隔离。

`POST /api/v1/memos/batch` 支持 `trash`、`restore`、`permanent`，仅处理
`items: [{memo_id, expected_version}]` 中明确选择的 1–100 条记录。
返回逐项 `updated` / `skipped` 及安全的冲突原因，部分冲突不阻断其他选项。
删除和还原按版本及状态核对，永久删除提交成功后才清理附件。

## 图片批量整理

「图片收藏 → 图片批量整理」可以识别全库未处理图片或当前页选中的图片，
也可以将本地识别文字交给 Jev 按现有系统和自定义模板分类。
本批量入口固定使用本地 PyTorch EasyOCR，不受旧单图 OCR 的云端回退配置影响；
Jev 只接收识别文字和标题，不接收图片字节、路径或用户备注。
已成功或未确定的判断、人工分类和人工确认均跳过；低置信度和无文字保留原分类，
可在图片详情手动选择模板。任务固定记录版本和图片哈希，结果不会覆盖人工修改。

先在 conda 环境安装 `environment.yml` 的依赖，然后准备权重：

```bash
conda run -n memoisle python backend/scripts/prepare_local_ocr.py --models /absolute/data/ocr-models
```

`--models` 应指向 `MEMOISLE_IMAGE_DIRECTORY` 的父目录下 `ocr-models`。
准备脚本只下载模型；识别时禁用权重下载。推理复用阅读器、限制预览尺寸，
自动选择可用设备，并在 `torch.inference_mode()` 内执行。
模型未准备或服务异常时安全暂停，点击「继续图片任务」从当前项继续；
识别结果已保存时不重复 OCR。重启会恢复已有批次，不会自行创建图片任务。

- `GET /api/v1/images/organization`：全库待处理数、重复组数和队列进度。
- `POST /api/v1/images/organization`：`action` 为 `ocr` / `classify` / `ocr_classify`；
  `scope=all` 固定全库未处理快照，`scope=selected` 使用上述选择项，最多 100 条。
- `POST /api/v1/images/organization/resume`：继续暂停任务。
- `GET /api/v1/images/duplicates`：精确文件哈希重复组分页，默认每页 10 组。
- `GET /api/v1/images/duplicates/{hash}`：大重复组内分页，默认每页 50 条。

重复识别仅比较完整文件哈希；外观相似或重新编码后的文件不视为精确重复。
所有查询按账号隔离，排除回收站。用户选择需整理的记录后移入回收站，可还原，
不会自动删除重复文件。

## DeepSeek 生成分类模板与 Jev 网页归类

在 Web 侧栏「设置 → 模型服务」（手机为顶栏「设置」）填写 DeepSeek、Jev 的 API Key 和模型名称。凭据按账号加密保存，接口只返回末尾四位掩码；密钥留空保留原有值，保存后下一次请求和后台归类立即生效，无需重启。可以先「测试连接」再保存；测试只发送固定短文本，不读取收藏，可能产生少量模型调用费用。取消启用并保存可停用该服务；「移除账号配置」删除账号凭据及模型设置，恢复服务器默认配置。

「请求地址（可选）」支持按账号保存中转地址，留空使用服务器默认地址。可填基础地址（例如 `https://relay.example/v1`），也可粘贴完整 `/chat/completions` 或 `/systemone` 地址，系统会归一化并补充对应接口端点。模型名称使用中转平台提供的 ID；DeepSeek 通道要求 Chat Completions、JSON 输出及当前请求参数兼容，Jev 通道要求 TypeSafe 的 System One/Choice 协议。地址不接受内嵌账号密码、查询参数或片段；更换服务域名、协议或端口时须填写对应 API Key，避免把已有或服务器默认密钥发送到其他服务。省略 API 请求中的 `base_url` 字段保留已保存地址，显式传 `null` 或空白字符串恢复默认地址。已有 SQLite 配置表会自动补充可空地址列，原有密钥与模型设置保持有效。

凭据的加密密钥默认自动生成到 SQLite 数据库旁的 `.memoisle-model.key`（其他数据库使用音频存储目录的父目录），文件权限为 `0600`，重启时重复使用；可用 `MEMOISLE_MODEL_CREDENTIAL_KEY_FILE` 指定位置。备份或迁移时需一并保留该文件，丢失后须重新填写 API Key。收藏数据导出不包含模型配置或凭据。

Web「网页资料 → 智能生成分类」会先让用户确认当前顶级分类是否够用，再读取网页标题、站点和公开摘要做聚类。`mode=subcategories` 只生成细类，`mode=top_level` 只补顶级分类。建议中的名称、说明和父分类均可修改，点击「加入模板」后使用现有创建接口保存。生成接口 `POST /api/v1/resource-categories/generate` 接受可选 `instructions`、`max_categories`（1–12，默认 12）和 `mode`，返回建议而不改写目录；没有整理要求时必须已有网页收藏。解析器兼容分组 JSON、嵌套 `data`/`result`、分析文字夹带的 JSON，以及 `title`/`parentCode`。遇到无法解析的正文会用紧凑 JSON 提示再请求一次；仍无法解析时返回空建议，空正文仍视为生成失败。

DeepSeek 接收本次整理要求、当前用户的分类定义，以及最多 80 条网页样本（按已有大类交错抽取，不含确认失效的网页）。样本含标题、站点、域名、已有分类和公开摘要，不读取收藏备注或图片。聚类请求开启思考模式最高档：`thinking.type=enabled`、`reasoning_effort=max`，`max_tokens` 16384，等待上限 300 秒。输出经过字段、同层级重名、父分类归属和三层深度校验。模型漏了 `parent_code` 时会按大类名或网页已有分类补上；解析失败或超时时按网页用途给出细类，不用网站名或域名当标签。接口采用 [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)；默认模型按官方示例使用 `deepseek-flash`。

加入模板后的新网页由 Jev 的 Choice 从已有类别中选择；手工分类和用户规则保持优先。Jev 请求失败、返回未知类别或置信度不足时回退现有规则。分类请求及 Jev 连接测试等待上限为 30 秒，兼容响应较慢的中转服务。未配置 Jev 时沿用原网页分类流程。图片批量整理使用上文的本地 OCR 与文本模板分类。单次 Jev Choice 最多支持 255 个分类，详见 [官方 Choice 文档](https://docs.typesafe.ai/primitives/choice)。

「网页资料 → 大模型分类已有网页」可启动历史网页的后台分类。按当前账号的启用模板及 Jev 设置处理全部未完成网页，使用保存的 URL、标题、描述、站点信息及可用的公开正文摘要，不发送收藏备注或图片。规则和兜底分类仍会进入模型队列；已成功完成 Jev/LLM 分类、手工分类和明确用户规则会跳过，回收站和云盘电子书不参与。处理进度和 `resource_ai_classified_at` 与分类结果一起持久化；重复启动返回当前任务，关闭页面不影响后台，服务退出后可继续剩余任务。旧库升级会补记已有 Jev/LLM 分类的完成时间。更换网页 URL 会清除完成标记。

分类优先使用公开网页的 `<main>` / `<article>` 文本，排除脚本、导航、页脚、表单和隐藏区域；摘要上限为 3000 字符，抓取沿用原有地址与重定向校验、响应大小和超时限制，不使用登录态。新网页抓取时缓存摘要；旧网页仅在尚未完成模型分类且缺少摘要缓存时补充一次，服务重试复用缓存，没有正文时继续使用元数据。关闭 `MEMOISLE_RESOURCE_ENRICHMENT_ENABLED` 时不额外抓取。补充时发现抓取失败、跳转或元数据变化会转入巡检待人工确认，仍用已有标题和描述完成分类，不主动采用新网址或内容。确认失效的网页跳过模型。

Jev 模板包含完整分类路径，区分不同父分类下的同名子类别。每次有效判断保存 `resource_ai_assessment`：置信度、当时的阈值、对话模型列出的全部成立标签（`proposed_categories`）、最多三个带概率的白名单候选、固定的接受或未确定原因、模型与时间，以及当次公开正文摘要快照。Jev 定案后仍保留对话模型列出的标签。置信度与候选概率分别显示；缺少概率时不推算，未知类别、无效响应和低置信度均不能覆盖原分类，阈值仍默认 0.7。Web 网页列表和详情展示「大模型列出的标签」或自动标签，分类依据里可查看完整列表。以后刷新正文不会修改旧判断快照；换网址、切换类型或人工归类会清除不再适用的依据。旧记录不伪造历史候选，完成标记与进度保持原值，剩余网页在下次处理时使用新流程。

确认失效的网页不进入模型分类，其余巡检状态（跳转、内容变化、需要登录、暂时失败、已忽略、尚未检查）仍会分类，不受巡检列表单次展示 200 条的限制。巡检中心出现异常时仍设置 `resource_ai_review_required`；后台巡检恢复正常仍保留该标记，并继续显示「已恢复，待人工确认」。自动分类也会处理这些网页。分类进度单独显示确认失效数量，巡检入口显示全部待处理总数。

新收藏与新导入网页持久化 `resource_ai_auto_pending`。确认失效以外的网页会由后台主动发现并创建自动分类任务，不需要用户再次点击；书签批次先抓取元数据，再由独立队列分类。书签导入的网页在配置 Jev 时先复核原文件夹：去掉「书签栏」「其他书签」等浏览器根目录后，Jev 只看文件夹路径把它对应到一个已有分类（每个文件夹只判断一次，按分类模板指纹缓存在 `bookmark_folder_category`，模板改动后重新判断）；再结合网页内容和原文件夹，在“该分类 / 不属于”之间判断。认可且达到 Jev 置信度要求就沿用该分类，不再请对话模型列标签；文件夹没有对应分类或判定不符时照常完整分类。结果写入 `resource_ai_assessment.bookmark_folder`（`kept` / `rejected` / `unmapped`，并记录 Jev 的置信度、原归类是文件夹还是标签、对应关系来自 Jev 还是手动指定）。Firefox 书签的 `TAGS` 随导入保存为条目标签和 `resource_import_tags`；文件夹没有对应分类时，再依次看最多三个标签。用户可在 `bookmark_folder_override` 里手动指定或取消某个文件夹 / 标签的对应分类，优先于 Jev，指定的分类停用后自动改回 Jev 的结果。Jev 判定不属于某分类、完整分类却又选回该分类时，记为 `folder_conflict`，保留原分类并进入分类确认中心。用户规则仍优先于原归类；单条网页刷新元数据时同样先复核原归类。任务执行期间的新导入会在当前任务结束后自动接续。成功或低置信度尝试会消耗这次自动排队标记，避免无限反复请求；尚未人工确认的低置信度条目可在本轮结束后另开一轮处理。已完成分类的网页在元数据刷新时也不重复调用模型。

「分类确认中心」使用独立的 `resource_ai_confirmation_pending` 队列，支持完整分页和按标题/网址/描述、未确定原因、首选候选、最高置信度筛选。`GET /api/v1/resource-classification/review` 返回当前账号的总数、分页条目、版本与候选可用性；`POST /api/v1/resource-classification/review/confirm` 接受 `action=adopt|keep|assign`、1–100 条 `items[{memo_id, expected_version, candidate_code?}]`，指定分类时另带 `category_code`。只更新明确选择且版本一致的可复核网页，冲突、确认失效、候选删除或停用等情况逐项返回安全的跳过原因，其他有效选择照常保存，不抓取网页或调用模型。`POST /api/v1/resource-classification/review/retry` 把当前待确认网页重新排队给大模型和 Jev，保留原分类直到有新结果，不把其余未处理网页一并纳入；已有任务正在运行时返回 409。暂停任务会被新的待确认队列替换，避免「继续任务」跳过已经失败过的条目。没有待确认网页时不会覆盖可继续的暂停任务。

采纳候选和指定分类记作手动分类；保留原分类不改原类别、来源、置信度和标签。三种操作均保存独立的 `resource_ai_confirmation` 凭据并停止自动/批量模型处理，原模型依据仍可查看，不把人工操作计为模型成功。更换网址、切换类型或直接改分类会清除旧确认。旧库升级仅把此前已尝试且仍可处理的未确定条目补入复核队列，不伪造候选、清除完成时间或修改任务进度；没有候选的历史网页可指定分类或保留原分类。确认失效的网页不进入分类确认。

超时、连接失败、HTTP 408/429/500/502/503/504 只对当前网页最多自动重试两次，分别等待至少 5 秒、15 秒；服务端 `Retry-After` 指定更长等待时遵守该时间，超过五分钟则暂停并提示稍后继续。认证、额度不足、无效模型或请求配置立即暂停并显示相应原因，不展示原始响应或凭据。等待时间和重试次数存入数据库，重启或重复点击不会跳过等待；等待期间释放租约，不阻塞其他账号。耗尽重试后停止当前账号的自动请求，保留队列和全部进度。

`GET /api/v1/resource-classification` 返回本人待处理、已完成、保留数量和最近任务进度，任务包含 `error_code`、`retry_count`、`retry_limit`、`next_retry_at`；`POST /api/v1/resource-classification` 返回 202 并排队剩余网页。`POST /api/v1/resource-classification/classified/retry` 把当前可处理的已完成模型分类重新排队，保留原分类直到有新结果；人工确认、用户规则和确认失效的网页不纳入。`GET /api/v1/resource-classification/folders` 列出每个文件夹和标签对应的分类与涉及网页数；`POST /api/v1/resource-classification/folders/map?limit=5` 每次让 Jev 判断几个还没判断的文件夹或标签（需要 Jev，否则返回 400，上游故障返回 502）；`PUT /api/v1/resource-classification/folders/override` 以 `mode` 为 `category` / `skip` / `auto` 手动指定、设为不沿用或恢复由 Jev 判断。`POST /api/v1/resource-classification/folders/retry` 只把原归类已对应到分类的已导入网页排队重新判断（需要 Jev），同样跳过人工确认、用户规则和确认失效；状态里的 `folder_retry_count` 是带原归类的网页数。已有任务正在运行时返回 409。暂停任务会被新的已完成队列替换。修复设置后使用 `POST /api/v1/resource-classification/resume` 或 Web「继续任务」，从暂停位置继续原队列，保留任务编号、创建时间、成功与未确定计数；已处理的成功或低置信度网页均不重复请求。旧客户端对暂停任务调用启动接口也会继续原队列。继续接口在没有暂停任务时返回 409；对仍在运行或等待重试的任务返回现有进度。队列租约防止多个工作线程重复领取，条目版本检查保护推理期间的手动修改或网址变更。

## 第三方登录回调

微信、Google、Apple 登录当前暂缓。即使配置了凭据，也必须同时设置
`MEMOISLE_OAUTH_LOGIN_ENABLED=true` 才会出现在登录页并接受授权请求。

重新启用时，在 Google、微信开放平台和 Apple Developer 中分别登记服务端回调：

```text
https://<api-domain>/api/v1/auth/google/callback
https://<api-domain>/api/v1/auth/wechat/callback
https://<api-domain>/api/v1/auth/apple/callback
```

登录成功后服务端会把 opaque Bearer 令牌放在 URL fragment 中回跳 Web 来源，或回跳
Android 自定义地址。令牌只在数据库保存 SHA-256 哈希，退出登录后会话可撤销。

## 邮箱登录

## 会议总结

服务端提供 `POST /api/v1/meeting/summary`，把转写交给 OpenAI 兼容 Chat Completions 接口，
生成会议概要、关键要点、决议、行动项和风险。未配置 `MEMOISLE_LLM_BASE_URL` 或
`MEMOISLE_LLM_MODEL` 时返回 503；模型调用失败时返回 502，客户端可保留原文并重试。

`POST /api/v1/auth/register` 和 `POST /api/v1/auth/login` 支持邮箱密码账号。
注册前先调用 `POST /api/v1/auth/verification-code` 发送六位验证码，再提交
`verification_code`、`password` 与 `confirm_password` 注册；两次密码不一致时返回 422。
验证码只保存哈希，默认 10 分钟有效，60 秒内不能重复发送，连续输错 5 次后失效。
注册成功后邮箱立即标记为已验证。旧版本产生的未验证账号仍可通过
`POST /auth/verify-email/request` 重新发送验证链接。

密码使用 PBKDF2-SHA256、随机盐和 600,000 次迭代保存；登录失败统一返回
“邮箱或密码不正确”。同一邮箱在 15 分钟内连续失败 5 次后返回 429，并携带
`Retry-After` 响应头。`POST /auth/password-reset/request` 发送 30 分钟有效的
一次性重置链接，`POST /auth/password-reset` 设置新密码、验证邮箱并撤销既有会话。
生产环境必须配置 AgentlyMail CLI 或 SMTP；开发模式可设置
`MEMOISLE_EMAIL_PROVIDER=outbox`，把邮件写入本地 `.eml` 收件箱。

## 数据导出

登录后可通过以下接口下载当前账号的数据副本：

- `GET /api/v1/exports/json`：适合完整备份和再次处理。
- `GET /api/v1/exports/csv`：保留全部公开字段，数组字段以 JSON 文本写入单元格。
- `GET /api/v1/exports/markdown`：适合人工阅读和归档。

三种格式都遵循回收站保留期，不包含访问令牌和录音二进制；响应使用
`Cache-Control: no-store`。JSON 导出的 `audio_files_included` 和
`image_files_included` 均为 `false`，并包含 `categories` 自定义分类模板。
图片条目只迁移标题、备注和图片元数据，原图需要在客户端重新上传。时间字段均为
UTC（ISO-8601，后缀 `Z`）；导入时无时区的时间按 UTC 解释。

完整备份可通过 `POST /api/v1/imports?format=json|csv` 写回当前账号，单次最多
5000 条、10 MB；按 `client_id`、单词词形和网页网址去重。Markdown 仅供阅读，
不能导入。Web 顶栏的「导入备份」使用该接口。

单词专用导入仍为 `POST /api/v1/words/import?format=json|csv`，单次最多 1000 条、
5 MB；完整 MemoIsle 导出中的非单词条目会跳过，重复词形不会再次创建。

## 图片收藏

图片收藏使用 `type=image`，正文可以为空，因此可以只上传一张图片：

```text
POST   /api/v1/memos/{id}/image?expected_version=N   # 上传或替换原图，裸二进制 + Content-Type
GET    /api/v1/memos/{id}/image                      # 按所有者读取原图
GET    /api/v1/memos/{id}/image/thumbnail             # 读取服务端生成的 WebP 缩略图
```

上传接受 PNG、JPEG、WebP、GIF，单张不超过 20 MB，单边不超过 12000 像素且总像素
不超过 5000 万；服务端会校验真实图片格式（不只信任 `Content-Type`），并用 EXIF
方向生成最大边 1280 像素的缩略图。超出上述限制时 Web 和 Android
会在客户端先压缩或缩放再上传，并提示用户压缩前后的大小与尺寸/格式变化；服务端
对绕过客户端的大图仍返回 413/422 作为安全兜底，不做二次编码。原图和缩略图的
文件名完全由服务端条目 ID 生成，读取时校验所有者。条目返回 `image_mime_type`、
`image_size_bytes`、`image_width`、`image_height` 和 `image_hash`；永久删除、清空
回收站和过期清理会一并删除文件。

图片条目计入 `GET /api/v1/memos/counts` 的 `image_count`，可参与类型筛选与跨类型
搜索，但当前不支持与其他类型互相转换。

## 图片 OCR 与自动标签

设置 `MEMOISLE_IMAGE_OCR_PROVIDER` 后，上传或替换图片会在后台识别文字并写入
`image_ocr_text`、`image_ocr_status`、`image_ocr_source` 和 `image_auto_tags`；
识别失败不影响图片本身已经保存，条目会记录 `failed`/`disabled` 与原因。

- `local`：本地引擎，优先 `rapidocr-onnxruntime`（pip 安装、模型随包、完全离线），
  其次 `pytesseract`（需要系统安装 tesseract 及语言包）。图片不出本机。
- `llm`：OpenAI 兼容的视觉模型，请求体为 `messages` 多模态格式，图片打成
  `data:image/jpeg;base64,...`，并要求返回 `{"text": "...", "tags": [...]}`。
  服务端会先生成最大边 1600 像素的 JPEG 预览图以控制体积；图片会发送到你配置的模型服务。
- `auto`：先用本地引擎，不可用时回退视觉模型；本地引擎可用但没有识别到文字时保留本地结果。

自动标签由“视觉模型返回的标签 + 本地关键词兜底”合并而成：本地兜底对英文按词频提取
（过滤停用词），对中文短句整段保留、长句用 4 字窗口统计重复短语。搜索接口的 `q` 会匹配
OCR 文本与自动标签，`tag` 过滤也能命中自动标签。

其他接口：

```text
POST /api/v1/memos/{id}/image/ocr   # 手动重新识别；未启用返回 503
```

服务重启后会把遗留的 `pending`/`processing` 条目重新排队识别。

## 复习计划

登录后可以通过 `GET/PATCH /api/v1/review-settings` 设置每日回顾队列上限
（1–100 条）和六档间隔天数（1–365 天）。`GET /api/v1/review-queue` 会按账号
设置限制队列；默认值为每日 10 条、`1/3/7/14/30/60` 天，旧账号会在启动时自动补齐字段。

## 语音转写与合成

Android 端录音停止后使用 sherpa-onnx SenseVoiceSmall INT8 在设备端转写。构建
前运行：

```bash
./android/scripts/download-sensevoice-model.sh
```

脚本会把官方模型中的 `model.int8.onnx` 和 `tokens.txt` 放到 Android assets；模型
文件不会提交到 Git。没有模型时仍可保存原始录音并手动填写文字。

服务端 TTS 使用可选的 `sanotts` Python 包生成 WAV，Web 和 Android 会优先请求该
接口，再回退到词典音频或系统/浏览器 TTS：

```bash
conda env update -f environment.yml
```

如果部署环境不需要服务端 TTS，可设置 `MEMOISLE_TTS_ENABLED=false`。sanoTTS 及其
音色包遵循 GPL-3.0-or-later，发布应用前请一并完成许可证和音色分发审查。

邮件渠道为 `auto` 时，后端会先检查 `agently-cli` 是否可执行；可执行时按
Heart-Plan 的方式调用 `message +send`，取得确认令牌后自动带令牌完成发送；找不到 CLI
时回退到 SMTP。使用 AgentlyMail 前，需让运行后端的同一系统用户完成 OAuth 授权，或通过
`MEMOISLE_AGENTLY_CLI_PATH` 指定 CLI 路径。

## 数据备份与恢复

需要备份的不只是数据库。下面两个密钥文件必须和数据库放在一起备份，否则恢复后库里加密的凭据无法解密：

- `.memoisle-auth.key`：登录会话签名密钥，云盘凭据默认也用它加密。显式设置了 `MEMOISLE_AUTH_TOKEN_SECRET` 时不会生成这个文件，请另外保存那个值。
- `.memoisle-model.key`：模型服务凭据的加密密钥。

`backend/scripts/backup.py` 会一起处理这些文件。数据位置读取与服务相同的 `MEMOISLE_*` 环境变量。

```bash
# 备份：服务运行中即可执行，用 SQLite 的 VACUUM INTO 生成一致快照
python backend/scripts/backup.py create --to /mnt/backup/memoisle --keep 14
# 只备份数据库与密钥，不带录音和图片
python backend/scripts/backup.py create --to /mnt/backup/memoisle --no-media
# 校验：按 manifest 里的 SHA-256 检查每个文件，并做 SQLite 完整性检查
python backend/scripts/backup.py verify /mnt/backup/memoisle/memoisle-backup-20261022T030000Z
# 恢复：先停止服务
python backend/scripts/backup.py restore /mnt/backup/memoisle/memoisle-backup-20261022T030000Z
```

- 每份备份是一个独立目录，先写到临时目录，全部完成后才改名，中途失败不会留下看起来完整、实际缺文件的备份。
- 恢复前会先校验，不通过就不动现有数据。现有数据不会被删除，而是挪到数据库旁边的 `pre-restore-<时间>` 目录，确认无误后再手动删除。
- 恢复时会把旧的 `-wal`、`-shm` 文件一起挪走，避免旧日志回放到恢复出来的库上。
- 定时备份可以交给 cron，例如每天凌晨 3 点：
  `0 3 * * * cd /srv/memoisle && python backend/scripts/backup.py create --to /mnt/backup/memoisle --keep 14`
- 备份目录里有密钥，请放在只有服务账号能读的位置。脚本会把复制出的密钥文件设为 0600。

## 测试

```bash
pytest
```
