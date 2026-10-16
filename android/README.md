# MemoIsle Android

## 开发环境

- Android Gradle Plugin 9.2.0
- Gradle 9.4.1
- 完整 JDK 17 或兼容版本（必须包含 `javac`，不能只有 JRE；本次也已用 conda OpenJDK 25 完成构建与 lint）
- Android SDK 36
- 最低 Android API 26

当前依赖版本与本机已能构建的 `HomesteadArchive` Android 工程保持一致。

## 运行

1. 启动仓库中的后端服务。
2. 使用 Android Studio 打开 `android/`。
3. 启动 API 36 模拟器并运行 `app` Debug 变体。

Debug 版本默认通过模拟器地址
`http://10.0.2.2:8000/api/v1/` 访问宿主机后端。Release 构建必须设置：

```bash
./gradlew assembleRelease \
  -PMEMOISLE_API_BASE_URL=https://example.com/api/v1/
```

## 当前功能

- 邮箱密码登录与注册；邮箱注册后提示查收验证码，登录令牌保存在私有偏好存储，切换账号会清空本机缓存。
- 微信、Google、Apple 登录暂缓；后端未开启第三方登录时，登录页不展示这些入口。
- SQLite 本地灵感缓存。
- 离线创建与失败状态保留。
- 启动、登录后和手动刷新时上传待同步内容；WorkManager 在联网时后台重试，采用指数退避。
- 从共享 API 拉取 Web 创建的灵感。
- Web 永久删除、清空回收站或保留期清理后，增量同步通过 `deleted_items` 清除本地记录、录音、原图、缩略图和上传失败缓存；只含删除的页面也会继续读取。已删除记录的离线上传遇到 404/410 后停止重试。升级本地数据库至版本 13 时重建同步游标，以清理旧版本残留，保留未同步的新建草稿。需要安装本次构建的新版 APK 才能使用此同步行为。
- 标题、正文编辑和服务端版本冲突处理；退出前会先检查待同步内容。
- 顶栏“导出”使用系统文件选择器保存当前账号 JSON 数据副本。
- 录音结束后使用 sherpa-onnx SenseVoiceSmall INT8 在设备端转写；Release 首次使用时
  下载约 160 MB 的官方模型到应用私有目录，下载失败时仍保留录音并允许手工输入。
- 单词、例句和内容发音优先请求后端 sanoTTS，失败时回退词典音频和 Android 系统 TTS。
- 图片收藏：资料库新增「图片」筛选，列表显示带鉴权的缩略图；详情先显示缩略图、可展开原图，
  并展示尺寸、大小和 MIME。首页快速动作或图片工作区通过系统相册选择器（`PickVisualMedia`，
  无需存储权限）创建条目并上传原图（PNG/JPEG/WebP/GIF，单张 ≤ 20 MB），失败保留本地草稿并在
  同步时重试；图片字节缓存在应用缓存目录，退出登录、切换账号或永久删除时清理。
- 图片超过 20 MB、单边 12000 像素或 5000 万像素时，会先降采样/缩放并重新编码
  （PNG 保留透明，其余转 JPEG）再上传，并用 Snackbar 提示压缩前后的大小与尺寸/格式变化；
  未超限的图片原样上传，不做二次压缩。
- 遵循 Stitch 设计系统的 Android 首页。
- 快速访问：网页资料分区顶部按打开次数列出常用网页（与 Web 端共用同一份计数），点「×」可移除，
  Snackbar 提供撤销；从资料详情或回顾打开原网页都会计一次数，离线时不计数。
- 密码库：底部导航「密码库」入口。用与 Web 端相同的主密码在本机解锁（PBKDF2-SHA256 + AES-GCM，
  主密码和库密钥不离开设备），可查看、搜索、复制、新建、编辑和删除账号密码、密钥和恢复码，
  并显示与 Web 端规则相同的密码提醒（到期、定期更换、弱密码、重复密码、恢复码不足）。
  页面禁止截屏，复制的内容 30 秒后从剪贴板清除；5 分钟无操作、App 退到后台或退出登录都会锁定。
  首次设置主密码、更改主密码和加密备份导出/导入仍在 Web 端完成。

构建 STT AAR：

```bash
./gradlew testDebugUnitTest assembleDebug lintDebug
```

Release 默认不打包约 229 MB 的模型权重，首次结束录音时从固定版本官方压缩包下载，
解压后校验 SHA-256 并原子写入 `noBackupFilesDir/models/sensevoice/`。模型和压缩包都
不会进入 Git。需要离线验证 Debug 变体时，可执行：

```bash
./scripts/download-sensevoice-model.sh
./gradlew testDebugUnitTest assembleDebug lintDebug
```

脚本将模型放到 `app/src/debug/assets/models/sensevoice/`，因此只影响 Debug APK；
构建脚本会自动下载并缓存 sherpa-onnx AAR，网络不可用时可提前放入
`app/build/third-party/`。也可以通过 `-PMEMOISLE_SENSEVOICE_MODEL_URL=...` 指定
内部模型镜像地址。

Android 端 TTS 请求服务端 `POST /api/v1/speech/tts`，因此需要先按[后端说明](../backend/README.md)
安装 `sanotts`；无网络、未登录或服务端未配置时会自动使用系统 TTS。
