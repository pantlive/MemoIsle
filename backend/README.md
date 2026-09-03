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
- `MEMOISLE_AUTH_TOKEN_SECRET`：登录 state 与 Bearer 会话签名密钥，生产环境必须固定配置。
- `MEMOISLE_GOOGLE_CLIENT_ID` / `MEMOISLE_GOOGLE_CLIENT_SECRET`：Google OAuth 客户端凭据。
- `MEMOISLE_WECHAT_APP_ID` / `MEMOISLE_WECHAT_APP_SECRET`：微信开放平台网站应用凭据。
- `MEMOISLE_APPLE_CLIENT_ID` / `MEMOISLE_APPLE_CLIENT_SECRET`：Apple Services ID 与预生成的 client secret。
- `MEMOISLE_AUTH_MOBILE_REDIRECT_URI`：Android 登录回跳地址，默认 `memoisle://auth/callback`。
- `MEMOISLE_LOCAL_USER_ID`：本地开发登录使用的用户标识。
- `MEMOISLE_AUDIO_DIRECTORY`：原始录音的本地开发存储目录。

## 第三方登录回调

在 Google、微信开放平台和 Apple Developer 中分别登记服务端回调：

```text
https://<api-domain>/api/v1/auth/google/callback
https://<api-domain>/api/v1/auth/wechat/callback
https://<api-domain>/api/v1/auth/apple/callback
```

登录成功后服务端会把 opaque Bearer 令牌放在 URL fragment 中回跳 Web 来源，或回跳
Android 自定义地址。令牌只在数据库保存 SHA-256 哈希，退出登录后会话可撤销。

## 邮箱登录

`POST /api/v1/auth/register` 和 `POST /api/v1/auth/login` 支持邮箱密码账号。
注册请求必须提交 `password` 与 `confirm_password`，两次输入不一致时返回 422。
密码使用 PBKDF2-SHA256、随机盐和 600,000 次迭代保存；登录失败统一返回
“邮箱或密码不正确”。当前版本尚未接入邮件服务，因此不发送邮箱所有权验证邮件；
生产环境建议补充验证邮件、密码找回和登录频率限制后再对外开放。

## 测试

```bash
pytest
```
