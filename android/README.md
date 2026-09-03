# MemoIsle Android

## 开发环境

- Android Gradle Plugin 9.2.0
- Gradle 9.4.1
- JDK 17 或兼容版本
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

- 邮箱密码、微信、Google 和 Apple ID 登录；登录令牌保存在私有偏好存储，切换账号会清空本机缓存。
- 通过系统浏览器完成 OAuth 授权，并使用 `memoisle://auth/callback` 深链返回应用。
- SQLite 本地灵感缓存。
- 离线创建与失败状态保留。
- 启动或手动刷新时上传待同步内容。
- 从共享 API 拉取 Web 创建的灵感。
- 标题、正文编辑和服务端版本冲突提示。
- 遵循 Stitch 设计系统的 Android 首页。
