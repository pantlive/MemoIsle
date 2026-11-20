"""轻量文件与文本中转：只在进程内存里暂放，取走即删，不写数据库也不落盘。

Web 和 Android 之间互传一段文字或一个小文件。服务端只做转发：

- 内容放在当前进程内存里，按账号隔离；
- 接收端下载或忽略后立刻删除，没人取的 ``RELAY_TTL`` 后自动清理；
- 进程重启后未取走的内容全部丢失，所以只能单 worker 部署（见部署脚本）。

所有方法都必须在同一个事件循环线程里调用（接口全部是 ``async def``），
因此这里不加线程锁。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from app.service import MAX_IMAGE_BYTES

RelayDevice = Literal["web", "android"]
RelayKind = Literal["text", "file"]

RELAY_DEVICES: tuple[RelayDevice, ...] = ("web", "android")
# 单条文本按 UTF-8 字节计算，100 KB 足够一大段笔记或链接列表。
MAX_TEXT_BYTES = 100 * 1024
# 与图片上传上限一致，Caddy 的请求体上限是 30 MB。
MAX_FILE_BYTES = MAX_IMAGE_BYTES
MAX_PENDING_ITEMS = 10
MAX_PENDING_BYTES = 50 * 1024 * 1024
RELAY_TTL_SECONDS = 10 * 60
MAX_WAIT_SECONDS = 25
PURGE_INTERVAL_SECONDS = 30
MAX_FILENAME_LENGTH = 200
MAX_MIME_LENGTH = 100


class RelayError(Exception):
    """中转失败，``status_code`` 直接作为接口状态码。"""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RelayTooLargeError(RelayError):
    status_code = 413


class RelayQuotaError(RelayError):
    status_code = 429


class RelayNotFoundError(RelayError):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("内容不存在、已被取走或已过期")


@dataclass(slots=True)
class RelayItem:
    """一条待取的中转内容。``content`` 只在内存里。"""

    id: str
    kind: RelayKind
    source: RelayDevice
    target: RelayDevice
    created_at: float
    expires_at: float
    content: bytes
    filename: str | None = None
    mime_type: str | None = None

    @property
    def size(self) -> int:
        return len(self.content)

    def text(self) -> str | None:
        return self.content.decode("utf-8") if self.kind == "text" else None


@dataclass(slots=True)
class _UserBox:
    items: dict[str, RelayItem] = field(default_factory=dict)
    waiters: set[asyncio.Event] = field(default_factory=set)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.items.values())


def clean_filename(value: str | None) -> str:
    """去掉路径和控制字符，防止下载时被当成目录或注入响应头。"""

    raw = (value or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(
        char for char in raw if char.isprintable() and char not in '"<>|:*?'
    ).strip(" .")
    if not cleaned:
        return "file"
    if len(cleaned) > MAX_FILENAME_LENGTH:
        stem, dot, suffix = cleaned.rpartition(".")
        if dot and 0 < len(suffix) <= 16:
            keep = MAX_FILENAME_LENGTH - len(suffix) - 1
            return f"{stem[:keep]}.{suffix}"
        return cleaned[:MAX_FILENAME_LENGTH]
    return cleaned


def clean_mime_type(value: str | None) -> str:
    """只保留形如 ``type/subtype`` 的主类型，其余一律当作二进制。"""

    main = (value or "").split(";", 1)[0].strip().lower()
    if (
        not main
        or len(main) > MAX_MIME_LENGTH
        or main.count("/") != 1
        or not all(char.isalnum() or char in "/.+-" for char in main)
    ):
        return "application/octet-stream"
    return main


class RelayHub:
    """进程内中转站，按账号分开保存待取内容。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = RELAY_TTL_SECONDS,
    ) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._users: dict[str, _UserBox] = {}

    # —— 写入 ——

    def push_text(
        self, user_id: str, text: str, *, source: RelayDevice, target: RelayDevice
    ) -> RelayItem:
        if not text.strip():
            raise RelayError("内容不能为空")
        content = text.encode("utf-8")
        if len(content) > MAX_TEXT_BYTES:
            raise RelayTooLargeError("文本不能超过 100 KB，请改用文件发送")
        return self._push(
            user_id, kind="text", content=content, source=source, target=target
        )

    def push_file(
        self,
        user_id: str,
        content: bytes,
        *,
        filename: str | None,
        mime_type: str | None,
        source: RelayDevice,
        target: RelayDevice,
    ) -> RelayItem:
        if not content:
            raise RelayError("文件内容不能为空")
        if len(content) > MAX_FILE_BYTES:
            raise RelayTooLargeError("文件不能超过 20 MB")
        return self._push(
            user_id,
            kind="file",
            content=content,
            source=source,
            target=target,
            filename=clean_filename(filename),
            mime_type=clean_mime_type(mime_type),
        )

    def _push(
        self,
        user_id: str,
        *,
        kind: RelayKind,
        content: bytes,
        source: RelayDevice,
        target: RelayDevice,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> RelayItem:
        self.purge_expired()
        box = self._users.setdefault(user_id, _UserBox())
        if len(box.items) >= MAX_PENDING_ITEMS:
            raise RelayQuotaError(
                f"待接收的内容已有 {MAX_PENDING_ITEMS} 条，请先在另一端接收或忽略"
            )
        if box.total_bytes + len(content) > MAX_PENDING_BYTES:
            raise RelayQuotaError("待接收的内容合计超过 50 MB，请先在另一端接收或忽略")
        now = self._clock()
        item = RelayItem(
            id=str(uuid4()),
            kind=kind,
            source=source,
            target=target,
            created_at=now,
            expires_at=now + self._ttl,
            content=content,
            filename=filename,
            mime_type=mime_type,
        )
        box.items[item.id] = item
        self._notify(box)
        return item

    @staticmethod
    def _notify(box: _UserBox) -> None:
        for waiter in box.waiters:
            waiter.set()

    # —— 读取 ——

    def list_pending(self, user_id: str, device: RelayDevice) -> list[RelayItem]:
        """发给 ``device`` 的待取内容，先发的在前。"""

        self.purge_expired()
        box = self._users.get(user_id)
        if box is None:
            return []
        return [item for item in box.items.values() if item.target == device]

    async def wait_for(
        self,
        user_id: str,
        device: RelayDevice,
        timeout: float,
        known: frozenset[str] = frozenset(),
    ) -> list[RelayItem]:
        """长轮询：待取内容和客户端已有的 ``known`` 不一样时立刻返回。

        否则最多等 ``timeout`` 秒，期间有新内容或有内容被取走都会唤醒；
        超时返回当前列表（没有内容时为空）。客户端把已经显示的 id 传进来，
        列表里放着没处理的内容时也不会每次立刻返回、空转打满服务端。
        """

        pending = self.list_pending(user_id, device)
        if timeout <= 0 or {item.id for item in pending} != known:
            return pending
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        box = self._users.setdefault(user_id, _UserBox())
        waiter = asyncio.Event()
        box.waiters.add(waiter)
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return self.list_pending(user_id, device)
                try:
                    await asyncio.wait_for(waiter.wait(), remaining)
                except TimeoutError:
                    return self.list_pending(user_id, device)
                waiter.clear()
                pending = self.list_pending(user_id, device)
                if {item.id for item in pending} != known:
                    return pending
        finally:
            box.waiters.discard(waiter)
            self._drop_if_empty(user_id)

    def get(self, user_id: str, item_id: str) -> RelayItem:
        self.purge_expired()
        box = self._users.get(user_id)
        item = box.items.get(item_id) if box is not None else None
        if item is None:
            raise RelayNotFoundError()
        return item

    def take(self, user_id: str, item_id: str) -> RelayItem:
        """取出并删除；同一条只能取一次。"""

        item = self.get(user_id, item_id)
        box = self._users[user_id]
        del box.items[item_id]
        # 让其他标签页、设备的长轮询及时把这一条从列表里拿掉。
        self._notify(box)
        self._drop_if_empty(user_id)
        return item

    def discard(self, user_id: str, item_id: str) -> None:
        self.take(user_id, item_id)

    # —— 清理 ——

    def purge_expired(self) -> int:
        now = self._clock()
        removed = 0
        for user_id in list(self._users):
            box = self._users[user_id]
            expired = [key for key, item in box.items.items() if item.expires_at <= now]
            for key in expired:
                del box.items[key]
            removed += len(expired)
            self._drop_if_empty(user_id)
        return removed

    def _drop_if_empty(self, user_id: str) -> None:
        box = self._users.get(user_id)
        if box is not None and not box.items and not box.waiters:
            del self._users[user_id]

    def clear(self) -> None:
        self._users.clear()

    @property
    def total_items(self) -> int:
        return sum(len(box.items) for box in self._users.values())

    def now(self) -> float:
        return self._clock()


async def relay_purge_loop(
    hub: RelayHub,
    stop_event: asyncio.Event,
    interval_seconds: float = PURGE_INTERVAL_SECONDS,
) -> None:
    """定时清掉过期内容，直到应用退出。"""

    while not stop_event.is_set():
        hub.purge_expired()
        try:
            await asyncio.wait_for(stop_event.wait(), interval_seconds)
        except TimeoutError:
            continue


__all__ = [
    "MAX_FILE_BYTES",
    "MAX_PENDING_BYTES",
    "MAX_PENDING_ITEMS",
    "MAX_TEXT_BYTES",
    "MAX_WAIT_SECONDS",
    "RELAY_DEVICES",
    "RELAY_TTL_SECONDS",
    "RelayDevice",
    "RelayError",
    "RelayHub",
    "RelayItem",
    "RelayNotFoundError",
    "RelayQuotaError",
    "RelayTooLargeError",
    "clean_filename",
    "clean_mime_type",
    "relay_purge_loop",
]
