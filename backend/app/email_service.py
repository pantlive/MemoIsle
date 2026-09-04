"""认证邮件构建与发送服务。"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from app.config import Settings

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """邮件发送或写入开发收件箱失败。"""


def _verification_url(settings: Settings, token: str, purpose: str) -> str:
    """构造指向 Web 的一次性操作链接。"""

    query_name = "verification_token" if purpose == "verify_email" else "reset_token"
    # 令牌本身由 URL 安全字母组成，quote 仍然防止后续格式调整引入特殊字符。
    return (
        f"{settings.web_base_url.rstrip('/')}/"
        f"?{query_name}={quote(token, safe='')}"
    )


def build_auth_email(
    settings: Settings,
    recipient: str,
    purpose: str,
    token: str,
) -> tuple[EmailMessage, str]:
    """构造邮件内容和正文中的操作链接。"""

    action_url = _verification_url(settings, token, purpose)
    if purpose == "verify_email":
        subject = "验证你的 MemoIsle 邮箱"
        body = (
            "欢迎注册 MemoIsle。\n\n"
            f"请点击下面的链接完成邮箱验证：\n{action_url}\n\n"
            "链接 24 小时内有效。如果不是你发起注册，请忽略这封邮件。"
        )
    else:
        subject = "重置你的 MemoIsle 密码"
        body = (
            "你请求重置 MemoIsle 密码。\n\n"
            f"请点击下面的链接设置新密码：\n{action_url}\n\n"
            "链接 30 分钟内有效。如果不是你发起请求，请忽略这封邮件。"
        )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = recipient
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = make_msgid(domain="memoisle.local")
    message.set_content(body)
    return message, action_url


def send_auth_email(
    settings: Settings,
    recipient: str,
    purpose: str,
    token: str,
) -> str:
    """通过 SMTP 发送邮件；开发模式可写入本地收件箱。"""

    message, action_url = build_auth_email(settings, recipient, purpose, token)
    if settings.smtp_host and settings.smtp_from_address:
        try:
            if settings.smtp_use_ssl:
                smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port)
            else:
                smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            with smtp:
                smtp.ehlo()
                if settings.smtp_use_tls and not settings.smtp_use_ssl:
                    smtp.starttls()
                    smtp.ehlo()
                if settings.smtp_username or settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
            return action_url
        except (OSError, smtplib.SMTPException) as error:
            logger.exception("发送认证邮件失败")
            raise EmailDeliveryError("认证邮件发送失败") from error

    if not settings.auth_dev_mode:
        raise EmailDeliveryError("未配置邮件发送服务")

    try:
        outbox_directory = Path(settings.email_outbox_directory)
        outbox_directory.mkdir(parents=True, exist_ok=True)
        # 文件名只使用 UUID 风格消息 ID，不携带收件人或令牌。
        output_path = outbox_directory / f"{uuid4()}.eml"
        output_path.write_bytes(message.as_bytes())
    except OSError as error:
        raise EmailDeliveryError("无法保存开发邮件") from error
    return action_url
