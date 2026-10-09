# MemoIsle Windows 桌面端（C# / WinUI 3）

原生 WinUI 3 桌面应用，通过 HTTP 连接 MemoIsle 后端；相比 JVM/WebView 壳方案内存占用低一个量级。

## 内存实测（同一台机器）

| 实现 | 工作集 | 私有 / 提交 |
|---|---|---|
| WinUI 3 原生（Release，本工程） | **146 MB** | **95 MB** |
| WinUI 3 原生（Debug，本工程） | 155 MB | 96 MB |
| Compose Multiplatform（已移除的旧实现） | 294 MB | 639 MB |

## 环境要求

- Windows 10 1809+ / Windows 11
- .NET 8 SDK（`dotnet --list-sdks` 应包含 8.x）
  - 免安装方式：下载 `dotnet-sdk-8.0.x-win-x64.zip` 解压，直接使用其中的 `dotnet.exe`
- 首次构建会从 NuGet 还原 `Microsoft.WindowsAppSDK`（2.4.0）与 `Microsoft.Windows.SDK.BuildTools`

## 构建与运行

```bat
cd winui\MemoIsle.Desktop
dotnet build -c Release -p:Platform=x64
dotnet run -c Release -p:Platform=x64
```

推荐在用户目录下构建（例如 `%USERPROFILE%\memoisle-build`），不要把工程副本或 SDK 散放在系统盘根目录；`.NET 8 SDK` 也可解压到 `%USERPROFILE%\dotnet-sdk` 免安装使用。

一键构建打包：`powershell -ExecutionPolicy Bypass -File build-windows.ps1`（默认自包含），传 `-FrameworkDependent` 生成精简版。

产物路径：`winui\MemoIsle.Desktop\bin\x64\Release\net8.0-windows10.0.19041.0\win-x64\MemoIsle.Desktop.exe`

### 本机已验证的 Windows 编译环境

当前从 WSL 编辑代码；WinUI/XAML 需要先同步到 Windows 本地目录再构建，避免直接使用 `\\wsl.localhost\...` 源码路径导致 XAML 编译器异常。

| 项 | 路径 |
|---|---|
| WSL 源码目录 | `/home/lsl/project/github/MemoIsle/winui` |
| Windows 构建目录 | `%LOCALAPPDATA%\MemoIsle\winui-build` |
| 免安装 .NET SDK | `%USERPROFILE%\memoisle-tools\dotnet-sdk\dotnet.exe` |
| Debug 产物 | `%LOCALAPPDATA%\MemoIsle\winui-build\MemoIsle.Desktop\bin\x64\Debug\net8.0-windows10.0.19041.0\win-x64\MemoIsle.Desktop.exe` |

在 PowerShell 中同步、构建并启动：

```powershell
$source = "\\wsl.localhost\Ubuntu\home\lsl\project\github\MemoIsle\winui"
$target = Join-Path $env:LOCALAPPDATA "MemoIsle\winui-build"
$dotnet = Join-Path $env:USERPROFILE "memoisle-tools\dotnet-sdk\dotnet.exe"
$project = Join-Path $target "MemoIsle.Desktop\MemoIsle.Desktop.csproj"

robocopy $source $target /E /XD bin obj
if ($LASTEXITCODE -ge 8) { exit $LASTEXITCODE }

# 重新构建前退出应用，避免 EXE 被占用。
Stop-Process -Name MemoIsle.Desktop -Force -ErrorAction SilentlyContinue
& $dotnet build $project -c Debug -p:Platform=x64 --nologo

$exe = Join-Path $target "MemoIsle.Desktop\bin\x64\Debug\net8.0-windows10.0.19041.0\win-x64\MemoIsle.Desktop.exe"
Start-Process -FilePath $exe
```

`robocopy` 退出码 `0` 到 `7` 视为成功，`8` 及以上为失败。

工程使用 `WindowsPackageType=None`（免打包运行）。两种发布形态：

| 模式 | 目录体积 | 说明 |
|---|---|---|
| 默认自包含 | ~217 MB | 自带 .NET 与 Windows App SDK 运行时，解压即用 |
| `-FrameworkDependent` | ~156 MB | 不再携带 .NET 运行时，但 Windows App SDK 的 WinRT 投影程序集（Microsoft.WinUI.dll 等）必须随应用，属该技术栈固有体积 |

后端地址默认 `http://127.0.0.1:8000/api/v1`，可用环境变量覆盖：

```bat
set MEMOISLE_API_BASE_URL=https://api.example.com/api/v1
```

### SenseVoice 离线转写模型

会议录音结束后使用 sherpa-onnx SenseVoiceSmall INT8 离线转写。首次使用会自动下载模型压缩包（约 155 MB）并解压以下两个文件：

| 项 | 路径 / 变量 |
|---|---|
| 默认模型目录 | `%LOCALAPPDATA%\MemoIsle\models\sensevoice` |
| 默认模型文件 | `%LOCALAPPDATA%\MemoIsle\models\sensevoice\model.int8.onnx` |
| 默认词表文件 | `%LOCALAPPDATA%\MemoIsle\models\sensevoice\tokens.txt` |
| 自定义模型目录 | 环境变量 `MEMOISLE_SENSEVOICE_DIR` |
| 默认下载地址 | `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2` |
| 自定义下载地址 | 环境变量 `MEMOISLE_SENSEVOICE_MODEL_URL` |
| 下载临时文件 | `%TEMP%\memoisle-sensevoice.tar.bz2` |

相关 NuGet 包：`org.k2fsa.sherpa.onnx 1.13.8`；`.tar.bz2` 使用 Windows 自带 `tar.exe` 解压。

### 远端说话人分离模型

会议的系统声音轨会先使用 sherpa-onnx speaker diarization 区分远端参会人，再用 SenseVoice 识别每个说话人的发言。首次使用会自动下载两个模型（合计约 47 MB）：

| 项 | 路径 / 变量 |
|---|---|
| 默认模型目录 | `%LOCALAPPDATA%\MemoIsle\models\speaker-diarization` |
| pyannote 分段模型 | `%LOCALAPPDATA%\MemoIsle\models\speaker-diarization\segmentation.onnx` |
| 3DSpeaker 声纹模型 | `%LOCALAPPDATA%\MemoIsle\models\speaker-diarization\speaker-embedding.onnx` |
| 自定义模型目录 | 环境变量 `MEMOISLE_SPEAKER_DIARIZATION_DIR` |
| 分段模型下载地址 | `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2` |
| 声纹模型下载地址 | `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx` |
| 自定义分段模型地址 | 环境变量 `MEMOISLE_SPEAKER_SEGMENTATION_MODEL_URL`（需为包含 `model.onnx` 的 `.tar.bz2`） |
| 自定义声纹模型地址 | 环境变量 `MEMOISLE_SPEAKER_EMBEDDING_MODEL_URL`（需为 `.onnx`） |
| 聚类阈值 | 环境变量 `MEMOISLE_SPEAKER_DIARIZATION_THRESHOLD`，默认 `0.5`，可调范围 `0.1` 到 `0.9` |

输出说明：`对方1`、`对方2` 是声纹聚类编号，不代表真实姓名。模型下载、加载或推理失败时自动回退为统称 `对方`，不会阻塞会议录音保存。

## 已实现功能

**认证**：邮箱密码登录、验证码注册、开发者登录（后端开启时）；凭证存 `%APPDATA%\MemoIsle\session.json`

**收藏**：灵感 / 单词 / 网页资料三类；单词支持查词（多义项勾选填入）、系统语音发音、剪贴板智能解析（识别 `/音标/`、英文+中文混合行，过滤 URL）、重复词形"查看 / 合并例句 / 仍然保存"；资料支持拖拽链接或含 URL 文本到窗口直接收藏

**图片收藏**：快速捕获栏「收藏图片」或直接拖入本地 PNG / JPG / WebP / GIF（单张 ≤ 20MB）即可创建图片条目；列表显示登录态缩略图与尺寸/大小/MIME；详情对话框可预览缩略图、编辑标题与备注（备注可留空）、「替换图片」、「查看原图」（系统默认看图器）、「保存原图」（另存为）；侧栏「图片」独立计数与筛选。图片类型不支持与其他类型互相转换。图片在桌面端 / Web 端创作，安卓端只读。图片超过 20 MB、单边 12000 像素或 5000 万像素时会先自动压缩（PNG 保留透明，其余转 JPEG，动图只留第一帧）再上传，并在状态栏、图片对话框和系统通知里提示压缩前后的大小与尺寸/格式变化。服务端启用后会上传即触发图片文字识别（OCR）：对话框展示识别状态（未识别 / 排队中 / 识别中 / 已识别 / 识别失败 / 服务端未启用）、识别文字与自动标签，识别来源（本地识别 / 视觉模型）由服务端配置决定，识别完成后自动刷新，也可在对话框里手动「识别文字 / 重新识别」。

**资料库**：全部 / 灵感 / 单词 / 资料 / 图片导航与计数；服务端搜索（250ms 防抖）、仅看星标、资料分类过滤、6 种排序、资料视图 20 条/页分页与列表/卡片双视图；编辑、删除、星标；资料元数据后台处理时每 5 秒自动刷新

**复习**：混合 / 单词 / 待读 / 待整理筛选与统计；单词「忘了 / 模糊 / 记住了」反馈；待读资料"打开网页并标记阅读中"；待整理灵感"整理完成 / 归档"；跳过；队列内星标

**回收站**：恢复、彻底删除、剩余保留天数提示

**网页巡检**：8 种状态筛选、问题计数徽章、重新检查 / 采用跳转新网址 / 更新网址 / 忽略 / 恢复巡检 / 删除

**书签导入**：解析 Chrome/Edge 导出 HTML（≤10MB / ≤5000 条，本地解析不上传）、服务端去重预览、后台导入进度、失败重试、整批撤销

**分类管理**：系统分类只读、自定义分类创建与启停、domain / url / text 分类规则增删

**语音灵感**：MediaCapture 录制 MP4/AAC、录制中实时转写（SpeechRecognizer，不可用时降级手动输入）、试听与重录、上传后可在列表"▶ 播放"

**会议录音与总结**：侧栏“灵感”旁可开始会议录音；支持来源/输出设备/输入设备选择、暂停与继续。点击“结束并保存”后先区分系统声音中的远端说话人，再用 SenseVoice 分别识别系统声音与麦克风音轨，生成“我 / 对方1 / 对方2”对话式转写，并调用后端 OpenAI 兼容模型生成会议总结；列表条目支持 ▶ 播放录音、查看转写。Web/安卓端会同步展示已保存的转写，不在端上重复执行会议转写。说话人分离失败时自动回退为“对方”。后端需配置 `MEMOISLE_LLM_BASE_URL` 与 `MEMOISLE_LLM_MODEL`

**桌面特性**：拖拽收藏、单实例保护、窗口位置与大小记忆、跟随系统的深色模式、批量操作（多选后批量星标/移入回收站/恢复）、快捷键（`Ctrl+N` 新建、`Ctrl+F` 搜索、`Ctrl+R` 刷新、`Ctrl+I/W/L` 直接新建灵感/单词/资料，对话框内 `Ctrl+Enter` 保存、`Esc` 关闭）

**全局热键（免切换收藏与翻译）**：应用在后台运行时，在任何程序里复制内容后按键即可直接入库并弹系统通知——`Ctrl+Shift+W` 收藏剪贴板单词（自动查词补全）、`Ctrl+Shift+L` 收藏剪贴板网址、`Ctrl+Shift+I` 收藏剪贴板灵感；**`Ctrl+Alt+D` 划词翻译**（在鼠标附近弹出结果小窗，译文自动复制，可一键收藏为灵感）。全部可在设置中改绑

**划词翻译**：选中文字后直接按全局快捷键即可——程序会**自动模拟 Ctrl+C 取词**（取词后还原你原来的剪贴板内容，可在设置里关闭自动取词改为手动复制）。结果在鼠标附近的小窗展示，译文自动复制，可一键收藏为灵感。提供方支持：Google 免费接口（无需密钥）、自配大模型（任意 OpenAI 兼容端点，如官方 API、DeepSeek、Ollama、vLLM）、**自动模式（优先 Google，失败回退大模型）**；可设目标语言（中/英/日/韩/法/德/西/俄）、系统提示词、自动复制开关；设置面板内有"测试翻译"按钮

**诊断日志**：`%APPDATA%\MemoIsle\diagnostics.log` 记录全局热键注册结果（OK/FAIL）与翻译调用详情，用于排查"按键没反应"类问题

**系统托盘**：关闭窗口后驻留托盘继续提供全局热键；托盘菜单支持显示主窗口、快速收藏剪贴板单词、退出；双击托盘图标恢复窗口

**设置面板**：快捷键自定义（含全局热键，改绑即时生效）、分类模板与规则管理

**资料管理**：条目的"更多操作"菜单可改分类（含清除）与阅读状态（未读/阅读中/已完成/已归档）；含缩略图的资料在卡片视图显示配图；发音优先服务端 TTS，失败回退系统语音；回收站支持逐条或一键清空

## 目录结构

```
winui/MemoIsle.Desktop/
├── App.xaml(.cs)          # 应用入口
├── MainWindow.xaml(.cs)   # 登录 + 资料库 + 复习 + 回收站界面
├── MemoDialogs.cs         # 新建/编辑对话框
├── Models/                # Memo 与认证/请求模型
├── Services/              # API 客户端、令牌存储、应用状态、系统语音
└── Assets/                # 图标（icon.ico/png 与生成脚本）
```
