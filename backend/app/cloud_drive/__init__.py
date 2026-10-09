"""云盘适配层入口：按服务商构建客户端。"""

from __future__ import annotations

import httpx

from app.cloud_drive.aliyun import AliyunDriveClient, parse_aliyun_credential
from app.cloud_drive.baidu import BaiduPanClient, parse_baidu_credential
from app.cloud_drive.base import (
    SUPPORTED_PROVIDERS,
    AccountInfo,
    CloudDriveClient,
    CloudDriveError,
    CredentialInvalidError,
    FileMeta,
    FileRef,
    FileTooLargeError,
    QuotaExceededError,
    RateLimitedError,
    ShareLinkInvalidError,
    UnsupportedOperationError,
    UnsupportedProviderError,
    provider_label,
)

__all__ = [
    "SUPPORTED_PROVIDERS",
    "AccountInfo",
    "AliyunDriveClient",
    "BaiduPanClient",
    "CloudDriveClient",
    "CloudDriveError",
    "CredentialInvalidError",
    "FileMeta",
    "FileRef",
    "FileTooLargeError",
    "QuotaExceededError",
    "RateLimitedError",
    "ShareLinkInvalidError",
    "UnsupportedOperationError",
    "UnsupportedProviderError",
    "build_client",
    "parse_aliyun_credential",
    "parse_baidu_credential",
    "provider_label",
]


def build_client(
    provider: str,
    credential: str,
    *,
    timeout: float = 30.0,
    http_client: httpx.Client | None = None,
) -> CloudDriveClient:
    """按服务商构建云盘客户端。"""

    if provider == "aliyun":
        return AliyunDriveClient(
            credential,
            timeout=timeout,
            http_client=http_client,
        )
    if provider == "baidu":
        return BaiduPanClient(
            credential,
            timeout=timeout,
            http_client=http_client,
        )
    raise UnsupportedProviderError(f"尚未支持的云盘服务商：{provider}")
