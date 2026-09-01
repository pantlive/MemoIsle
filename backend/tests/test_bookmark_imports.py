"""Chrome 书签导入接口测试。"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from app.bookmark_service import (
    create_bookmark_batch,
    process_bookmark_batch,
    read_bookmark_batch,
    run_pending_bookmark_imports,
)
from app.models import BookmarkImportBatch, BookmarkImportItem, Memo
from app.schemas import BookmarkImportRequest
from fastapi.testclient import TestClient


def bookmark_payload() -> dict[str, list[dict[str, str]]]:
    """生成包含两条有效书签的结构化导入请求。"""

    return {
        "items": [
            {
                "client_item_id": "bookmark-1",
                "title": "PyTorch 入门教程",
                "url": "https://pytorch.org/tutorials/#start",
                "folder_path": "书签栏/学习/深度学习",
            },
            {
                "client_item_id": "bookmark-2",
                "title": "稍后阅读的文章",
                "url": "https://example.org/article?id=42",
                "folder_path": "书签栏/稍后阅读",
            },
        ]
    }


def test_bookmark_preview_reports_existing_file_duplicate_and_invalid(
    client: TestClient,
) -> None:
    """预览会同时识别已有资料、文件内重复与非法协议。"""

    existing = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "已经收藏",
            "body": "已有资料",
            "source_url": "https://example.com/docs",
        },
    ).json()
    response = client.post(
        "/api/v1/bookmark-imports/preview",
        json={
            "items": [
                {
                    "client_item_id": "existing",
                    "title": "已有链接的另一标题",
                    "url": "HTTPS://EXAMPLE.COM:443/docs#chapter",
                },
                {
                    "client_item_id": "new",
                    "title": "新链接",
                    "url": "https://new.example/path",
                },
                {
                    "client_item_id": "same-file",
                    "title": "文件内重复",
                    "url": "https://NEW.example/path#fragment",
                },
                {
                    "client_item_id": "invalid",
                    "title": "本地文件",
                    "url": "file:///private/bookmark.html",
                },
            ]
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total_count"] == 4
    assert result["valid_count"] == 1
    assert result["duplicate_count"] == 2
    assert result["invalid_count"] == 1
    assert result["items"][0]["existing_memo_id"] == existing["id"]
    assert result["items"][0]["error_code"] == "already_saved"
    assert result["items"][2]["error_code"] == "duplicate_in_file"
    assert result["items"][3]["status"] == "invalid"


def test_bookmark_batch_import_is_searchable_retryable_and_undoable(
    client: TestClient,
) -> None:
    """导入批次可查询进度、搜索、重试，并安全撤销未编辑项目。"""

    created_response = client.post(
        "/api/v1/bookmark-imports",
        json=bookmark_payload(),
    )
    assert created_response.status_code == 202
    batch_id = created_response.json()["id"]

    progress_response = client.get(f"/api/v1/bookmark-imports/{batch_id}")
    assert progress_response.status_code == 200
    progress = progress_response.json()
    assert progress["status"] == "completed"
    assert progress["imported_count"] == 2
    assert progress["failed_count"] == 0
    assert {item["status"] for item in progress["items"]} == {"imported"}

    search_response = client.get("/api/v1/memos", params={"q": "PyTorch 入门"})
    assert search_response.status_code == 200
    imported_memo = search_response.json()["items"][0]
    assert imported_memo["resource_import_folder"] == "书签栏/学习/深度学习"
    assert imported_memo["resource_import_batch_id"] == batch_id
    assert imported_memo["resource_category_status"] == "pending"

    # 模拟一次可恢复的项目失败，重试应关联幂等创建的原资料。
    database = client.app.state.database
    with database.session_factory() as session:
        item = session.get(BookmarkImportItem, progress["items"][0]["client_item_id"])
        if item is None:
            item = next(
                candidate
                for candidate in session.query(BookmarkImportItem).all()
                if candidate.batch_id == batch_id
            )
        item.status = "failed"
        item.error_code = "simulated_failure"
        session.commit()
    retry_response = client.post(f"/api/v1/bookmark-imports/{batch_id}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["failed_count"] == 0
    assert retry_response.json()["imported_count"] == 2

    # 显式编辑会让该资料脱离导入批次，因此撤销时必须保留。
    edited_response = client.patch(
        f"/api/v1/memos/{imported_memo['id']}",
        json={
            "expected_version": imported_memo["version"],
            "title": "我已整理的 PyTorch 教程",
        },
    )
    assert edited_response.status_code == 200
    assert edited_response.json()["resource_import_batch_id"] is None

    undo_response = client.post(f"/api/v1/bookmark-imports/{batch_id}/undo")
    assert undo_response.status_code == 200
    assert undo_response.json()["status"] == "undone"
    assert {item["status"] for item in undo_response.json()["items"]} == {
        "retained",
        "undone",
    }

    remaining_response = client.get("/api/v1/memos", params={"type": "resource"})
    remaining = remaining_response.json()["items"]
    assert [item["id"] for item in remaining] == [imported_memo["id"]]
    assert remaining[0]["title"] == "我已整理的 PyTorch 教程"


def test_pending_bookmark_batch_recovers_after_restart(client: TestClient) -> None:
    """服务重启后会恢复等待中和处理中项目，不让批次永久卡住。"""

    database = client.app.state.database
    settings = client.app.state.settings
    user_id = settings.local_user_id
    with database.session_factory() as session:
        batch = create_bookmark_batch(
            session,
            user_id,
            BookmarkImportRequest.model_validate(bookmark_payload()),
        )
        batch.status = "processing"
        first_item = next(
            item
            for item in session.query(BookmarkImportItem).all()
            if item.batch_id == batch.id
        )
        first_item.status = "processing"
        session.commit()
        batch_id = batch.id

    assert run_pending_bookmark_imports(settings.database_url, settings) == 1

    with database.session_factory() as session:
        recovered_batch = session.get(BookmarkImportBatch, batch_id)
        assert recovered_batch is not None
        assert recovered_batch.status == "completed"
        recovered = read_bookmark_batch(session, user_id, batch_id)
        assert recovered.imported_count == 2
        assert {item.status for item in recovered.items} == {"imported"}


def test_bookmark_import_finishes_before_metadata_enrichment(
    client: TestClient,
) -> None:
    """批量收藏先完成可搜索写入，联网元数据与分类留给后台队列。"""

    database = client.app.state.database
    settings = replace(
        client.app.state.settings,
        resource_enrichment_enabled=True,
    )
    user_id = settings.local_user_id
    with database.session_factory() as session:
        batch = create_bookmark_batch(
            session,
            user_id,
            BookmarkImportRequest.model_validate(bookmark_payload()),
        )
        processed = process_bookmark_batch(
            session,
            user_id,
            batch.id,
            settings,
        )
        imported_memos = list(
            session.query(Memo).filter(Memo.resource_import_batch_id == batch.id)
        )

    assert processed.status == "completed"
    assert processed.imported_count == 2
    assert len(imported_memos) == 2
    assert {memo.resource_metadata_status for memo in imported_memos} == {"pending"}
    assert {memo.resource_category_status for memo in imported_memos} == {"pending"}
