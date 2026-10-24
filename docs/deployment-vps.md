# VPS 部署

小内存服务器使用 FastAPI + SQLite、React 静态产物和 Caddy。运行依赖由 conda
管理，关闭本地 OCR 和服务端 TTS，不上传本地数据库、图片、录音或密钥。

## 目录与服务

- `/opt/memoisle`：代码、浏览器扩展运行文件与 `web/dist`。
- `/opt/memoisle/.conda`：Python 3.13 运行环境。
- `/etc/memoisle/memoisle.env`：生产环境配置，属主 root，权限 0600。
- `/var/lib/memoisle`：数据库、附件、持久化密钥及邮件授权，属主 memoisle，权限 0700。
- `memoisle.service`：独立账号运行 API，仅监听 `127.0.0.1:8000`。
- `caddy.service`：静态前端、API 反向代理与自动续期证书。

新建运行环境时，在已安装 conda 的服务器执行：

```bash
cd /opt/memoisle/deploy
conda env create --prefix /opt/memoisle/.conda --file environment-vps.yml
```

上传内容应包含 `backend/app`、`backend/scripts`、`backend/requirements.txt`、
`extension` 的运行文件、`deploy` 和本地执行 `cd web && npm ci && npm run build`
生成的 `web/dist`。扩展文件不可遗漏，Web 的扩展下载接口会直接读取它们。
上传后将源码与静态目录设为 0755、文件设为 0644，确保 memoisle 和 caddy
可以读取；私有环境配置和数据目录继续使用上述独立权限。

将 `deploy/memoisle.service` 安装到 `/etc/systemd/system/memoisle.service`，
按 `deploy/memoisle.env.example` 创建私有配置，准备服务账号和数据目录，然后执行：

```bash
systemctl daemon-reload
systemctl enable --now memoisle
curl --fail http://127.0.0.1:8000/api/v1/health
```

## hw 的端口与域名

`hw` 的 IP 是 `113.45.59.172`。443 保留给现有 DERP，8443 不用于 MemoIsle。
本项目使用 `deploy/Caddyfile.hw`，目标地址为 `https://memo.17115859.xyz:9443`。
环境配置中的 `MEMOISLE_WEB_BASE_URL` 和 `MEMOISLE_CORS_ORIGINS` 要包含该端口。

DNS 控制台需添加 A 记录：`memo` → `113.45.59.172`。云平台安全组和主机防火墙
需允许 TCP 80、9443；8000 仅供本机访问。Caddy 通过 80 的 HTTP-01 验证域名，
避免使用已被 DERP 占用的 443 完成证书验证。解析生效前，证书申请会失败并自动重试。
可通过 `http://113.45.59.172` 检查前端和 API；录音、密码库等浏览器功能需使用 HTTPS。

```bash
caddy validate --config /opt/memoisle/deploy/Caddyfile.hw --adapter caddyfile
install -m 644 /opt/memoisle/deploy/Caddyfile.hw /etc/caddy/Caddyfile
systemctl reload caddy
```

本次检查发现云厂商下发的 DNS `100.125.1.250` 无响应，已在服务器的
`/etc/systemd/resolved.conf.d/60-memoisle-dns.conf` 配置可用的公共解析器。
原 DHCP 配置保留，删除此新增文件并重启 `systemd-resolved` 可撤回该调整。

## 注册与找回密码邮件

`agent.qq.com` 邮箱使用 AgentlyMail OAuth，不需要填写普通 QQ 邮箱的 SMTP 授权码。
CLI 安装于 `/opt/memoisle/mail`，须以实际运行后端的 memoisle 用户完成授权：

```bash
npm install --prefix /opt/memoisle/mail --omit=dev --no-audit --no-fund @tencent-qqmail/agently-cli
runuser -u memoisle -- /opt/memoisle/mail/node_modules/.bin/agently-cli auth login
runuser -u memoisle -- /opt/memoisle/mail/node_modules/.bin/agently-cli +me
```

在浏览器使用预期的发件邮箱完成授权。不要复制其他机器或其他账号的授权文件。
在私有环境配置中设置：

```dotenv
MEMOISLE_EMAIL_PROVIDER=agently
MEMOISLE_AGENTLY_CLI_PATH=/opt/memoisle/mail/node_modules/.bin/agently-cli
```

若改用 SMTP，则填写服务商提供的 SMTP 地址、发件邮箱及授权码。
465 通常对应 `MEMOISLE_SMTP_USE_SSL=true`、`MEMOISLE_SMTP_USE_TLS=false`；
587 通常对应 `MEMOISLE_SMTP_USE_SSL=false`、`MEMOISLE_SMTP_USE_TLS=true`。
配置文件不可提交到仓库。更改环境配置后执行 `systemctl restart memoisle`。

## 验证、更新与备份

```bash
systemctl status memoisle caddy
journalctl -u memoisle -n 50 --no-pager
journalctl -u caddy -n 50 --no-pager
curl --fail http://113.45.59.172/api/v1/health
curl --fail https://memo.17115859.xyz:9443/api/v1/health
```

更新前按[后端备份说明](../backend/README.md#数据备份与恢复)备份数据库、媒体及
两个持久化密钥。备份进程需要与服务相同的 `MEMOISLE_*` 环境变量。
更新代码时不要覆盖 `/etc/memoisle`、`/var/lib/memoisle` 或现有 conda 环境；
依赖有变更才更新运行环境，然后重启 `memoisle` 并再次检查健康接口。

## Android 安装包分发

登录页、桌面顶栏和设置页的下载入口指向 `/api/v1/android/download`，无需登录。
生产签名 APK 独立保存在 `/opt/memoisle/downloads/memoisle-android.apk`，由后端直接
提供下载，支持 HEAD 和 Range。更换安装包时先完整上传为临时文件，再原子替换；
不需要重启服务。网站发布时保留 `downloads`，私钥与签名配置只保存在构建机器，
不要上传到 Web 目录。构建与签名流程见 [Android 说明](../android/README.md#网站下载安装包)。
