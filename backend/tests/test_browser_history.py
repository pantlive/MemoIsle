"""浏览器浏览历史同步与查询测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.browser_history_service import clear_browser_history
from app.models import BrowserHistoryEntry
from fastapi.testclient import TestClient
from sqlalchemy import select, text

EXTENSION_ID = "b" * 32
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"


def visit_payload(
    url: str,
    title: str = "示例网页",
    visited_at: datetime | None = None,
    visit_count: int = 1,
) -> dict[str, object]:
    """生成一条扩展上报的浏览记录。"""

    return {
        "page_url": url,
        "page_title": title,
        "favicon_url": None,
        "visited_at": (visited_at or datetime.now(UTC)).isoformat(),
        "visit_count": visit_count,
    }


def test_history_sync_requires_extension_origin(client: TestClient) -> None:
    """来源不是声明的扩展时拒绝写入。"""

    response = client.post(
        "/api/v1/browser-history/sync",
        json={
            "extension_id": EXTENSION_ID,
            "visits": [visit_payload("https://public.example/guide")],
        },
    )
    assert response.status_code == 403


def test_history_sync_merges_visits_by_normalized_url(
    client: TestClient,
) -> None:
    """同一网址重复上报只保留一行，累计次数取较大值。"""

    earlier = datetime.now(UTC) - timedelta(hours=2)
    first = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://public.example/guide", "指南", earlier, 1),
            ],
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["synced_count"] == 1
    assert body["total_count"] == 1
    # 没带设备标识时归到 legacy，并且没有「疑似同一台机器」的候选。
    assert body["device_id"] == "legacy"
    assert body["possible_same_device_id"] is None

    # 规范化后同一个网址（补根路径、大写主机）不应产生第二行。
    later = datetime.now(UTC)
    second = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://PUBLIC.example/guide", "指南（新版）", later, 5),
            ],
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["synced_count"] == 1
    assert second_body["total_count"] == 1

    listing = client.get("/api/v1/browser-history").json()
    assert listing["extension_connected"] is True
    assert listing["total_count"] == 1
    item = listing["items"][0]
    assert item["page_url"] == "https://public.example/guide"
    assert item["page_title"] == "指南（新版）"
    assert item["visit_count"] == 5
    assert item["saved_memo_id"] is None


def test_history_sync_skips_internal_and_private_pages(
    client: TestClient,
) -> None:
    """浏览器内部页和本地地址不进入历史列表。"""

    response = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("chrome://extensions"),
                visit_payload("file:///C:/private.txt"),
                visit_payload("http://localhost/admin"),
                visit_payload("http://192.168.1.10/internal"),
                visit_payload("https://public.example/guide"),
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["synced_count"] == 1
    items = client.get("/api/v1/browser-history").json()["items"]
    assert [item["page_url"] for item in items] == [
        "https://public.example/guide",
    ]


def seed_two_eras(client: TestClient) -> None:
    """写入一条 45 天前和一条 2 天前的记录。"""

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload(
                    "https://public.example/old",
                    "旧记录",
                    datetime.now(UTC) - timedelta(days=45),
                ),
                visit_payload(
                    "https://public.example/recent",
                    "最近记录",
                    datetime.now(UTC) - timedelta(days=2),
                ),
            ],
        },
    )


def test_history_search_only_covers_recent_days(client: TestClient) -> None:
    """历史长期保留，但默认检索与列表只看最近 30 天。"""

    seed_two_eras(client)

    default_view = client.get("/api/v1/browser-history").json()
    assert [item["page_title"] for item in default_view["items"]] == ["最近记录"]
    assert default_view["window_days"] == 30
    assert default_view["extended_search_enabled"] is False

    # 没在设置里打开时，手改参数也翻不出更早的记录。
    widened = client.get("/api/v1/browser-history?days=365").json()
    assert [item["page_title"] for item in widened["items"]] == ["最近记录"]

    searched = client.get("/api/v1/browser-history?q=旧记录").json()
    assert searched["items"] == []

    with client.app.state.database.session_factory() as session:
        # 超出展示窗口的记录仍在库里，只是不进入列表与搜索。
        assert len(session.scalars(select(BrowserHistoryEntry)).all()) == 2


def test_extended_search_setting_unlocks_older_history(
    client: TestClient,
) -> None:
    """在设置里打开后，可以按 90/365 天或全部时间搜索更早的历史。"""

    seed_two_eras(client)

    toggled = client.patch(
        "/api/v1/browser-history/settings",
        json={"extended_search_enabled": True},
    )
    assert toggled.status_code == 200
    assert toggled.json() == {"extended_search_enabled": True}

    # 默认窗口不因开关自动放宽，避免每次打开面板都扫全表。
    default_view = client.get("/api/v1/browser-history").json()
    assert [item["page_title"] for item in default_view["items"]] == ["最近记录"]
    assert default_view["window_days"] == 30
    assert default_view["extended_search_enabled"] is True

    widened = client.get("/api/v1/browser-history?days=90").json()
    assert {item["page_title"] for item in widened["items"]} == {
        "旧记录",
        "最近记录",
    }
    assert widened["window_days"] == 90

    searched = client.get("/api/v1/browser-history?q=旧记录&days=90").json()
    assert [item["page_title"] for item in searched["items"]] == ["旧记录"]

    # days=0 表示不限时间，返回的窗口是 null。
    all_time = client.get("/api/v1/browser-history?days=0").json()
    assert all_time["window_days"] is None
    assert {item["page_title"] for item in all_time["items"]} == {
        "旧记录",
        "最近记录",
    }

    # 非法档位不放行，仍然回落到 30 天。
    fallback = client.get("/api/v1/browser-history?days=45").json()
    assert fallback["window_days"] == 30
    assert [item["page_title"] for item in fallback["items"]] == ["最近记录"]

    # 关掉后立刻回到 30 天，不需要清缓存。
    client.patch(
        "/api/v1/browser-history/settings",
        json={"extended_search_enabled": False},
    )
    closed = client.get("/api/v1/browser-history?days=90").json()
    assert closed["window_days"] == 30
    assert [item["page_title"] for item in closed["items"]] == ["最近记录"]


def test_history_settings_defaults_to_off(client: TestClient) -> None:
    """新账号默认只能搜索最近 30 天。"""

    response = client.get("/api/v1/browser-history/settings")
    assert response.status_code == 200
    assert response.json() == {"extended_search_enabled": False}


def test_history_marks_urls_already_in_library(client: TestClient) -> None:
    """资料库已收藏的网址在历史列表里带出条目 ID。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": "0f4b8d3e-0d33-4a08-9d61-2d8f0c2f1a11",
            "type": "resource",
            "body": "https://public.example/guide",
            "source_url": "https://public.example/guide",
            "source_title": "指南",
            "tags": [],
        },
    )
    assert created.status_code == 201
    memo_id = created.json()["id"]

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [visit_payload("https://public.example/guide", "指南")],
        },
    )

    items = client.get("/api/v1/browser-history").json()["items"]
    assert items[0]["saved_memo_id"] == memo_id


def test_history_replace_all_clears_removed_records(client: TestClient) -> None:
    """浏览器清空历史后，服务端同账号记录同步清空。"""

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://public.example/one"),
                visit_payload("https://public.example/two"),
            ],
        },
    )
    cleared = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [visit_payload("https://public.example/two")],
            "replace_all": True,
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["total_count"] == 1
    items = client.get("/api/v1/browser-history").json()["items"]
    assert [item["page_url"] for item in items] == ["https://public.example/two"]


def test_history_paginates_newest_first(client: TestClient) -> None:
    """分页按最近访问时间倒序，offset 可继续往后翻。"""

    now = datetime.now(UTC)
    visits = [
        visit_payload(
            f"https://public.example/page-{index}",
            f"第 {index} 页",
            now - timedelta(minutes=index),
        )
        for index in range(5)
    ]
    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={"extension_id": EXTENSION_ID, "visits": visits},
    )

    first_page = client.get("/api/v1/browser-history?limit=2").json()
    assert [item["page_title"] for item in first_page["items"]] == [
        "第 0 页",
        "第 1 页",
    ]
    assert first_page["total_count"] == 5

    second_page = client.get("/api/v1/browser-history?limit=2&offset=2").json()
    assert [item["page_title"] for item in second_page["items"]] == [
        "第 2 页",
        "第 3 页",
    ]


def test_history_reports_extension_not_connected(client: TestClient) -> None:
    """尚未同步过历史时明确告诉前端扩展未连接。"""

    listing = client.get("/api/v1/browser-history").json()
    assert listing["extension_connected"] is False
    assert listing["synced_at"] is None
    assert listing["items"] == []


def test_clear_history_keeps_saved_resources(client: TestClient) -> None:
    """清空历史只删记录，已收藏进资料库的网页保留。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": "6a1f0d34-58c6-4f4f-b6a6-3d5a1d3c7b22",
            "type": "resource",
            "body": "https://public.example/guide",
            "source_url": "https://public.example/guide",
            "source_title": "指南",
            "tags": [],
        },
    )
    assert created.status_code == 201
    memo_id = created.json()["id"]

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://public.example/guide"),
                visit_payload("https://public.example/other"),
            ],
        },
    )

    cleared = client.delete("/api/v1/browser-history")
    assert cleared.status_code == 204

    listing = client.get("/api/v1/browser-history").json()
    assert listing["items"] == []
    # 同步状态一并清掉，前端会重新提示「扩展未连接」。
    assert listing["extension_connected"] is False
    with client.app.state.database.session_factory() as session:
        assert session.scalars(select(BrowserHistoryEntry)).all() == []

    # 资料库里的网页资料不受影响。
    assert client.get(f"/api/v1/memos/{memo_id}").status_code == 200


def test_history_groups_entries_by_local_day(client: TestClient) -> None:
    """返回按访问日期分块的结果，日期按前端时区换算。"""

    # UTC 23:30 在 +08:00 已是第二天，分组要跟用户看到的日期一致。
    late = datetime(2026, 10, 20, 23, 30, tzinfo=UTC)
    early = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    same_local_day = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://public.example/a", "A", late),
                visit_payload("https://public.example/b", "B", early),
                visit_payload("https://public.example/c", "C", same_local_day),
            ],
        },
    )

    payload = client.get("/api/v1/browser-history?tz_offset=480").json()
    groups = payload["days"]
    assert [group["date"] for group in groups] == ["2026-10-21", "2026-10-20"]
    assert [group["count"] for group in groups] == [1, 2]
    assert [item["page_title"] for item in groups[0]["items"]] == ["A"]
    assert [item["page_title"] for item in groups[1]["items"]] == ["B", "C"]
    # items 与分块内容一致，旧客户端仍可逐条渲染。
    assert len(payload["items"]) == 3


def test_history_filters_by_date_range(client: TestClient) -> None:
    """按本地日期查询，边界按前端时区换算。"""

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload(
                    "https://public.example/old",
                    "十月十日",
                    datetime(2026, 10, 10, 12, tzinfo=UTC),
                ),
                visit_payload(
                    "https://public.example/mid",
                    "十月十五",
                    datetime(2026, 10, 15, 12, tzinfo=UTC),
                ),
                visit_payload(
                    "https://public.example/new",
                    "十月二十",
                    datetime(2026, 10, 20, 12, tzinfo=UTC),
                ),
            ],
        },
    )

    single_day = client.get(
        "/api/v1/browser-history?from=2026-10-15&to=2026-10-15",
    ).json()
    assert [item["page_title"] for item in single_day["items"]] == ["十月十五"]
    assert [group["date"] for group in single_day["days"]] == ["2026-10-15"]

    range_view = client.get(
        "/api/v1/browser-history?from=2026-10-12&to=2026-10-21",
    ).json()
    assert {item["page_title"] for item in range_view["items"]} == {
        "十月十五",
        "十月二十",
    }

    # 日期范围优先于默认 30 天窗口，可以查到更早的记录。
    old_only = client.get(
        "/api/v1/browser-history?from=2026-10-01&to=2026-10-11",
    ).json()
    assert [item["page_title"] for item in old_only["items"]] == ["十月十日"]


def test_history_date_filter_respects_timezone(client: TestClient) -> None:
    """同一时刻在 +08:00 与 UTC 下可能落在不同日期。"""

    entry_at = datetime(2026, 10, 20, 23, 30, tzinfo=UTC)
    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [visit_payload("https://public.example/late", "深夜", entry_at)],
        },
    )

    in_utc = client.get(
        "/api/v1/browser-history?from=2026-10-20&to=2026-10-20&tz_offset=0",
    ).json()
    assert len(in_utc["items"]) == 1

    in_shanghai = client.get(
        "/api/v1/browser-history?from=2026-10-21&to=2026-10-21&tz_offset=480",
    ).json()
    assert len(in_shanghai["items"]) == 1

    wrong_day = client.get(
        "/api/v1/browser-history?from=2026-10-20&to=2026-10-20&tz_offset=480",
    ).json()
    assert wrong_day["items"] == []


def test_history_paginates_page_by_page_without_total_cap(
    client: TestClient,
) -> None:
    """每页最多 1000 条，但翻页没有总量上限，能一直翻到最后一条。"""

    now = datetime.now(UTC)
    visits = [
        visit_payload(
            f"https://public.example/page-{index}",
            f"第 {index} 条",
            now - timedelta(seconds=index),
        )
        for index in range(1050)
    ]
    # 单次同步最多 500 条，分批提交同样能合并进历史表。
    for start in range(0, len(visits), 500):
        response = client.post(
            "/api/v1/browser-history/sync",
            headers={"Origin": EXTENSION_ORIGIN},
            json={
                "extension_id": EXTENSION_ID,
                "visits": visits[start : start + 500],
            },
        )
        assert response.status_code == 200, response.text

    first = client.get("/api/v1/browser-history?limit=1000").json()
    assert first["total_count"] == 1050
    assert first["page_size"] == 1000
    assert first["offset"] == 0
    assert first["has_more"] is True
    assert first["next_offset"] == 1000
    assert len(first["items"]) == 1000
    assert sum(group["count"] for group in first["days"]) == 1000

    # 第二页越过 1000 条，仍然能拿到剩下的 50 条。
    second = client.get(
        f"/api/v1/browser-history?limit=1000&offset={first['next_offset']}",
    ).json()
    assert len(second["items"]) == 50
    assert second["has_more"] is False
    assert second["next_offset"] is None
    assert second["total_count"] == 1050

    # 两页拼起来正好是全部记录，没有重复也没有遗漏。
    titles = {item["page_title"] for item in first["items"] + second["items"]}
    assert titles == {f"第 {index} 条" for index in range(1050)}

    # 单页上限 1000，参数再大直接被拒，而不是悄悄截断。
    oversized = client.get("/api/v1/browser-history?limit=5000")
    assert oversized.status_code == 422

    # 翻过末尾返回空页，分页标记同时收尾。
    beyond = client.get("/api/v1/browser-history?limit=200&offset=1050").json()
    assert beyond["items"] == []
    assert beyond["days"] == []
    assert beyond["has_more"] is False
    assert beyond["total_count"] == 1050


def test_sync_total_count_matches_actual_rows(client: TestClient) -> None:
    """增量维护的 total_count 与真实条数一致，不需要每次 count 全表。"""

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://public.example/a"),
                visit_payload("https://public.example/b"),
            ],
        },
    )
    # 第二批既有新增也有重复，只有新增才算进 total。
    second = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://public.example/b"),
                visit_payload("https://public.example/c"),
            ],
        },
    )
    assert second.json()["total_count"] == 3

    with client.app.state.database.session_factory() as session:
        actual = len(session.scalars(select(BrowserHistoryEntry)).all())
    assert actual == 3
    assert client.get("/api/v1/browser-history").json()["total_count"] == 3


def test_history_uses_covering_index_for_paging(client: TestClient) -> None:
    """翻页索引包含 (user_id, last_visited_at, id)，排序不再建临时 B 树。"""

    with client.app.state.database.session_factory() as session:
        plan = session.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT * FROM browser_history_entry "
                "WHERE user_id = 'u1' "
                "ORDER BY last_visited_at DESC, id DESC LIMIT 200",
            ),
        ).all()

    detail = " ".join(str(row[-1]) for row in plan)
    assert "ix_browser_history_entry_user_visited" in detail
    # 排序完全由索引满足，出现临时 B 树说明索引缺了 id 列。
    assert "TEMP B-TREE" not in detail


def test_clear_history_does_not_load_rows(client: TestClient) -> None:
    """清空历史走批量 DELETE，不把记录加载成 ORM 对象。"""

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload(f"https://public.example/p{index}")
                for index in range(20)
            ],
        },
    )

    user_id = client.app.state.settings.local_user_id
    with client.app.state.database.session_factory() as session:
        deleted = clear_browser_history(session, user_id)
    assert deleted == 20
    with client.app.state.database.session_factory() as session:
        assert session.scalars(select(BrowserHistoryEntry)).all() == []


def test_replace_all_clears_with_one_batch_delete(client: TestClient) -> None:
    """浏览器清空历史时保留本次上报的那部分，其余批量删除。"""

    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [
                visit_payload("https://public.example/keep"),
                visit_payload("https://public.example/drop-1"),
                visit_payload("https://public.example/drop-2"),
            ],
        },
    )
    replaced = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "visits": [visit_payload("https://public.example/keep")],
            "replace_all": True,
        },
    )
    assert replaced.status_code == 200
    items = client.get("/api/v1/browser-history").json()["items"]
    assert [item["page_url"] for item in items] == [
        "https://public.example/keep",
    ]


def seed_history(client: TestClient, count: int) -> None:
    """写入若干条按秒递减的历史，便于验证翻页顺序。"""

    now = datetime.now(UTC)
    visits = [
        visit_payload(
            f"https://public.example/c{index}",
            f"第 {index} 条",
            now - timedelta(seconds=index),
        )
        for index in range(count)
    ]
    for start in range(0, len(visits), 500):
        response = client.post(
            "/api/v1/browser-history/sync",
            headers={"Origin": EXTENSION_ORIGIN},
            json={
                "extension_id": EXTENSION_ID,
                "visits": visits[start : start + 500],
            },
        )
        assert response.status_code == 200, response.text


def test_cursor_pagination_walks_every_row_once(client: TestClient) -> None:
    """用 next_cursor 连续翻页，能按顺序取完所有记录且不重复。"""

    seed_history(client, 450)

    collected: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        query = "/api/v1/browser-history?limit=100"
        if cursor:
            query += f"&cursor={cursor}"
        payload = client.get(query).json()
        pages += 1
        collected.extend(item["page_title"] for item in payload["items"])
        assert payload["has_more"] is (payload["next_cursor"] is not None)
        if not payload["has_more"]:
            break
        cursor = payload["next_cursor"]
        assert pages < 20, "翻页没有终止"

    assert pages == 5
    assert len(collected) == 450
    assert len(set(collected)) == 450
    # 顺序是最近访问优先，即第 0 条在前。
    assert collected[:3] == ["第 0 条", "第 1 条", "第 2 条"]
    assert collected[-1] == "第 449 条"


def test_cursor_ignores_offset_and_reports_offset_zero(
    client: TestClient,
) -> None:
    """游标模式下 offset 不生效，也不会给出 next_offset 入口。"""

    seed_history(client, 250)
    first = client.get("/api/v1/browser-history?limit=100").json()
    cursor = first["next_cursor"]
    assert cursor

    # 同时传一个错误的 offset，游标仍然以锚点为准。
    second = client.get(
        f"/api/v1/browser-history?limit=100&cursor={cursor}&offset=9999",
    ).json()
    assert second["offset"] == 0
    assert second["next_offset"] is None
    assert [item["page_title"] for item in second["items"]][:2] == [
        "第 100 条",
        "第 101 条",
    ]


def test_invalid_cursor_falls_back_to_offset(client: TestClient) -> None:
    """坏游标不报错，退回 offset 分页继续工作。"""

    seed_history(client, 120)
    payload = client.get(
        "/api/v1/browser-history?limit=50&cursor=not-a-real-cursor&offset=50",
    ).json()
    assert payload["offset"] == 50
    assert [item["page_title"] for item in payload["items"]][:2] == [
        "第 50 条",
        "第 51 条",
    ]


def test_cursor_respects_filters(client: TestClient) -> None:
    """游标翻页与关键词、日期筛选叠加时仍然正确。"""

    seed_history(client, 60)
    filtered = client.get("/api/v1/browser-history?q=第 1&limit=5").json()
    # 「第 1」「第 10~19」「第 1x」都命中，至少能翻几页。
    cursor = filtered["next_cursor"]
    assert cursor
    next_page = client.get(
        f"/api/v1/browser-history?q=第 1&limit=5&cursor={cursor}",
    ).json()
    assert next_page["items"]
    titles = {item["page_title"] for item in filtered["items"] + next_page["items"]}
    assert titles.isdisjoint({"第 2 条"})


def sync_from_device(
    client: TestClient,
    device_id: str,
    device_name: str,
    visits: list[dict[str, object]],
    replace_all: bool = False,
) -> dict[str, object]:
    """以指定设备身份上报历史。

    每次调用都先清掉设备 Cookie：不同 device_id 代表不同电脑，
    而真实的另一台电脑浏览器里没有这台机器的 Cookie。
    """

    client.cookies.clear()
    response = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "device_id": device_id,
            "device_name": device_name,
            "visits": visits,
            "replace_all": replace_all,
        },
    )
    assert response.status_code == 200, response.text
    result: dict[str, object] = response.json()
    return result


def test_two_devices_keep_separate_rows_and_merge_in_list(
    client: TestClient,
) -> None:
    """同一账号两台电脑：各自记账，列表默认合并成一行。"""

    shared = "https://public.example/shared"
    sync_from_device(
        client,
        "mac-1",
        "Mac · Chrome",
        [visit_payload(shared, "共享页面", visit_count=3)],
    )
    sync_from_device(
        client,
        "win-2",
        "Windows · Edge",
        [visit_payload(shared, "共享页面", visit_count=5)],
    )

    # 库里是两行，各自独立。
    with client.app.state.database.session_factory() as session:
        rows = session.scalars(select(BrowserHistoryEntry)).all()
    assert {row.device_id for row in rows} == {"mac-1", "win-2"}
    assert {row.visit_count for row in rows} == {3, 5}

    # 合并视图：一行，访问次数相加，设备取最近访问的那台。
    merged = client.get("/api/v1/browser-history").json()
    assert len(merged["items"]) == 1
    assert merged["items"][0]["visit_count"] == 8
    # 响应里的 device_id 为空表示「合并所有设备」，条目自身带来源设备。
    assert merged["device_id"] is None
    assert merged["items"][0]["device_id"] == "win-2"
    assert merged["items"][0]["device_name"] == "Windows · Edge"

    # 按设备筛选：各看各的。
    mac_only = client.get("/api/v1/browser-history?device_id=mac-1").json()
    assert [item["visit_count"] for item in mac_only["items"]] == [3]
    assert mac_only["device_id"] == "mac-1"


def test_device_list_is_returned(client: TestClient) -> None:
    """响应带上所有同步过的设备，供前端做筛选。"""

    sync_from_device(
        client,
        "mac-1",
        "Mac · Chrome",
        [visit_payload("https://public.example/a")],
    )
    sync_from_device(
        client,
        "win-2",
        "Windows · Edge",
        [visit_payload("https://public.example/b")],
    )

    payload = client.get("/api/v1/browser-history").json()
    devices = {item["device_id"]: item for item in payload["devices"]}
    assert set(devices) == {"mac-1", "win-2"}
    assert devices["mac-1"]["device_name"] == "Mac · Chrome"
    assert devices["win-2"]["device_name"] == "Windows · Edge"
    assert all(item["total_count"] == 1 for item in devices.values())


def test_replacing_history_only_affects_one_device(
    client: TestClient,
) -> None:
    """在 A 电脑清空历史，不能删掉 B 电脑的记录。"""

    keep = "https://public.example/keep"
    other = "https://public.example/other"
    sync_from_device(client, "mac-1", "Mac", [visit_payload(keep)])
    sync_from_device(
        client,
        "win-2",
        "Windows",
        [visit_payload(keep), visit_payload(other)],
    )

    # mac-1 清空自己的历史，只保留 keep。
    sync_from_device(
        client,
        "mac-1",
        "Mac",
        [visit_payload(keep)],
        replace_all=True,
    )

    with client.app.state.database.session_factory() as session:
        rows = session.scalars(select(BrowserHistoryEntry)).all()
    # Windows 的两条都还在，Mac 只剩 keep。
    assert {(row.device_id, row.page_url) for row in rows} == {
        ("mac-1", keep),
        ("win-2", keep),
        ("win-2", other),
    }


def test_device_names_are_sanitized(client: TestClient) -> None:
    """异常的设备标识和名称会被清理，不进坏数据。"""

    response = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "device_id": "mac 1/../bad!",
            "device_name": "  Mac\n  Chrome  ",
            "visits": [visit_payload("https://public.example/a")],
        },
    )
    assert response.status_code == 200
    devices = client.get("/api/v1/browser-history").json()["devices"]
    assert devices[0]["device_id"] == "mac1bad"
    assert devices[0]["device_name"] == "Mac Chrome"


def test_legacy_database_gains_device_isolation(tmp_path: Path) -> None:
    """老库升级：补 device_id、换唯一键，旧记录落到 legacy 设备。"""

    import sqlite3

    from app.database import Database

    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE browser_history_entry (
          id VARCHAR(36) PRIMARY KEY,
          user_id VARCHAR(36) NOT NULL,
          url_key VARCHAR(64) NOT NULL,
          page_url VARCHAR(2048) NOT NULL,
          page_title VARCHAR(300) NOT NULL,
          favicon_url VARCHAR(2048),
          visit_count INTEGER NOT NULL,
          first_visited_at DATETIME NOT NULL,
          last_visited_at DATETIME NOT NULL
        );
        CREATE UNIQUE INDEX uq_browser_history_entry_user_url
          ON browser_history_entry (user_id, url_key);
        CREATE INDEX ix_browser_history_entry_user_visited
          ON browser_history_entry (user_id, last_visited_at);
        CREATE TABLE browser_history_sync_state (
          id VARCHAR(36) PRIMARY KEY,
          user_id VARCHAR(36) NOT NULL,
          extension_id VARCHAR(64) NOT NULL,
          total_count INTEGER NOT NULL,
          synced_at DATETIME NOT NULL
        );
        INSERT INTO browser_history_entry VALUES
          ('a1', 'u1', 'k1', 'https://old/1', '旧记录', NULL, 2,
           '2026-10-01', '2026-10-01');
        """,
    )
    connection.commit()
    connection.close()

    database = Database(f"sqlite+pysqlite:///{database_path}")
    database.create_schema()
    try:
        with database.engine.connect() as session:
            columns = {
                row[1]
                for row in session.exec_driver_sql(
                    "PRAGMA table_info(browser_history_entry)",
                )
            }
            state_columns = {
                row[1]
                for row in session.exec_driver_sql(
                    "PRAGMA table_info(browser_history_sync_state)",
                )
            }
            rows = session.exec_driver_sql(
                "SELECT page_url, device_id FROM browser_history_entry",
            ).all()
            indexes = {
                row[0]
                for row in session.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'index' "
                    "AND tbl_name = 'browser_history_entry'",
                )
            }
        assert "device_id" in columns
        assert {"device_id", "device_name"} <= state_columns
        # 旧记录统一归到 legacy 设备，不丢数据。
        assert rows == [("https://old/1", "legacy")]
        # 唯一键换成带 device_id 的版本，否则两台设备存同一网址会冲突。
        assert "uq_browser_history_entry_user_device_url" in indexes
        assert "uq_browser_history_entry_user_url" not in indexes
    finally:
        database.dispose()


def test_merged_pagination_does_not_repeat_urls(client: TestClient) -> None:
    """合并视图翻页时，同一网址的其他设备记录不能被当成新条目再出现一次。"""

    now = datetime.now(UTC)
    sync_from_device(
        client,
        "mac",
        "Mac",
        [
            visit_payload(
                "https://public.example/A",
                "A",
                now - timedelta(hours=1),
                visit_count=5,
            ),
            visit_payload(
                "https://public.example/C",
                "C",
                now - timedelta(hours=4),
            ),
        ],
    )
    sync_from_device(
        client,
        "win",
        "Windows",
        [
            # A 在第二台设备上更早访问，排在 B 后面。
            visit_payload(
                "https://public.example/A",
                "A",
                now - timedelta(hours=3),
                visit_count=7,
            ),
            visit_payload(
                "https://public.example/B",
                "B",
                now - timedelta(hours=2),
            ),
        ],
    )

    # 小页量强制分页，逐页收集。
    collected: list[tuple[str, int]] = []
    cursor: str | None = None
    for _ in range(10):
        query = "/api/v1/browser-history?limit=2"
        if cursor:
            query += f"&cursor={cursor}"
        page = client.get(query).json()
        collected.extend(
            (item["page_title"], item["visit_count"]) for item in page["items"]
        )
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]

    titles = [title for title, _ in collected]
    assert titles == ["A", "B", "C"], f"分页结果异常：{collected}"
    assert len(titles) == len(set(titles)), "同一网址在分页里重复出现"
    # 访问次数跨设备相加：5 + 7。
    assert collected[0] == ("A", 12)

    # 与一次取全的结果完全一致。
    whole = client.get("/api/v1/browser-history?limit=100").json()
    assert [
        (item["page_title"], item["visit_count"]) for item in whole["items"]
    ] == collected


def sync_with_identity(
    client: TestClient,
    device_id: str,
    device_name: str,
    hardware_key: str,
    install_id: str,
    visits: list[dict[str, object]],
) -> dict[str, object]:
    """带机器指纹上报，返回响应体。"""

    response = client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "device_id": device_id,
            "device_name": device_name,
            "hardware_key": hardware_key,
            "install_id": install_id,
            "visits": visits,
        },
    )
    assert response.status_code == 200, response.text
    result: dict[str, object] = response.json()
    return result


def forget_device_cookie(client: TestClient) -> None:
    """清掉设备 Cookie，模拟「换了一台电脑」。

    真实的另一台电脑浏览器里没有这个 Cookie；测试里所有请求共用一个
    TestClient，必须手动清掉才能还原这个前提。
    """

    client.cookies.clear()


def test_same_fingerprint_reports_possible_same_device(
    client: TestClient,
) -> None:
    """同款电脑算出相同指纹时，服务端要指认「疑似同一台机器」。"""

    sync_with_identity(
        client,
        "mac-a",
        "Mac",
        "fingerprint-1",
        "install-a",
        [visit_payload("https://public.example/a")],
    )
    # 另一台电脑没有这台机器的设备 Cookie。
    forget_device_cookie(client)
    second = sync_with_identity(
        client,
        "mac-b",
        "Mac",
        "fingerprint-1",
        "install-b",
        [visit_payload("https://public.example/b")],
    )
    # 第二台机器用新 ID 落库，但会被告知可能和 mac-a 是同一台。
    assert second["device_id"] == "mac-b"
    assert second["possible_same_device_id"] == "mac-a"

    devices = client.get("/api/v1/browser-history").json()["devices"]
    hints = {item["device_id"]: item["possible_same_device_id"] for item in devices}
    assert hints == {"mac-a": None, "mac-b": "mac-a"}


def test_reinstalled_extension_is_flagged_for_merge(client: TestClient) -> None:
    """Cookie 也被清掉时，只能靠指纹提示用户确认是否合并。"""

    sync_with_identity(
        client,
        "mac-original",
        "Mac",
        "fingerprint-1",
        "install-old",
        [visit_payload("https://public.example/a")],
    )
    # 重装且用户清过 Cookie（或换了浏览器配置）：指纹还在，ID 是新的。
    forget_device_cookie(client)
    result = sync_with_identity(
        client,
        "mac-reinstalled",
        "Mac",
        "fingerprint-1",
        "install-new",
        [visit_payload("https://public.example/b")],
    )
    assert result["possible_same_device_id"] == "mac-original"

    # 用户确认是同一台机器后合并，两台的历史并到一起。
    merged = client.post(
        "/api/v1/browser-history/devices/mac-reinstalled/merge",
        json={"target_device_id": "mac-original"},
    )
    assert merged.status_code == 200
    assert merged.json()["total_count"] == 2

    devices = client.get("/api/v1/browser-history").json()["devices"]
    assert [item["device_id"] for item in devices] == ["mac-original"]
    items = client.get("/api/v1/browser-history").json()["items"]
    assert {item["page_url"] for item in items} == {
        "https://public.example/a",
        "https://public.example/b",
    }


def test_same_fingerprint_different_install_gets_separate_device(
    client: TestClient,
) -> None:
    """指纹撞车的另一台机器继续用原设备 ID 上报时，要分出独立设备。"""

    sync_with_identity(
        client,
        "shared-id",
        "Mac",
        "fingerprint-1",
        "install-a",
        [visit_payload("https://public.example/a")],
    )
    # 另一台同款电脑也把 device_id 算成了 shared-id，但安装标识不同。
    result = sync_with_identity(
        client,
        "shared-id",
        "Mac",
        "fingerprint-1",
        "install-b",
        [visit_payload("https://public.example/b")],
    )
    assert result["device_id"] != "shared-id"
    assert result["possible_same_device_id"] == "shared-id"

    # 两条历史落在不同设备上，互不覆盖。
    with client.app.state.database.session_factory() as session:
        rows = session.scalars(select(BrowserHistoryEntry)).all()
    assert len({row.device_id for row in rows}) == 2


def test_rename_and_delete_device(client: TestClient) -> None:
    """设备可改名，也可单独删除而不影响其他设备。"""

    sync_from_device(client, "mac-1", "Mac", [visit_payload("https://public.example/a")])
    sync_from_device(client, "win-2", "Windows", [visit_payload("https://public.example/b")])

    renamed = client.patch(
        "/api/v1/browser-history/devices/mac-1",
        json={"device_name": "家里的 Mac"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["device_name"] == "家里的 Mac"

    removed = client.delete("/api/v1/browser-history/devices/mac-1")
    assert removed.status_code == 204

    devices = client.get("/api/v1/browser-history").json()["devices"]
    assert [item["device_id"] for item in devices] == ["win-2"]
    # Windows 的记录没被动。
    items = client.get("/api/v1/browser-history").json()["items"]
    assert [item["page_url"] for item in items] == ["https://public.example/b"]


def test_device_operations_reject_unknown_and_self_merge(
    client: TestClient,
) -> None:
    """未知设备返回 404，自己合并给自己返回 400。"""

    sync_from_device(client, "mac-1", "Mac", [visit_payload("https://public.example/a")])

    assert client.patch(
        "/api/v1/browser-history/devices/nope",
        json={"device_name": "x"},
    ).status_code == 404
    assert client.delete("/api/v1/browser-history/devices/nope").status_code == 404
    assert client.post(
        "/api/v1/browser-history/devices/mac-1/merge",
        json={"target_device_id": "mac-1"},
    ).status_code == 400


def test_device_cookie_survives_extension_reinstall(client: TestClient) -> None:
    """重装扩展后随机 ID 丢失，靠 Cookie 认回同一台设备。"""

    first = sync_with_identity(
        client,
        "original-id",
        "Mac",
        "fingerprint-1",
        "install-1",
        [visit_payload("https://public.example/a")],
    )
    assert first["device_id"] == "original-id"
    # 服务端下发 HttpOnly Cookie，扩展不需要 cookies 权限。
    cookie = client.cookies.get("memoisle_device")
    assert cookie == "original-id"

    # 重装：chrome.storage.local 清空，随机 ID 重新生成。
    second = sync_with_identity(
        client,
        "fresh-random-id",
        "Mac",
        "fingerprint-1",
        "install-1",
        [visit_payload("https://public.example/b")],
    )
    # Cookie 让它回到原来那台设备，而不是新建一台。
    assert second["device_id"] == "original-id"

    devices = client.get("/api/v1/browser-history").json()["devices"]
    assert [item["device_id"] for item in devices] == ["original-id"]
    items = client.get("/api/v1/browser-history").json()["items"]
    assert {item["page_url"] for item in items} == {
        "https://public.example/a",
        "https://public.example/b",
    }


def test_cookie_does_not_merge_a_different_extension_install(
    client: TestClient,
) -> None:
    """同一浏览器里的另一个扩展实例不该被 Cookie 吞掉。"""

    sync_with_identity(
        client,
        "first-install",
        "Chrome",
        "fingerprint-1",
        "install-1",
        [visit_payload("https://public.example/a")],
    )
    # 另一个安装：ID 未知、指纹也不同，说明是独立设备。
    forget_device_cookie(client)
    other = sync_with_identity(
        client,
        "second-install",
        "Chrome",
        "fingerprint-2",
        "install-2",
        [visit_payload("https://public.example/b")],
    )
    assert other["device_id"] == "second-install"
    devices = client.get("/api/v1/browser-history").json()["devices"]
    assert {item["device_id"] for item in devices} == {
        "first-install",
        "second-install",
    }

