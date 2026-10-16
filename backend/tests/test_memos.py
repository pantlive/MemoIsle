"""Memo API 行为测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.models import Memo
from fastapi.testclient import TestClient


def create_idea(client: TestClient, client_id: str | None = None) -> dict[str, object]:
    """创建一条测试灵感并返回响应数据。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": client_id or str(uuid4()),
            "type": "idea",
            "body": "在手机上快速记录灵感，再到网页继续整理。",
            "tags": ["产品", "产品", " MVP "],
        },
    )
    assert response.status_code == 201
    result: dict[str, object] = response.json()
    return result


def test_create_and_list_idea(client: TestClient) -> None:
    """创建后可在资料库中读取同一条内容。"""

    created = create_idea(client)
    assert created["title"] == "在手机上快速记录灵感，再到网页继续整理。"
    assert created["tags"] == ["产品", "MVP"]
    assert created["version"] == 1

    response = client.get("/api/v1/memos", params={"type": "idea"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == created["id"]


def test_export_json_contains_user_data_and_retained_trash(client: TestClient) -> None:
    """个人导出包含当前账号和保留期内的回收站条目。"""

    idea = create_idea(client)
    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "可导出的网页资料",
            "body": "导出测试正文",
            "source_url": "https://example.com/export",
        },
    )
    assert resource_response.status_code == 201
    resource = resource_response.json()
    trashed = client.delete(
        f"/api/v1/memos/{resource['id']}?expected_version={resource['version']}"
    )
    assert trashed.status_code == 200

    login_response = client.post("/api/v1/auth/dev-login")
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    response = client.get(
        "/api/v1/exports/json",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["format"] == "memoisle-json"
    assert payload["version"] == 1
    assert payload["audio_files_included"] is False
    assert payload["user"]["email"] is None
    exported_ids = {item["id"] for item in payload["memos"]}
    assert idea["id"] in exported_ids
    assert resource["id"] in exported_ids
    exported_resource = next(
        item for item in payload["memos"] if item["id"] == resource["id"]
    )
    assert exported_resource["status"] == "trashed"


def test_search_across_memo_types_and_fields(client: TestClient) -> None:
    """全局搜索覆盖三类内容的标题、释义、来源和标签。"""

    idea = create_idea(client)
    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "深度学习课程",
            "body": "稍后整理章节笔记。",
            "source_url": "https://example.com/neural-networks",
            "source_title": "Neural Networks Guide",
            "tags": ["资料库"],
        },
    )
    word_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "serendipity",
            "body": "偶然发现美好事物。",
            "word_meaning": "机缘巧合",
            "word_example": "A fortunate discovery.",
            "tags": ["英语生词"],
        },
    )
    assert resource_response.status_code == 201
    assert word_response.status_code == 201

    source_search = client.get("/api/v1/memos", params={"q": "NEURAL"})
    assert source_search.status_code == 200
    assert [item["id"] for item in source_search.json()["items"]] == [
        resource_response.json()["id"]
    ]

    meaning_search = client.get("/api/v1/memos", params={"q": "机缘巧合"})
    assert [item["id"] for item in meaning_search.json()["items"]] == [
        word_response.json()["id"]
    ]

    typed_search = client.get(
        "/api/v1/memos",
        params={"type": "idea", "q": "产品"},
    )
    assert [item["id"] for item in typed_search.json()["items"]] == [idea["id"]]


def test_search_treats_like_wildcards_as_plain_text(client: TestClient) -> None:
    """搜索中的百分号和下划线不应意外匹配任意内容。"""

    create_idea(client)
    percent_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "idea",
            "title": "进度达到 100%",
            "body": "测试通配符转义。",
        },
    )
    assert percent_response.status_code == 201

    search_response = client.get("/api/v1/memos", params={"q": "100%"})
    assert [item["id"] for item in search_response.json()["items"]] == [
        percent_response.json()["id"]
    ]


def test_search_matches_keywords_regardless_of_order(
    client: TestClient,
) -> None:
    """多个关键词按「与」匹配，词序不影响命中。"""

    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "React 教程：从入门到实践",
            "source_url": "https://example.com/react-guide",
        },
    )
    assert resource_response.status_code == 201
    resource_id = resource_response.json()["id"]

    forward = client.get("/api/v1/memos", params={"q": "react 教程"})
    assert [item["id"] for item in forward.json()["items"]] == [resource_id]

    backward = client.get("/api/v1/memos", params={"q": "教程 react"})
    assert [item["id"] for item in backward.json()["items"]] == [resource_id]

    missing = client.get("/api/v1/memos", params={"q": "react 不存在的词"})
    assert missing.json()["items"] == []


def test_search_splits_query_without_spaces(client: TestClient) -> None:
    """中英文连写时按边界拆分，仍能命中带空格或分隔符的标题。"""

    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "Rust 异步编程入门",
            "source_url": "https://example.com/rust-async",
        },
    )
    assert resource_response.status_code == 201
    resource_id = resource_response.json()["id"]

    compact = client.get(
        "/api/v1/memos",
        params={"type": "resource", "q": "Rust异步"},
    )
    assert [item["id"] for item in compact.json()["items"]] == [resource_id]

    separator = client.get(
        "/api/v1/memos",
        params={"type": "resource", "q": "Rust-异步"},
    )
    assert [item["id"] for item in separator.json()["items"]] == [resource_id]


def test_search_splits_query_for_resource_metadata(client: TestClient) -> None:
    """关键词可以分别命中标题、网址与描述等不同字段。"""

    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "分布式系统阅读笔记",
            "body": "记录一致性协议要点。",
            "source_url": "https://example.com/distributed-systems",
            "resource_site_name": "Example Docs",
        },
    )
    assert resource_response.status_code == 201
    resource_id = resource_response.json()["id"]

    cross_field = client.get(
        "/api/v1/memos",
        params={"q": "分布式 example"},
    )
    assert [item["id"] for item in cross_field.json()["items"]] == [resource_id]

    tags = client.get("/api/v1/memos", params={"q": "分布式 协议"})
    assert [item["id"] for item in tags.json()["items"]] == [resource_id]


def test_create_is_idempotent(client: TestClient) -> None:
    """相同客户端标识重试不会生成重复条目。"""

    client_id = str(uuid4())
    first = create_idea(client, client_id)
    second = create_idea(client, client_id)
    assert second["id"] == first["id"]

    response = client.get("/api/v1/memos")
    assert len(response.json()["items"]) == 1


def test_resource_url_duplicate_can_be_reviewed_or_forced(client: TestClient) -> None:
    """不同入口提交相同规范网址时先提示，确认后可以另存。"""

    first = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "第一条",
            "body": "网页备注",
            "source_url": "https://example.com/library",
        },
    )
    second = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "扩展再次收藏",
            "body": "另一个入口",
            "source_url": "HTTPS://EXAMPLE.COM:443/library#top",
        },
    )
    assert first.status_code == 201
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate_resource"
    assert detail["current"]["id"] == first.json()["id"]
    forced = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "仍然保存",
            "body": "保留不同语境",
            "source_url": "https://example.com/library",
            "allow_duplicate": True,
        },
    )
    assert forced.status_code == 201
    assert forced.json()["id"] != first.json()["id"]
    resources = client.get(
        "/api/v1/memos",
        params={"type": "resource"},
    ).json()["items"]
    assert len(resources) == 2


def test_update_requires_current_version(client: TestClient) -> None:
    """旧版本更新返回可恢复的服务端当前内容。"""

    created = create_idea(client)
    memo_id = created["id"]
    updated = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": 1,
            "body": "网页端已经补充了这条灵感。",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["title"] == "网页端已经补充了这条灵感。"

    conflict = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={"expected_version": 1, "body": "Android 的旧版本修改。"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["current"]["version"] == 2


def test_memo_type_conversion_preserves_common_fields(client: TestClient) -> None:
    """条目可转换类型，公共字段保留且不适用扩展字段会清理。"""

    idea = create_idea(client)
    missing_url = client.patch(
        f"/api/v1/memos/{idea['id']}",
        json={"expected_version": 1, "type": "resource"},
    )
    assert missing_url.status_code == 422

    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "可转换资料",
            "body": "转换后仍保留的备注",
            "source_url": "https://example.com/convert",
        },
    )
    assert resource_response.status_code == 201
    resource = resource_response.json()
    word_response = client.patch(
        f"/api/v1/memos/{resource['id']}",
        json={"expected_version": resource["version"], "type": "word"},
    )
    assert word_response.status_code == 200
    word = word_response.json()
    assert word["type"] == "word"
    assert word["title"] == resource["title"]
    assert word["body"] == resource["body"]
    assert word["source_url"] == resource["source_url"]
    assert word["word_meaning"] == resource["body"]
    assert word["resource_metadata_status"] == "none"

    idea_response = client.patch(
        f"/api/v1/memos/{word['id']}",
        json={"expected_version": word["version"], "type": "idea"},
    )
    assert idea_response.status_code == 200
    converted_idea = idea_response.json()
    assert converted_idea["type"] == "idea"
    assert converted_idea["source_url"] == resource["source_url"]
    assert converted_idea["word_meaning"] is None
    assert converted_idea["resource_metadata_status"] == "none"


def test_type_conversion_respects_word_duplicate_protection(client: TestClient) -> None:
    """转换为已有词形时仍然需要用户处理重复单词。"""

    existing = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "focus",
            "body": "专注",
        },
    )
    idea = create_idea(client)
    response = client.patch(
        f"/api/v1/memos/{idea['id']}",
        json={
            "expected_version": 1,
            "type": "word",
            "title": "FOCUS",
        },
    )
    assert existing.status_code == 201
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_lemma"


def test_sync_cursor_only_returns_newer_changes(client: TestClient) -> None:
    """增量同步游标不会重复返回旧数据。"""

    create_idea(client)
    first_sync = client.get("/api/v1/sync/changes")
    assert first_sync.status_code == 200
    payload = first_sync.json()
    assert len(payload["items"]) == 1
    assert payload["cursor_id"] == payload["items"][-1]["id"]

    second_sync = client.get(
        "/api/v1/sync/changes",
        params={
            "cursor": payload["cursor"],
            "cursor_id": payload["cursor_id"],
        },
    )
    assert second_sync.status_code == 200
    assert second_sync.json()["items"] == []


def test_sync_cursor_breaks_ties_with_memo_id(client: TestClient) -> None:
    """相同更新时间的分页不会因时间游标而漏掉条目。"""

    first_created = create_idea(client)
    second_created = create_idea(client)
    same_updated_at = datetime(2026, 9, 13, 12, tzinfo=UTC)
    with client.app.state.database.session_factory() as session:
        for memo_id in (first_created["id"], second_created["id"]):
            memo = session.get(Memo, memo_id)
            assert memo is not None
            memo.updated_at = same_updated_at
        session.commit()

    first_page = client.get(
        "/api/v1/sync/changes",
        params={"limit": 1},
    ).json()
    assert first_page["cursor_id"] == first_page["items"][0]["id"]

    second_page = client.get(
        "/api/v1/sync/changes",
        params={
            "cursor": first_page["cursor"],
            "cursor_id": first_page["cursor_id"],
            "limit": 1,
        },
    ).json()
    assert len(second_page["items"]) == 1
    assert second_page["items"][0]["id"] != first_page["items"][0]["id"]


def test_sync_includes_items_moved_to_trash(client: TestClient) -> None:
    """移入回收站的变更仍会同步，其他设备才能移除本地可见项。"""

    created = create_idea(client)
    first_sync = client.get("/api/v1/sync/changes").json()

    trashed_response = client.patch(
        f"/api/v1/memos/{created['id']}",
        json={"expected_version": 1, "status": "trashed"},
    )
    assert trashed_response.status_code == 200

    changes = client.get(
        "/api/v1/sync/changes",
        params={"cursor": first_sync["cursor"]},
    ).json()["items"]
    assert len(changes) == 1
    assert changes[0]["id"] == created["id"]
    assert changes[0]["status"] == "trashed"
    assert client.get("/api/v1/memos").json()["items"] == []


def test_combined_filters_and_sorting(client: TestClient) -> None:
    """类型、分类、标签、状态、日期与排序可以组合使用。"""

    created_ids: list[str] = []
    for title, tag in (
        ("Alpha 课程", "课程"),
        ("Beta 课程", "其他"),
        ("Gamma 文章", "课程笔记"),
    ):
        response = client.post(
            "/api/v1/memos",
            json={
                "client_id": str(uuid4()),
                "type": "resource",
                "title": title,
                "body": "筛选测试",
                "source_url": f"https://example.com/{title.split()[0].lower()}",
                "tags": [tag],
            },
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    database = client.app.state.database
    with database.session_factory() as session:
        alpha = session.get(Memo, created_ids[0])
        beta = session.get(Memo, created_ids[1])
        gamma = session.get(Memo, created_ids[2])
        assert alpha is not None and beta is not None and gamma is not None
        alpha.resource_category = "learning"
        alpha.link_health_status = "healthy"
        alpha.created_at = datetime(2026, 9, 1, 8, tzinfo=UTC)
        beta.resource_category = "learning"
        beta.resource_auto_tags = ["课程"]
        beta.link_health_status = "changed"
        beta.created_at = datetime(2026, 9, 2, 8, tzinfo=UTC)
        gamma.resource_category = "article"
        gamma.status = "archived"
        gamma.created_at = datetime(2026, 9, 3, 8, tzinfo=UTC)
        session.commit()

    response = client.get(
        "/api/v1/memos",
        params={
            "type": "resource",
            "category": "learning",
            "tag": "课程",
            "status": "active",
            "created_from": "2026-09-01",
            "created_to": "2026-09-02",
            "sort": "title_desc",
        },
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        created_ids[1],
        created_ids[0],
    ]

    health_response = client.get(
        "/api/v1/memos",
        params={"health": "changed"},
    )
    assert health_response.status_code == 200
    assert [item["id"] for item in health_response.json()["items"]] == [
        created_ids[1]
    ]


def test_list_limit_keeps_newest_items_and_sync_keeps_oldest_first(
    client: TestClient,
) -> None:
    """列表截断前按最新排序，增量同步仍按时间正序返回。"""

    created_ids: list[str] = []
    for index in range(3):
        response = client.post(
            "/api/v1/memos",
            json={
                "client_id": str(uuid4()),
                "type": "idea",
                "title": f"排序验证 {index}",
                "body": f"排序验证正文 {index}",
            },
        )
        assert response.status_code == 201
        created_ids.append(response.json()["id"])

    list_response = client.get("/api/v1/memos", params={"limit": 2})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == list(
        reversed(created_ids[-2:])
    )

    sync_response = client.get("/api/v1/sync/changes", params={"limit": 2})
    assert sync_response.status_code == 200
    assert [item["id"] for item in sync_response.json()["items"]] == created_ids[:2]


def test_create_update_and_list_resource(client: TestClient) -> None:
    """网页资料保存原始链接，并支持按类型读取和编辑。"""

    created_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "PyTorch 官方教程",
            "body": "稍后学习张量基础。",
            "source_url": "https://pytorch.org/tutorials/",
            "source_title": "PyTorch Tutorials",
            "tags": ["学习资料"],
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["source_url"] == "https://pytorch.org/tutorials/"
    assert created["source_title"] == "PyTorch Tutorials"
    assert created["resource_kind"] == "other"
    assert created["resource_reading_status"] == "unread"
    assert created["collections"] == []
    assert created["starred"] is False


def test_create_resource_truncates_long_browser_title(client: TestClient) -> None:
    """浏览器原生标题超过 200 字时截断保存，而不是返回 422。"""

    long_title = "用户中心 - " + ("丽萨主机," * 40)
    assert len(long_title) > 200
    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "body": "https://lisahost.com/clientarea.php",
            "source_url": "https://lisahost.com/clientarea.php",
            "source_title": long_title,
            "tags": [],
        },
    )
    assert response.status_code == 201, response.json()
    created = response.json()
    assert created["source_title"] == long_title[:200]
    assert created["title"] == long_title[:200]

    list_response = client.get("/api/v1/memos", params={"type": "resource"})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [created["id"]]

    updated_response = client.patch(
        f"/api/v1/memos/{created['id']}",
        json={
            "expected_version": 1,
            "title": "PyTorch 学习资料",
            "body": "优先阅读入门教程。",
            "source_url": "https://pytorch.org/tutorials/beginner/basics/intro.html",
            "resource_kind": "course",
            "resource_reading_status": "reading",
            "collections": ["深度学习", "课程"],
            "starred": True,
        },
    )
    assert updated_response.status_code == 200
    assert updated_response.json()["version"] == 2
    assert updated_response.json()["title"] == "PyTorch 学习资料"
    assert updated_response.json()["resource_kind"] == "course"
    assert updated_response.json()["resource_reading_status"] == "reading"
    assert updated_response.json()["collections"] == ["深度学习", "课程"]
    assert updated_response.json()["starred"] is True

    filtered_response = client.get(
        "/api/v1/memos",
        params={
            "resource_kind": "course",
            "reading_status": "reading",
            "collection": "深度学习",
            "starred": "true",
        },
    )
    assert filtered_response.status_code == 200
    assert [item["id"] for item in filtered_response.json()["items"]] == [
        created["id"]
    ]


def test_resource_rejects_unsafe_or_missing_url(client: TestClient) -> None:
    """网页资料必须使用明确的 HTTP(S) 来源地址。"""

    missing_url = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "body": "缺少链接",
        },
    )
    assert missing_url.status_code == 422

    unsafe_url = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "body": "本地文件",
            "source_url": "file:///tmp/private.txt",
        },
    )
    assert unsafe_url.status_code == 422


def test_create_word_and_submit_review(client: TestClient) -> None:
    """单词可进入到期队列，并根据反馈更新复习计划。"""

    created_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "serendipity",
            "body": "意外发现美好事物的能力",
            "word_phonetic": "/ˌserənˈdɪpəti/",
            "word_meaning": "机缘巧合；意外发现珍奇事物的本领",
            "word_example": "We found the book by serendipity.",
            "tags": ["英语"],
        },
    )
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["familiarity"] == 0
    assert created["review_count"] == 0

    queue_response = client.get("/api/v1/review-queue")
    assert queue_response.status_code == 200
    queue = queue_response.json()
    assert [item["id"] for item in queue["items"]] == [created["id"]]
    assert queue["word_count"] == 1
    assert queue["resource_count"] == 0
    assert queue["idea_count"] == 0

    review_response = client.post(
        f"/api/v1/words/{created['id']}/reviews",
        json={"expected_version": 1, "feedback": "remembered"},
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["version"] == 2
    assert reviewed["familiarity"] == 1
    assert reviewed["review_count"] == 1
    assert reviewed["last_review_at"].endswith("Z")

    empty_queue = client.get("/api/v1/review-queue")
    assert empty_queue.json()["items"] == []
    assert empty_queue.json()["word_count"] == 0


def test_duplicate_word_lemma_can_merge_or_force_create(client: TestClient) -> None:
    """相同词形默认视为重复，可合并例句或仍然分别保存。"""

    first = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "Serendipity",
            "body": "机缘巧合",
            "word_meaning": "机缘巧合",
            "word_example": "We found the book by serendipity.",
        },
    )
    assert first.status_code == 201
    created = first.json()

    duplicate = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "serendipity",
            "body": "意外发现",
            "word_meaning": "意外发现珍奇事物的本领",
            "word_example": "A fortunate accident.",
        },
    )
    assert duplicate.status_code == 409
    detail = duplicate.json()["detail"]
    assert detail["code"] == "duplicate_lemma"
    assert detail["current"]["id"] == created["id"]

    merged = client.post(
        f"/api/v1/words/{created['id']}/merge",
        json={
            "expected_version": created["version"],
            "word_meaning": "意外发现珍奇事物的本领",
            "word_example": "A fortunate accident.",
        },
    )
    assert merged.status_code == 200
    merged_word = merged.json()
    assert "机缘巧合" in merged_word["word_meaning"]
    assert "A fortunate accident." in merged_word["word_example"]

    forced = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "serendipity",
            "body": "另一个语境",
            "allow_duplicate": True,
        },
    )
    assert forced.status_code == 201
    assert forced.json()["id"] != created["id"]

    unique = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "ephemeral",
            "body": "短暂的",
        },
    )
    assert unique.status_code == 201
    trashed = client.patch(
        f"/api/v1/memos/{unique.json()['id']}",
        json={"expected_version": unique.json()["version"], "status": "trashed"},
    )
    assert trashed.status_code == 200
    after_trash = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "EPHEMERAL",
            "body": "回收站后可再收藏",
        },
    )
    assert after_trash.status_code == 201


def test_today_review_mixes_types_and_allows_skip(client: TestClient) -> None:
    """今日回顾混合到期单词、未读资料和待整理灵感，跳过后当天不再出现。"""

    word_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "ephemeral",
            "body": "短暂的",
        },
    )
    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "body": "待读资料",
            "source_url": "https://example.com/review-item",
        },
    )
    idea = create_idea(client)
    assert word_response.status_code == 201
    assert resource_response.status_code == 201
    assert idea["status"] == "inbox"

    queue = client.get("/api/v1/review-queue").json()
    assert queue["word_count"] == 1
    assert queue["resource_count"] == 1
    assert queue["idea_count"] == 1
    assert [item["type"] for item in queue["items"]] == ["word", "resource", "idea"]

    first = queue["items"][0]
    skip_response = client.post(
        f"/api/v1/review-queue/{first['id']}/skip",
        json={"expected_version": first["version"]},
    )
    assert skip_response.status_code == 200
    remaining = client.get("/api/v1/review-queue").json()
    assert first["id"] not in [item["id"] for item in remaining["items"]]
    assert remaining["word_count"] == 0

    idea_queue = client.get("/api/v1/review-queue", params={"type": "idea"}).json()
    assert [item["id"] for item in idea_queue["items"]] == [idea["id"]]
    organized = client.patch(
        f"/api/v1/memos/{idea['id']}",
        json={"expected_version": idea["version"], "status": "active"},
    )
    assert organized.status_code == 200
    after_organize = client.get("/api/v1/review-queue", params={"type": "idea"}).json()
    assert after_organize["items"] == []
    assert after_organize["idea_count"] == 0


def test_memo_counts_include_current_resource_total(client: TestClient) -> None:
    """类型数量接口返回未删除网页资料的真实总数。"""

    for memo_type, body in (
        ("resource", "网页资料"),
        ("resource", "另一条网页资料"),
        ("idea", "一条灵感"),
    ):
        payload = {
            "client_id": str(uuid4()),
            "type": memo_type,
            "body": body,
            "source_url": "https://example.com/" + str(uuid4())
            if memo_type == "resource"
            else None,
            "tags": [],
        }
        response = client.post("/api/v1/memos", json=payload)
        assert response.status_code == 201

    counts_response = client.get("/api/v1/memos/counts")
    assert counts_response.status_code == 200
    assert counts_response.json() == {
        "total_count": 3,
        "word_count": 0,
        "resource_count": 2,
        "idea_count": 1,
        "image_count": 0,
        "inbox_count": 1,
    }


def test_inbox_list_returns_unorganized_ideas(client: TestClient) -> None:
    """收件箱列表只返回 inbox 状态条目，整理后不再出现。"""

    idea = create_idea(client)
    organized = create_idea(client)
    client.patch(
        f"/api/v1/memos/{organized['id']}",
        json={"expected_version": organized["version"], "status": "active"},
    )
    client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "keep-out",
            "body": "不应出现在收件箱",
        },
    )

    inbox = client.get("/api/v1/memos", params={"status": "inbox"})
    assert inbox.status_code == 200
    payload = inbox.json()
    assert payload["total_count"] == 1
    assert [item["id"] for item in payload["items"]] == [idea["id"]]
    assert payload["items"][0]["status"] == "inbox"

    counts = client.get("/api/v1/memos/counts").json()
    assert counts["inbox_count"] == 1

    client.patch(
        f"/api/v1/memos/{idea['id']}",
        json={"expected_version": idea["version"], "status": "active"},
    )
    after = client.get("/api/v1/memos", params={"status": "inbox"}).json()
    assert after["items"] == []
    assert after["total_count"] == 0
    assert client.get("/api/v1/memos/counts").json()["inbox_count"] == 0


def test_memo_list_returns_total_for_filters(client: TestClient) -> None:
    """列表接口返回筛选条件匹配的真实总数，而不是分页数量。"""

    for index in range(3):
        response = client.post(
            "/api/v1/memos",
            json={
                "client_id": str(uuid4()),
                "type": "resource",
                "body": f"资料 {index}",
                "source_url": f"https://example.com/resource-{index}",
                "tags": [],
                "starred": index == 0,
            },
        )
        assert response.status_code == 201

    response = client.get(
        "/api/v1/memos",
        params={"type": "resource", "starred": "true", "limit": 1},
    )
    assert response.status_code == 200
    assert response.json()["total_count"] == 1
    assert len(response.json()["items"]) == 1


def test_memo_list_supports_resource_pagination(client: TestClient) -> None:
    """网页资料列表支持偏移分页，同时保留筛选总数。"""

    for index in range(3):
        response = client.post(
            "/api/v1/memos",
            json={
                "client_id": str(uuid4()),
                "type": "resource",
                "body": f"分页资料 {index}",
                "source_url": f"https://example.com/page-{index}",
                "tags": [],
            },
        )
        assert response.status_code == 201

    first_page = client.get(
        "/api/v1/memos",
        params={"type": "resource", "limit": 1, "offset": 0},
    )
    second_page = client.get(
        "/api/v1/memos",
        params={"type": "resource", "limit": 1, "offset": 1},
    )
    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["total_count"] == 3
    assert second_page.json()["total_count"] == 3
    assert len(first_page.json()["items"]) == 1
    assert len(second_page.json()["items"]) == 1
    first_item_id = first_page.json()["items"][0]["id"]
    second_item_id = second_page.json()["items"][0]["id"]
    assert first_item_id != second_item_id


def test_word_requires_lemma_and_non_word_cannot_be_reviewed(
    client: TestClient,
) -> None:
    """单词必须有词形，其他内容不能进入单词复习流程。"""

    missing_lemma = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "body": "缺少词形",
        },
    )
    assert missing_lemma.status_code == 422

    idea = create_idea(client)
    invalid_review = client.post(
        f"/api/v1/words/{idea['id']}/reviews",
        json={"expected_version": 1, "feedback": "fuzzy"},
    )
    assert invalid_review.status_code == 422


def test_upload_and_download_idea_audio(client: TestClient) -> None:
    """语音灵感可上传原始音频并再次读取。"""

    idea = create_idea(client)
    audio_content = b"webm-test-audio"
    upload_response = client.post(
        f"/api/v1/memos/{idea['id']}/audio",
        params={"expected_version": 1},
        content=audio_content,
        headers={
            "Content-Type": "audio/webm",
            "X-Audio-Duration-Ms": "1350",
        },
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()
    assert uploaded["audio_mime_type"] == "audio/webm"
    assert uploaded["audio_size_bytes"] == len(audio_content)
    assert uploaded["audio_duration_ms"] == 1350
    assert uploaded["version"] == 2

    download_response = client.get(f"/api/v1/memos/{idea['id']}/audio")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "audio/webm"
    assert download_response.content == audio_content


def test_upload_meeting_audio_preserves_transcript(client: TestClient) -> None:
    """会议纪要正文与转写字段可以分别保存，上传音频不会覆盖转写。"""

    created_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "idea",
            "title": "产品周会",
            "body": "会议概要：确认上线时间。",
            "transcript": "主持人：我们先确认上线时间。",
            "tags": ["会议"],
        },
    )
    assert created_response.status_code == 201
    meeting = created_response.json()
    assert meeting["transcript"] == "主持人：我们先确认上线时间。"

    upload_response = client.post(
        f"/api/v1/memos/{meeting['id']}/audio",
        params={"expected_version": meeting["version"]},
        content=b"meeting-audio",
        headers={
            "Content-Type": "audio/mp4",
            "X-Audio-Duration-Ms": "120000",
        },
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()
    assert uploaded["body"] == "会议概要：确认上线时间。"
    assert uploaded["transcript"] == "主持人：我们先确认上线时间。"
    assert uploaded["transcript_status"] == "manual"


def test_audio_rejects_wrong_memo_type_and_format(client: TestClient) -> None:
    """音频上传只允许灵感和受支持的音频格式。"""

    word_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "voice",
            "body": "声音",
        },
    )
    word = word_response.json()
    wrong_type = client.post(
        f"/api/v1/memos/{word['id']}/audio",
        params={"expected_version": 1},
        content=b"audio",
        headers={"Content-Type": "audio/webm"},
    )
    assert wrong_type.status_code == 422

    idea = create_idea(client)
    wrong_format = client.post(
        f"/api/v1/memos/{idea['id']}/audio",
        params={"expected_version": 1},
        content=b"not-audio",
        headers={"Content-Type": "text/plain"},
    )
    assert wrong_format.status_code == 422
