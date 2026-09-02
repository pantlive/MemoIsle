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


def test_create_is_idempotent(client: TestClient) -> None:
    """相同客户端标识重试不会生成重复条目。"""

    client_id = str(uuid4())
    first = create_idea(client, client_id)
    second = create_idea(client, client_id)
    assert second["id"] == first["id"]

    response = client.get("/api/v1/memos")
    assert len(response.json()["items"]) == 1


def test_resource_url_is_deduplicated_across_client_ids(client: TestClient) -> None:
    """不同入口提交相同规范网址时只保留一条网页资料。"""

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
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    resources = client.get(
        "/api/v1/memos",
        params={"type": "resource"},
    ).json()["items"]
    assert len(resources) == 1


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


def test_sync_cursor_only_returns_newer_changes(client: TestClient) -> None:
    """增量同步游标不会重复返回旧数据。"""

    create_idea(client)
    first_sync = client.get("/api/v1/sync/changes")
    assert first_sync.status_code == 200
    payload = first_sync.json()
    assert len(payload["items"]) == 1

    second_sync = client.get(
        "/api/v1/sync/changes",
        params={"cursor": payload["cursor"]},
    )
    assert second_sync.status_code == 200
    assert second_sync.json()["items"] == []


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
    assert [item["id"] for item in queue_response.json()["items"]] == [created["id"]]

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
    }


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
