"""文件/文本中转：只在内存里转发，取走即删、按账号隔离、超限拒绝、到期清理。"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from app.auth_service import create_dev_session
from app.relay_api import _content_disposition
from app.relay_service import (
    MAX_FILE_BYTES,
    MAX_PENDING_ITEMS,
    MAX_TEXT_BYTES,
    RelayHub,
    RelayNotFoundError,
    RelayQuotaError,
    RelayTooLargeError,
    clean_filename,
    clean_mime_type,
    relay_purge_loop,
)
from fastapi.testclient import TestClient
from sqlalchemy import inspect

BASE = "/api/v1/relay"


def other_account_headers(client: TestClient) -> dict[str, str]:
    """新建另一个账号并关闭开发模式回退，之后不带令牌的请求会被拒绝。"""

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    return {"Authorization": f"Bearer {token}"}


def own_headers(client: TestClient) -> dict[str, str]:
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(session, settings).token
    return {"Authorization": f"Bearer {token}"}


def send_file(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "报告.pdf",
    target: str = "android",
    mime: str = "application/pdf",
    headers: dict[str, str] | None = None,
):
    return client.post(
        f"{BASE}/file",
        params={"target": target, "filename": filename},
        content=content,
        headers={"Content-Type": mime, **(headers or {})},
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 1_000_000.0

    def __call__(self) -> float:
        return self.value


def test_text_relay_from_web_to_android(client: TestClient) -> None:
    """Web 发的文字只出现在 Android 收件箱里，复制完删除后不再出现。"""

    response = client.post(
        f"{BASE}/text", json={"text": "你好 hello", "target": "android"}
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["kind"] == "text"
    assert created["source"] == "web"
    assert created["target"] == "android"
    assert created["size"] == len("你好 hello".encode())
    assert 0 < created["expires_in"] <= 600

    assert client.get(f"{BASE}/inbox", params={"device": "web"}).json() == []
    inbox = client.get(f"{BASE}/inbox", params={"device": "android"}).json()
    assert [item["text"] for item in inbox] == ["你好 hello"]

    assert client.delete(f"{BASE}/items/{created['id']}").status_code == 204
    assert client.get(f"{BASE}/inbox", params={"device": "android"}).json() == []
    assert client.delete(f"{BASE}/items/{created['id']}").status_code == 404


def test_source_follows_client_header(client: TestClient) -> None:
    """Android 客户端带 X-MemoIsle-Client: mobile，来源自动记为 android。"""

    response = client.post(
        f"{BASE}/text",
        json={"text": "来自手机", "target": "web"},
        headers={"X-MemoIsle-Client": "mobile"},
    )
    assert response.json()["source"] == "android"
    inbox = client.get(f"{BASE}/inbox", params={"device": "web"}).json()
    assert inbox[0]["source"] == "android"


def test_file_relay_is_taken_once(client: TestClient) -> None:
    """文件下载一次后立即删除，第二次下载 404，中文文件名按 RFC 5987 返回。"""

    content = b"%PDF-1.4 fake"
    response = send_file(client, content)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["filename"] == "报告.pdf"
    assert created["mime_type"] == "application/pdf"
    assert created["size"] == len(content)
    assert created["text"] is None

    inbox = client.get(f"{BASE}/inbox", params={"device": "android"}).json()
    assert [item["id"] for item in inbox] == [created["id"]]

    download = client.get(f"{BASE}/items/{created['id']}/download")
    assert download.status_code == 200
    assert download.content == content
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["cache-control"] == "no-store"
    assert f"filename*=UTF-8''{quote('报告.pdf')}" in download.headers[
        "content-disposition"
    ]

    assert client.get(f"{BASE}/items/{created['id']}/download").status_code == 404
    assert client.get(f"{BASE}/inbox", params={"device": "android"}).json() == []
    assert client.app.state.relay_hub.total_items == 0


def test_text_item_can_be_downloaded(client: TestClient) -> None:
    created = client.post(
        f"{BASE}/text", json={"text": "第一行\n第二行", "target": "web"}
    ).json()
    download = client.get(f"{BASE}/items/{created['id']}/download")
    assert download.status_code == 200
    assert download.text == "第一行\n第二行"
    assert download.headers["content-type"].startswith("text/plain")


def test_relay_is_isolated_between_accounts(client: TestClient) -> None:
    """别人看不到、取不走、删不掉，一律 404。"""

    mine = own_headers(client)
    created = client.post(
        f"{BASE}/text", json={"text": "仅自己可见", "target": "android"}, headers=mine
    ).json()
    file_item = send_file(client, b"secret", headers=mine).json()
    other = other_account_headers(client)

    inbox = client.get(f"{BASE}/inbox", params={"device": "android"}, headers=other)
    assert inbox.status_code == 200
    assert inbox.json() == []
    for item_id in (created["id"], file_item["id"]):
        assert client.get(
            f"{BASE}/items/{item_id}/download", headers=other
        ).status_code == 404
        deleted = client.delete(f"{BASE}/items/{item_id}", headers=other)
        assert deleted.status_code == 404

    own = client.get(f"{BASE}/inbox", params={"device": "android"}, headers=mine).json()
    assert {item["id"] for item in own} == {created["id"], file_item["id"]}


def test_relay_requires_login(client: TestClient) -> None:
    client.app.state.settings = replace(client.app.state.settings, auth_dev_mode=False)
    assert client.post(
        f"{BASE}/text", json={"text": "x", "target": "web"}
    ).status_code == 401
    assert send_file(client, b"x").status_code == 401
    assert client.get(f"{BASE}/inbox", params={"device": "web"}).status_code == 401
    assert client.get(f"{BASE}/items/abc/download").status_code == 401
    assert client.delete(f"{BASE}/items/abc").status_code == 401
    assert client.app.state.relay_hub.total_items == 0


def test_size_and_count_limits(client: TestClient) -> None:
    """超大文本、超大文件 413，待取条数超限 429，提示都是中文。"""

    too_long = "字" * (MAX_TEXT_BYTES // 3 + 1)
    response = client.post(f"{BASE}/text", json={"text": too_long, "target": "web"})
    assert response.status_code == 413
    assert "100 KB" in response.json()["detail"]

    response = send_file(client, b"x" * (MAX_FILE_BYTES + 1))
    assert response.status_code == 413
    assert "20 MB" in response.json()["detail"]

    response = client.post(
        f"{BASE}/file",
        params={"target": "web", "filename": "a.bin"},
        content=b"x",
        headers={"Content-Length": str(MAX_FILE_BYTES + 1)},
    )
    assert response.status_code in {400, 413}

    assert send_file(client, b"").status_code == 400
    assert client.post(
        f"{BASE}/text", json={"text": "   ", "target": "web"}
    ).status_code == 400
    assert client.post(
        f"{BASE}/text", json={"text": "x", "target": "tv"}
    ).status_code == 422

    for index in range(MAX_PENDING_ITEMS):
        assert client.post(
            f"{BASE}/text", json={"text": f"第{index}条", "target": "web"}
        ).status_code == 201
    response = client.post(f"{BASE}/text", json={"text": "多一条", "target": "android"})
    assert response.status_code == 429
    assert "10 条" in response.json()["detail"]


def test_total_bytes_limit() -> None:
    hub = RelayHub()
    chunk = b"x" * MAX_FILE_BYTES

    def push(user_id: str, content: bytes) -> None:
        hub.push_file(
            user_id,
            content,
            filename="a.bin",
            mime_type=None,
            source="web",
            target="android",
        )

    push("u", chunk)
    push("u", chunk)
    with pytest.raises(RelayQuotaError, match="50 MB"):
        push("u", chunk)
    # 另一个账号的额度不受影响。
    push("v", chunk)
    with pytest.raises(RelayTooLargeError):
        push("v", chunk + b"x")


def test_expired_items_are_purged() -> None:
    """到期后列表、下载都看不到；清理任务会把内存真正释放掉。"""

    clock = FakeClock()
    hub = RelayHub(clock=clock, ttl_seconds=600)
    item = hub.push_text("u", "过期前", source="web", target="android")
    clock.value += 599
    assert [entry.id for entry in hub.list_pending("u", "android")] == [item.id]
    clock.value += 1
    assert hub.list_pending("u", "android") == []
    with pytest.raises(RelayNotFoundError):
        hub.take("u", item.id)

    hub.push_text("u", "a", source="web", target="android")
    hub.push_text("v", "b", source="android", target="web")
    clock.value += 601
    assert hub.purge_expired() == 2
    assert hub.total_items == 0
    assert hub._users == {}


def test_purge_loop_stops_with_event() -> None:
    clock = FakeClock()
    hub = RelayHub(clock=clock, ttl_seconds=1)
    hub.push_text("u", "a", source="web", target="android")
    clock.value += 2

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(relay_purge_loop(hub, stop, interval_seconds=0.01))
        await asyncio.sleep(0.05)
        assert hub.total_items == 0
        stop.set()
        await asyncio.wait_for(task, 1)

    asyncio.run(scenario())


def test_long_poll_wakes_on_push_and_times_out() -> None:
    hub = RelayHub()

    async def scenario() -> None:
        started = time.monotonic()
        assert await hub.wait_for("u", "web", 0.05) == []
        assert time.monotonic() - started >= 0.04

        waiter = asyncio.create_task(hub.wait_for("u", "web", 5))
        await asyncio.sleep(0.02)
        # 发给另一端的内容不会唤醒本端返回。
        hub.push_text("u", "给手机", source="web", target="android")
        await asyncio.sleep(0.02)
        assert not waiter.done()
        hub.push_text("u", "给网页", source="android", target="web")
        items = await asyncio.wait_for(waiter, 1)
        assert [item.text() for item in items] == ["给网页"]
        # 等待结束后不留下等待者。
        assert hub._users["u"].waiters == set()

        # 客户端已经显示了这一条：不立刻返回，超时后原样带回列表。
        known = frozenset(item.id for item in items)
        started = time.monotonic()
        again = await hub.wait_for("u", "web", 0.05, known)
        assert time.monotonic() - started >= 0.04
        assert [item.id for item in again] == list(known)

        # 别处取走这一条时唤醒，返回新的（空）列表。
        waiter = asyncio.create_task(hub.wait_for("u", "web", 5, known))
        await asyncio.sleep(0.02)
        assert not waiter.done()
        hub.discard("u", next(iter(known)))
        assert await asyncio.wait_for(waiter, 1) == []

    asyncio.run(scenario())


def test_long_poll_over_http(client: TestClient) -> None:
    """接口层长轮询：另一线程发送后，等待中的请求立即带回内容。"""

    headers = own_headers(client)
    result: dict[str, object] = {}

    def poll() -> None:
        started = time.monotonic()
        response = client.get(
            f"{BASE}/inbox", params={"device": "web", "wait": 10}, headers=headers
        )
        result["elapsed"] = time.monotonic() - started
        result["body"] = response.json()

    thread = threading.Thread(target=poll)
    thread.start()
    time.sleep(0.3)
    client.post(
        f"{BASE}/text",
        json={"text": "唤醒", "target": "web", "source": "android"},
        headers=headers,
    )
    thread.join(5)
    assert not thread.is_alive()
    assert [item["text"] for item in result["body"]] == ["唤醒"]  # type: ignore[index]
    assert result["elapsed"] < 5  # type: ignore[operator]

    known = ",".join(item["id"] for item in result["body"])  # type: ignore[union-attr]
    started = time.monotonic()
    still = client.get(
        f"{BASE}/inbox",
        params={"device": "web", "wait": 1, "known": known},
        headers=headers,
    ).json()
    assert time.monotonic() - started >= 0.9
    assert [item["text"] for item in still] == ["唤醒"]

    assert client.get(
        f"{BASE}/inbox", params={"device": "web", "wait": 26}
    ).status_code == 422


def data_files(root: Path) -> set[Path]:
    sidecars = ("-wal", "-shm", "-journal")
    return {
        path
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(sidecars)
    }


def test_relay_never_touches_database_or_disk(
    client: TestClient, tmp_path: Path
) -> None:
    """收发前后数据库表结构和数据目录文件都不变。"""

    engine = client.app.state.database.engine
    tables_before = set(inspect(engine).get_table_names())
    files_before = data_files(tmp_path)

    created = send_file(client, b"payload-not-on-disk", filename="note.txt").json()
    client.post(f"{BASE}/text", json={"text": "payload-text", "target": "web"})
    assert client.get(f"{BASE}/items/{created['id']}/download").status_code == 200

    assert set(inspect(engine).get_table_names()) == tables_before
    assert not any("relay" in name for name in tables_before)
    assert data_files(tmp_path) == files_before
    # SQLite 的 -wal/-shm/-journal 由后台任务随时创建或回收，不比较文件名，
    # 但所有文件（包括数据库本身）里都不能出现中转内容。
    for path in tmp_path.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"payload-not-on-disk" not in data
            assert b"payload-text" not in data


def test_filename_and_mime_are_sanitized() -> None:
    assert clean_filename("../../etc/passwd") == "passwd"
    assert clean_filename("C:\\Users\\a\\报告.pdf") == "报告.pdf"
    assert clean_filename('a"b\r\n.txt') == "ab.txt"
    assert clean_filename("   ") == "file"
    long_name = "长" * 300 + ".jpeg"
    cleaned = clean_filename(long_name)
    assert len(cleaned) == 200 and cleaned.endswith(".jpeg")
    assert clean_mime_type("text/plain; charset=utf-8") == "text/plain"
    assert clean_mime_type("evil\r\nX: y") == "application/octet-stream"
    assert clean_mime_type(None) == "application/octet-stream"
    header = _content_disposition("报告 v2.pdf")
    assert header.startswith('attachment; filename="')
    assert "\r" not in header and "\n" not in header
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A%20v2.pdf" in header
