"""云盘适配层：统一各网盘的凭据校验、目录、转存、上传与元数据接口。

不同网盘的协议差异全部收敛在本层，上层只依赖 CloudDriveClient。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"aliyun", "baidu"})

PROVIDER_LABELS: dict[str, str] = {
    "aliyun": "阿里云盘",
    "baidu": "百度网盘",
}


class CloudDriveError(Exception):
    """云盘操作失败的基类。"""


class UnsupportedProviderError(CloudDriveError):
    """请求了尚未支持的云盘服务商。"""


class CredentialInvalidError(CloudDriveError):
    """凭据缺失、过期或已失效，需要用户重新粘贴。"""


class ShareLinkInvalidError(CloudDriveError):
    """分享链接失效、提取码错误或分享已被取消。"""


class QuotaExceededError(CloudDriveError):
    """云盘空间不足。"""


class RateLimitedError(CloudDriveError):
    """触发平台限流，可退避后重试。"""


class FileTooLargeError(CloudDriveError):
    """文件超过配置的大小上限。"""


class UnsupportedOperationError(CloudDriveError):
    """当前服务商或当前阶段尚未实现该能力。"""


@dataclass(frozen=True)
class AccountInfo:
    """凭据校验通过后拿到的账号信息。"""

    provider: str
    display_name: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FileRef:
    """云盘中的文件引用。"""

    file_id: str
    name: str
    path: str
    size_bytes: int | None = None
    parent_id: str | None = None


@dataclass(frozen=True)
class FileMeta:
    """文件元数据，用于写入 Memo.ebook_snapshot。"""

    file_id: str
    name: str
    path: str
    size_bytes: int | None = None
    content_hash: str | None = None
    category: str | None = None
    thumbnail: str | None = None
    updated_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_snapshot(self) -> dict[str, object]:
        """转成可直接落库的快照字典。"""

        return {
            "file_id": self.file_id,
            "name": self.name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "content_hash": self.content_hash,
            "category": self.category,
            "thumbnail": self.thumbnail,
            "updated_at": self.updated_at,
        }


class CloudDriveClient(Protocol):
    """云盘适配层统一接口。"""

    provider: str

    def check_credential(self) -> AccountInfo:
        """校验凭据并返回账号信息。"""

    def ensure_folder(self, path: str) -> str:
        """确保目录存在，返回目录 file_id。"""

    def transfer_share(
        self,
        share_url: str,
        password: str | None,
        target_folder_id: str,
    ) -> list[FileRef]:
        """把分享链接转存到目标目录，返回转存后的文件列表。"""

    def upload_file(
        self,
        local_path: Path,
        target_folder_id: str,
        name: str | None = None,
    ) -> FileRef:
        """把本地文件上传到目标目录。"""

    def get_file_meta(self, file_id: str) -> FileMeta:
        """读取文件元数据。"""


def provider_label(provider: str) -> str:
    """返回服务商中文名，未知服务商回退原值。"""

    return PROVIDER_LABELS.get(provider, provider)
