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
`http://10.0.2.2:8000/api/v1/` 访问宿主机后端。Release 默认连接
`https://memo.17115859.xyz:9443/api/v1/`；部署到其他服务器时覆盖：

```bash
./gradlew assembleRelease \
  -PMEMOISLE_API_BASE_URL=https://example.com/api/v1/
```

## 网站下载安装包

网站的登录页、桌面顶栏和「设置 → 安卓客户端」提供公开 APK 下载：
`https://memo.17115859.xyz:9443/api/v1/android/download`。
网站发布包使用 Release 变体，API 地址为 `https://memo.17115859.xyz:9443/api/v1/`。
Release 仅包含 ARM64、ARM32 手机架构，原生库压缩打包，并开启 R8 代码与资源精简。
Debug 继续支持模拟器架构。语音 SDK 的 JNI 类、Room 数据库构造方法和 WorkManager 入口有专门的保留规则，
以保持本地语音和已有后台同步任务正常工作。
`0.1.2` 的签名 APK 实测约 24.2 MB，相比 `0.1.1` 的 135.8 MB 减少约 82%。
`0.1.3` 的签名 APK 约 24.3 MB，补充了桌面自适应图标和登录页标志，并修复
R8 删除 Room 无参构造方法导致的启动闪退。发布时必须实际安装签名 Release 包做冷启动验证；Debug 单元测试
不会覆盖 R8 反射入口的裁剪行为。检查 `adb logcat -b crash`，并确认登录页出现且
`/api/v1/auth/providers` 请求成功后，再替换网站下载包。
`0.1.4` 更新了首页、资料详情和密码库界面，统一图标、排版、类型配色与返回交互。

构建后使用 `scripts/sign-release.py` 签名。签名配置 JSON 需放在仓库外的私有目录，
包含 `keystore`、`alias`、`store_password` 和 `key_password`；密钥与配置文件权限
应为 0600。后续版本必须沿用同一签名密钥，并递增 `versionCode`，才能覆盖升级。

```bash
./gradlew assembleRelease \
  -PMEMOISLE_API_BASE_URL=https://memo.17115859.xyz:9443/api/v1/
python scripts/sign-release.py \
  --signing-config /private/path/signing.json \
  --api-base-url https://memo.17115859.xyz:9443/api/v1/
```

脚本核对 APK 内的 API 地址，按 16 KB 对齐后签名并验证，输出
`app/build/outputs/apk/release/memoisle-android.apk`。私钥和签名密码不进入安装包或仓库。
将签名 APK 上传到服务器 `/opt/memoisle/downloads/memoisle-android.apk`，源码更新时
保留该目录。自定义路径可设置后端环境变量 `MEMOISLE_ANDROID_APK_PATH`。
首次在手机安装时，按 Android 提示允许当前浏览器安装应用。

## 当前功能

- 邮箱密码登录与注册；邮箱注册后提示查收验证码，登录令牌保存在私有偏好存储，切换账号会清空本机缓存。
- 微信、Google、Apple 登录暂缓；后端未开启第三方登录时，登录页不展示这些入口。
- SQLite 本地灵感缓存。
- 离线创建与失败状态保留。
- 启动、登录后和手动刷新时上传待同步内容；WorkManager 在联网时后台重试，采用指数退避。
- 从共享 API 拉取 Web 创建的灵感。
- Web 永久删除、清空回收站或保留期清理后，增量同步通过 `deleted_items` 清除本地记录、录音、原图、缩略图和上传失败缓存；只含删除的页面也会继续读取。已删除记录的离线上传遇到 404/410 后停止重试。升级本地数据库至版本 13 时重建同步游标，以清理旧版本残留，保留未同步的新建草稿。需要安装本次构建的新版 APK 才能使用此同步行为。
- 标题、正文编辑和服务端版本冲突处理；退出前会先检查待同步内容。
- 顶栏「⋯」菜单里的「导出数据」使用系统文件选择器保存当前账号 JSON 数据副本；「退出登录」也在这个菜单里。
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
- 遵循 Stitch 设计系统的 Android 首页。界面统一使用 Material 图标（`material-icons-extended`）、
  自定义字号与圆角；灵感、单词、网页资料和图片各有固定的图标和配色，列表、快捷入口和详情共用。
  顶栏随页面切换标题，收件箱带数量角标，回收站、导出数据和退出登录收在「⋯」菜单；
  不在首页时按返回键先回到首页。网页资料用站点首字母头像（不加载第三方站点图标）。
  资料、图片、灵感、单词详情和密码库编辑页为全屏页面：左上角关闭，底部固定主操作；
  内容未修改时「保存修改」不可点。
- 网页资料显示服务端大模型写的用途简介（本地数据库版本 15，升级后完整同步一次）：列表、快速访问和回顾优先显示，
  没有时依次用网页描述和备注；详情页在描述上方单独显示「用途」。
- 快速访问：网页资料分区顶部按打开次数列出常用网页（与 Web 端共用同一份计数），点「×」可移除，
  Snackbar 提供撤销；从资料详情或回顾打开原网页都会计一次数，离线时不计数。
- 密码库：底部导航「密码库」入口。用与 Web 端相同的主密码在本机解锁（PBKDF2-SHA256 + AES-GCM，
  主密码和库密钥不离开设备），可查看、搜索、复制、新建、编辑和删除账号密码、密钥、云服务器和恢复码（云服务器可一键复制主机、密码或私钥和 `ssh -p 端口 用户@主机` 命令），
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
