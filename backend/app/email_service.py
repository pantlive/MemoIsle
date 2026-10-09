"""认证邮件构建与发送服务。"""

from __future__ import annotations

import json
import logging
import shutil
import smtplib
import subprocess
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any
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
    return _build_email_message(settings, recipient, subject, body), action_url


def _build_email_message(
    settings: Settings,
    recipient: str,
    subject: str,
    body: str,
) -> EmailMessage:
    """构造纯文本邮件。"""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = (
        settings.smtp_from_address
        or settings.smtp_username
        or "no-reply@memoisle.local"
    )
    message["To"] = recipient
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = make_msgid(domain="memoisle.local")
    message.set_content(body)
    return message


def send_verification_code_email(
    settings: Settings,
    recipient: str,
    code: str,
) -> None:
    """发送六位邮箱验证码。"""

    body = (
        "你的 MemoIsle 注册验证码是：\n\n"
        f"{code}\n\n"
        f"验证码 {settings.auth_verification_code_expire_minutes} 分钟内有效。"
        "如果不是你本人操作，请忽略这封邮件。"
    )
    send_email(settings, recipient, "MemoIsle 注册验证码", body)


def send_auth_email(
    settings: Settings,
    recipient: str,
    purpose: str,
    token: str,
) -> str:
    """通过配置的邮件渠道发送验证或密码重置邮件。"""

    message, action_url = build_auth_email(settings, recipient, purpose, token)
    _deliver_email(settings, message)
    return action_url


def send_email(
    settings: Settings,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """按配置的邮件渠道发送，开发模式默认写入本地收件箱。"""

    _deliver_email(settings, _build_email_message(settings, recipient, subject, body))


def _deliver_email(settings: Settings, message: EmailMessage) -> None:
    """根据配置选择邮件发送渠道。"""

    if settings.auth_dev_mode and settings.email_provider in {"auto", "outbox"}:
        _write_development_email(settings, message)
        return

    if settings.email_provider in {"auto", "agently"}:
        cli_path = shutil.which(settings.agently_cli_path)
        if cli_path is not None:
            _send_via_agently(cli_path, message)
            return
        if settings.email_provider == "agently":
            raise EmailDeliveryError("未找到 agently-cli")

    if settings.email_provider in {"auto", "smtp"}:
        # 发件人未单独配置时，使用 SMTP 登录用户名，兼容常见邮箱服务商。
        if settings.smtp_host and (
            settings.smtp_from_address or settings.smtp_username
        ):
            _send_via_smtp(settings, message)
            return
        if settings.email_provider == "smtp":
            raise EmailDeliveryError("SMTP 未完整配置")

    if settings.email_provider == "outbox" or settings.auth_dev_mode:
        _write_development_email(settings, message)
        return
    raise EmailDeliveryError("未配置邮件发送服务")


def _send_via_agently(cli_path: str, message: EmailMessage) -> None:
    """通过 agently-cli 发送邮件并自动完成 CLI 的二次确认。"""

    base_args = [
        "--to",
        message["To"] or "",
        "--subject",
        message["Subject"] or "",
        "--body",
        message.get_content(),
        "--body-format",
        "plain",
    ]
    first_result = _run_agently(cli_path, base_args)
    data = first_result.get("data")
    if not isinstance(data, dict):
        raise EmailDeliveryError("AgentlyMail 返回数据格式无效")
    confirmation_token = data.get("confirmation_token")
    if not isinstance(confirmation_token, str) or not confirmation_token:
        if data.get("confirmation_required"):
            raise EmailDeliveryError("AgentlyMail 未返回确认令牌")
        return
    _run_agently(
        cli_path,
        [*base_args, "--confirmation-token", confirmation_token],
    )


def _run_agently(cli_path: str, args: list[str]) -> dict[str, Any]:
    """运行 agently-cli 并解析 JSON 响应。"""

    try:
        result = subprocess.run(
            [cli_path, "message", "+send", *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.exception("调用 AgentlyMail CLI 失败")
        raise EmailDeliveryError("AgentlyMail 发送失败") from error
    if result.returncode != 0:
        logger.error("AgentlyMail CLI 返回失败状态：%s", result.returncode)
        raise EmailDeliveryError("AgentlyMail 发送失败")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        logger.error("AgentlyMail CLI 返回非 JSON 数据")
        raise EmailDeliveryError("AgentlyMail 返回数据无效") from error
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise EmailDeliveryError("AgentlyMail 发送失败")
    return payload


def _send_via_smtp(settings: Settings, message: EmailMessage) -> None:
    """通过 SMTP 发送邮件。"""

    try:
        if settings.smtp_use_ssl:
            smtp = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )
        else:
            smtp = smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=settings.smtp_timeout_seconds,
            )
        with smtp:
            smtp.ehlo()
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                smtp.starttls()
                smtp.ehlo()
            if settings.smtp_username or settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        logger.exception("发送认证邮件失败")
        raise EmailDeliveryError("认证邮件发送失败") from error


def _write_development_email(settings: Settings, message: EmailMessage) -> None:
    """将邮件写入本地开发收件箱。"""

    if not settings.auth_dev_mode:
        raise EmailDeliveryError("本地邮件收件箱仅允许开发模式使用")
    try:
        outbox_directory = Path(settings.email_outbox_directory)
        outbox_directory.mkdir(parents=True, exist_ok=True)
        # 文件名只使用 UUID 风格消息 ID，不携带收件人或验证码。
        output_path = outbox_directory / f"{uuid4()}.eml"
        output_path.write_bytes(message.as_bytes())
    except OSError as error:
        raise EmailDeliveryError("无法保存开发邮件") from error
