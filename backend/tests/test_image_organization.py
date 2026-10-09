"""本地图片整理的队列、模板、隐私、重复组与并发保护。"""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.auth_service import create_dev_session
from app.image_ocr_service import OcrResult, OcrUnavailableError
from app.image_organization_service import process_image_job
from app.models import ImageOrganizationJob, Memo, ResourceCategoryTemplate
from app.resource_classification_quality import (
    empty_assessment,
    parse_jev_assessment,
)
from app.resource_processing import (
    CategoryDecision,
    ClassificationCategory,
    ResourceMetadata,
    classify_resource_with_jev,
)
from fastapi.testclient import TestClient
from PIL import Image

URL = "/api/v1/images/organization"


@pytest.fixture(autouse=True)
def pause_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试显式推进批次，避免后台处理真实图像或发送网络请求。"""

    async def idle(
        _database_url: str, _settings: object, stop_event: asyncio.Event
    ) -> None:
        """等待隔离应用关闭。"""

        await stop_event.wait()

    monkeypatch.setattr("app.main.image_organization_loop", idle)
    monkeypatch.setattr("app.main.resource_classification_loop", idle)


def seed_images(client: TestClient, count: int = 1, **changes: Any) -> list[str]:
    """建立带真实合成文件的图片记录，额外字段只作用于本次隔离数据。"""

    buffer = BytesIO()
    Image.new("RGB", (48, 24), "white").save(buffer, format="PNG")
    content = buffer.getvalue()
    image_hash = hashlib.sha256(content).hexdigest()
    directory = client.app.state.settings.image_directory
    directory.mkdir(parents=True, exist_ok=True)
    ids = [str(uuid4()) for _ in range(count)]
    with client.app.state.database.session_factory() as session:
        for index, memo_id in enumerate(ids):
            path = directory / f"{memo_id}.image"
            path.write_bytes(content)
            values: dict[str, Any] = dict(
                id=memo_id,
                user_id=client.app.state.settings.local_user_id,
                client_id=str(uuid4()),
                type="image",
                title=f"合成图片 {index}",
                body="不能发送的私人备注",
                image_storage_name=path.name,
                image_hash=image_hash,
                image_mime_type="image/png",
            )
            values.update(changes)
            session.add(Memo(**values))
        session.commit()
    return ids


def run_job(client: TestClient) -> dict[str, Any]:
    """直接驱动当前账号批次并返回公开进度。"""

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        process_image_job(session, settings.local_user_id, settings)
    return client.get(URL).json()["job"]


def configure_jev(client: TestClient) -> None:
    """只配置隔离测试的假密钥和中转地址。"""

    assert (
        client.put(
            "/api/v1/model-settings/jev",
            json={
                "model": "typesafe/jev",
                "api_key": "fake-image-key",
                "base_url": "https://fake.example/v1",
            },
        ).status_code
        == 200
    )


def decision(code: str = "learning") -> CategoryDecision:
    """通过正式解析器生成带证据的模板判断。"""

    selected, assessment = parse_jev_assessment(
        {"answers": {"category": {"choice": code, "confidence": 0.9}}},
        {code: "学习资料"},
        0.7,
        "typesafe/jev",
        True,
        "PyTorch 图片文字",
    )
    assessment["input_source"] = "image_ocr"
    return CategoryDecision(
        category=selected,
        category_label="学习资料",
        source="jev",
        confidence=0.9,
        auto_tags=(),
        assessment=assessment,
    )


def test_full_ocr_queue_is_durable_skips_ready_and_does_not_upload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全库批次不受分页限制，已识别图片不重跑，模型未配置也可本地识别。"""

    ids = seed_images(client, 211)
    seed_images(client, 2, image_ocr_status="ready", image_ocr_text="之前识别")
    seed_images(client, 1, status="trashed", deleted_at=datetime.now(UTC))
    calls: list[bytes] = []

    def ocr(content: bytes, model_path: Path) -> OcrResult:
        """确认仅调用本地识别接口。"""

        assert model_path.name == "ocr-models"
        calls.append(content)
        return OcrResult("PyTorch 笔记", ["PyTorch"], "local_pytorch")

    monkeypatch.setattr("app.image_organization_service.recognize_local_image", ocr)
    initial = client.post(URL, json={"action": "ocr", "scope": "all"})
    assert initial.status_code == 202 and initial.json()["job"]["total_count"] == 211
    assert (
        client.post(URL, json={"action": "ocr", "scope": "all"}).json()["job"]["id"]
        == initial.json()["job"]["id"]
    )
    client.app.state.database.create_schema()
    job = run_job(client)
    assert job["status"] == "completed" and job["succeeded_count"] == 211
    assert job["processed_count"] == 211 and len(calls) == 211
    row = client.get(f"/api/v1/memos/{ids[0]}").json()
    assert row["image_ocr_source"] == "local_pytorch" and row["version"] == 2
    assert (
        client.post(URL, json={"action": "ocr", "scope": "all"}).json()["job"][
            "total_count"
        ]
        == 0
    )
    run_job(client)
    assert len(calls) == 211


def test_image_jev_request_only_contains_ocr_title_and_template_paths() -> None:
    """真实序列化请求不含图像、链接或备注，使用自定义模板完整路径。"""

    def handler(request: httpx.Request) -> httpx.Response:
        """校验出站载荷，而不是只验证调用参数。"""

        body = json.loads(request.content)
        assert body["state"] == {
            "title": "合成课程截图",
            "image_ocr_text": "PyTorch 张量课程",
        }
        assert (
            body["questions"]["category"]["criteria"]["tensor"]["path"] == "学习 / 张量"
        )
        assert "private-note" not in request.content.decode()
        assert "private.example" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "answers": {
                    "category": {
                        "choice": "tensor",
                        "confidence": 0.9,
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        result = classify_resource_with_jev(
            ResourceMetadata(
                "https://private.example",
                "合成课程截图",
                "private-note",
                None,
                None,
                200,
                text_excerpt="PyTorch 张量课程",
            ),
            [ClassificationCategory("tensor", "张量", path="学习 / 张量")],
            "fake-key",
            "https://fake.example/v1",
            "typesafe/jev",
            0.7,
            transport,
            content_kind="image",
        )
    assert (
        result.category == "tensor" and result.assessment["input_source"] == "image_ocr"
    )


@pytest.mark.parametrize(
    "protection", ["manual", "user_rule", "jev", "assessment", "confirmed"]
)
def test_classification_protects_prior_results(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    protection: str,
) -> None:
    """已尝试、已确认或人工归类的图片不再次请求模型。"""

    configure_jev(client)
    changes: dict[str, Any] = {
        "resource_category": "article",
        "resource_categories": ["article"],
    }
    if protection == "assessment":
        changes["resource_ai_assessment"] = empty_assessment(
            "no_ocr_text",
            0.7,
            "typesafe/jev",
            False,
        )
    elif protection == "confirmed":
        changes["resource_ai_confirmation"] = {
            "action": "keep",
            "confirmed_at": datetime.now(UTC).isoformat(),
            "category_code": "article",
            "category_label": "文章阅读",
        }
    else:
        changes["resource_category_source"] = protection
    memo_id = seed_images(client, **changes)[0]

    def forbidden(*args: object, **kwargs: object) -> None:
        """保护记录不得触发识别或外部分类。"""

        pytest.fail("protected image was processed")

    monkeypatch.setattr(
        "app.image_organization_service.recognize_local_image", forbidden
    )
    monkeypatch.setattr(
        "app.image_organization_service.classify_resource_with_jev", forbidden
    )
    assert (
        client.post(URL, json={"action": "ocr_classify", "scope": "all"}).json()["job"][
            "total_count"
        ]
        == 0
    )
    client.post(
        URL,
        json={
            "action": "ocr_classify",
            "scope": "selected",
            "items": [
                {"memo_id": memo_id, "expected_version": 1},
            ],
        },
    )
    assert run_job(client)["skipped_count"] == 1
    assert (
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_category"] == "article"
    )


def test_combined_task_resume_reuses_saved_ocr_and_does_not_replay_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务错误暂停当前项，保存 OCR 并更新快照，继续只重试未完成判断。"""

    configure_jev(client)
    ids = seed_images(client, 2)
    ocr_calls: list[bytes] = []
    model_calls: list[str] = []

    def ocr(content: bytes, _path: Path) -> OcrResult:
        """记录真实识别次数。"""

        ocr_calls.append(content)
        return OcrResult("PyTorch 学习", [], "local_pytorch")

    def model(
        metadata: ResourceMetadata, *args: object, **kwargs: object
    ) -> CategoryDecision:
        """第一张成功，第二张一次失败后恢复。"""

        assert kwargs["content_kind"] == "image"
        model_calls.append(metadata.page_title)
        if len(model_calls) == 2:
            raise httpx.HTTPStatusError(
                "secret-token-private",
                request=httpx.Request("POST", "https://fake.example"),
                response=httpx.Response(401),
            )
        return decision()

    monkeypatch.setattr("app.image_organization_service.recognize_local_image", ocr)
    monkeypatch.setattr(
        "app.image_organization_service.classify_resource_with_jev", model
    )
    client.post(URL, json={"action": "ocr_classify", "scope": "all"})
    failed = run_job(client)
    assert failed["status"] == "failed" and failed["processed_count"] == 1
    assert "secret-token-private" not in failed["error"]
    assert len(ocr_calls) == 2 and len(model_calls) == 2
    assert client.post(f"{URL}/resume").status_code == 202
    completed = run_job(client)
    assert completed["succeeded_count"] == 2 and completed["status"] == "completed"
    assert len(ocr_calls) == 2 and len(model_calls) == 3
    assert model_calls[1] == model_calls[2] and model_calls[0] != model_calls[2]
    assert all(
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_ai_classified_at"]
        for memo_id in ids
    )
    assert (
        client.post(URL, json={"action": "ocr_classify", "scope": "all"}).json()["job"][
            "total_count"
        ]
        == 0
    )


@pytest.mark.parametrize("empty", [False, True])
def test_uncertain_or_no_text_preserves_category_and_is_not_reprocessed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    empty: bool,
) -> None:
    """低置信度与无文字图片保留原分类，并保存未确定证据避免反复调用。"""

    configure_jev(client)
    memo_id = seed_images(
        client, resource_category="article", resource_categories=["article"]
    )[0]
    monkeypatch.setattr(
        "app.image_organization_service.recognize_local_image",
        lambda *_: OcrResult("" if empty else "PyTorch", [], "local_pytorch"),
    )

    def uncertain(*args: object, **kwargs: object) -> None:
        """空文字不应请求模型，其他文字返回低置信度。"""

        assert not empty
        parse_jev_assessment(
            {"answers": {"category": {"choice": "learning", "confidence": 0.2}}},
            {"learning": "学习"},
            0.7,
            "typesafe/jev",
            True,
            "PyTorch",
        )

    monkeypatch.setattr(
        "app.image_organization_service.classify_resource_with_jev", uncertain
    )
    client.post(URL, json={"action": "ocr_classify", "scope": "all"})
    assert run_job(client)["failed_count"] == 1
    row = client.get(f"/api/v1/memos/{memo_id}").json()
    assert (
        row["resource_category"] == "article"
        and row["resource_ai_classified_at"] is None
    )
    assert row["resource_ai_assessment"]["reason_code"] == (
        "no_ocr_text" if empty else "low_confidence"
    )
    assert (
        client.post(URL, json={"action": "ocr_classify", "scope": "all"}).json()["job"][
            "total_count"
        ]
        == 0
    )


@pytest.mark.parametrize("change", ["edit", "trash", "replace", "lease"])
def test_late_ocr_result_cannot_override_changed_snapshot_or_lease(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """等待本地识别时其他会话可写入，旧 worker 不覆盖新版本或新租约。"""

    memo_id = seed_images(client)[0]

    def ocr(_content: bytes, _path: Path) -> OcrResult:
        """通过独立事务模拟真实并发，而不是改动同一会话对象。"""

        with client.app.state.database.session_factory() as session:
            memo = session.get(Memo, memo_id)
            if change == "lease":
                job = session.get(
                    ImageOrganizationJob, client.app.state.settings.local_user_id
                )
                job.worker_token = "another-worker"
            else:
                memo.version += 1
                if change == "trash":
                    memo.status = "trashed"
                    memo.deleted_at = datetime.now(UTC)
                elif change == "replace":
                    memo.image_hash = "new-content-hash"
                else:
                    memo.resource_category_source = "manual"
                    memo.resource_category = "article"
            session.commit()
        return OcrResult("迟到的 OCR", [], "local_pytorch")

    monkeypatch.setattr("app.image_organization_service.recognize_local_image", ocr)
    client.post(URL, json={"action": "ocr", "scope": "all"})
    job = run_job(client)
    assert job["processed_count"] == (0 if change == "lease" else 1)
    assert job["skipped_count"] == (0 if change == "lease" else 1)
    assert client.get(f"/api/v1/memos/{memo_id}").json()["image_ocr_text"] is None


@pytest.mark.parametrize("error_kind", ["unavailable", "unexpected", "missing_file"])
def test_ocr_failures_are_safe_and_continue_is_available(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error_kind: str,
) -> None:
    """模型缺失和未预期错误安全暂停，丢失文件逐项记失败，不泄露错误内容。"""

    memo_id = seed_images(client)[0]

    def failure(*args: object) -> None:
        """模拟错误内含凭据也不得返回给前端。"""

        error = OcrUnavailableError if error_kind == "unavailable" else RuntimeError
        raise error("private-test-key")

    monkeypatch.setattr("app.image_organization_service.recognize_local_image", failure)
    if error_kind == "missing_file":
        (client.app.state.settings.image_directory / f"{memo_id}.image").unlink()
    client.post(URL, json={"action": "ocr", "scope": "all"})
    job = run_job(client)
    assert "private-test-key" not in json.dumps(job)
    if error_kind == "missing_file":
        assert job["status"] == "completed" and job["failed_count"] == 1
    else:
        assert job["status"] == "failed" and job["processed_count"] == 0
        assert client.post(f"{URL}/resume").status_code == 202
        monkeypatch.setattr(
            "app.image_organization_service.recognize_local_image",
            lambda *_: OcrResult("已恢复", [], "local_pytorch"),
        )
        assert run_job(client)["succeeded_count"] == 1


def test_duplicate_groups_all_pages_and_account_isolation(client: TestClient) -> None:
    """大重复组完整分页，其他账号、回收站和无文件记录不混入。"""

    ids = seed_images(client, 63)
    seed_images(client, 2, status="trashed", deleted_at=datetime.now(UTC))
    seed_images(client, 2, user_id=str(uuid4()))
    groups = client.get("/api/v1/images/duplicates").json()
    assert groups["total_count"] == 1 and groups["groups"][0]["count"] == 63
    image_hash = groups["groups"][0]["image_hash"]
    assert len(groups["groups"][0]["items"]) == 50
    seen: set[str] = set()
    for offset in [0, 50]:
        page = client.get(
            f"/api/v1/images/duplicates/{image_hash}", params={"offset": offset}
        ).json()
        assert page["total_count"] == 63
        seen.update(row["id"] for row in page["items"])
    assert seen == set(ids)
    assert (
        client.get("/api/v1/images/duplicates", params={"limit": 21}).status_code == 422
    )
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    assert client.get(URL).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        client.get("/api/v1/images/duplicates", headers=headers).json()["total_count"]
        == 0
    )
    assert (
        client.get(f"/api/v1/images/duplicates/{image_hash}", headers=headers).json()[
            "items"
        ]
        == []
    )
    assert (
        client.post(
            URL,
            headers=headers,
            json={
                "action": "ocr",
                "scope": "selected",
                "items": [{"memo_id": ids[0], "expected_version": 1}],
            },
        ).json()["job"]["total_count"]
        == 0
    )


def test_image_replacement_clears_ai_but_preserves_manual_category(
    client: TestClient,
) -> None:
    """更换文件清除旧模型判断，人工模板分类仍保留。"""

    for source in ["jev", "manual"]:
        memo_id = seed_images(
            client,
            resource_category_source=source,
            resource_category="learning",
            resource_categories=["learning"],
            resource_ai_classified_at=datetime.now(UTC),
            resource_ai_assessment=decision().assessment,
        )[0]
        buffer = BytesIO()
        Image.new("RGB", (24, 12), "red").save(buffer, format="PNG")
        result = client.post(
            f"/api/v1/memos/{memo_id}/image",
            params={"expected_version": 1},
            headers={"Content-Type": "image/png"},
            content=buffer.getvalue(),
        ).json()
        assert (
            result["resource_ai_assessment"] is None
            and result["resource_ai_classified_at"] is None
        )
        assert result["resource_category"] == (
            "learning" if source == "manual" else None
        )
        if source == "manual":
            patched = client.patch(
                f"/api/v1/memos/{memo_id}",
                json={
                    "expected_version": result["version"],
                    "resource_categories": ["article"],
                },
            )
            assert (
                patched.status_code == 200
                and patched.json()["resource_category_source"] == "manual"
            )


def test_duplicate_groups_have_complete_group_pagination(client: TestClient) -> None:
    """重复组超过十组时，后续页面依然可见，且不会跨页重复。"""

    for index in range(13):
        seed_images(client, 2, image_hash=f"{index:064x}")
    groups = []
    for offset in (0, 10):
        page = client.get("/api/v1/images/duplicates", params={"offset": offset}).json()
        assert page["total_count"] == 13
        groups.extend(group["image_hash"] for group in page["groups"])
    assert len(groups) == len(set(groups)) == 13


def test_disabled_template_during_model_request_cannot_be_applied(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """等待模型时停用模板，保留 OCR 并暂停判断，绝不写入失效分类。"""

    configure_jev(client)
    category = client.post(
        "/api/v1/resource-categories", json={"name": "图片模板"}
    ).json()
    memo_id = seed_images(client)[0]
    monkeypatch.setattr(
        "app.image_organization_service.recognize_local_image",
        lambda *_: OcrResult("学习文字", [], "local_pytorch"),
    )

    def model(*args: object, **kwargs: object) -> CategoryDecision:
        """通过另一会话停用当前模型正在判断的模板。"""

        with client.app.state.database.session_factory() as session:
            session.get(ResourceCategoryTemplate, category["id"]).is_active = False
            session.commit()
        return decision(category["code"])

    monkeypatch.setattr(
        "app.image_organization_service.classify_resource_with_jev", model
    )
    client.post(URL, json={"action": "ocr_classify", "scope": "all"})
    assert run_job(client)["status"] == "failed"
    row = client.get(f"/api/v1/memos/{memo_id}").json()
    assert row["resource_category"] is None
    assert row["image_ocr_status"] == "ready"
    assert row["resource_ai_classified_at"] is None


def test_local_ocr_disables_gradients_and_downloads_and_reuses_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """校验推理边界和设备选择，运行时缺模型也不能偷偷联网下载。"""

    import easyocr
    import torch
    from app import image_local_ocr

    constructed = []

    class Reader:
        """模拟引擎只检查关键外部契约，不复制识别实现。"""

        def __init__(self, languages: list[str], **kwargs: Any) -> None:
            assert torch.is_inference_mode_enabled()
            assert languages == ["ch_sim", "en"]
            assert kwargs["download_enabled"] is False
            assert kwargs["gpu"] == (
                torch.cuda.is_available() or torch.backends.mps.is_available()
            )
            constructed.append(self)

        def readtext(self, content: bytes, **kwargs: Any) -> list[str]:
            """输入预览不得超过上限，不建立梯度图。"""

            assert torch.is_inference_mode_enabled()
            assert not torch.is_grad_enabled()
            image = Image.open(BytesIO(content))
            assert max(image.size) <= 2400
            return ["PyTorch 合成文本"]

    monkeypatch.setattr(easyocr, "Reader", Reader)
    monkeypatch.setattr(image_local_ocr, "_readers", {})
    buffer = BytesIO()
    Image.new("RGB", (2600, 100), "white").save(buffer, format="PNG")
    for _ in range(2):
        result = image_local_ocr.recognize_local_image(
            buffer.getvalue(), tmp_path / "models"
        )
        assert result.source == "local_pytorch"
    assert len(constructed) == 1
