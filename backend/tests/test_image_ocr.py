"""图片 OCR 与自动标签测试。"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.database import Database
from app.image_ocr_service import (
    OcrNotConfiguredError,
    OcrResult,
    OcrUnavailableError,
    build_ocr_preview,
    derive_tags_from_text,
    extract_text_and_tags_llm,
    merge_tags,
    normalize_ocr_text,
    parse_ocr_payload,
    reset_image_ocr_fields,
    run_image_ocr,
)
from app.image_ocr_service import (
    extract_text_local as real_extract_text_local,
)
from app.main import create_app
from app.models import Memo
from fastapi.testclient import TestClient
from PIL import Image


def png_bytes(width: int = 64, height: int = 32) -> bytes:
    """生成一张用于测试的 PNG。"""

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "#336699").save(buffer, format="PNG")
    return buffer.getvalue()


def base_settings(**overrides: object) -> Settings:
    """构造一份最小可用配置，允许覆盖 OCR 相关字段。"""

    values: dict[str, object] = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "cors_origins": ("http://localhost:5173",),
        "local_user_id": "00000000-0000-0000-0000-000000000001",
        "auth_dev_mode": True,
        "auth_token_secret": "test-auth-token-secret",
        "audio_directory": Path("/tmp/memoisle-test-audio"),
        "image_directory": Path("/tmp/memoisle-test-images"),
        "resource_enrichment_enabled": False,
        "resource_health_monitor_enabled": False,
        "word_dictionary_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def build_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    local=None,
    llm=None,
    **overrides: object,
) -> TestClient:
    """构建启用指定 OCR 渠道的测试客户端，并替换识别器避免真实依赖。"""

    from app import image_ocr_service

    settings = base_settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        image_directory=tmp_path / "images",
        audio_directory=tmp_path / "audio",
        image_ocr_provider=provider,
        **overrides,
    )
    if local is not None:
        monkeypatch.setattr(image_ocr_service, "extract_text_local", local)
    if llm is not None:
        monkeypatch.setattr(image_ocr_service, "extract_text_and_tags_llm", llm)
    app = create_app(settings=settings, database=Database(settings.database_url))
    return TestClient(app)


def create_image_memo(client: TestClient, title: str = "测试图片") -> dict:
    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "image",
            "title": title,
            "body": "",
        },
    )
    assert response.status_code == 201
    return response.json()


def upload_image(
    client: TestClient,
    memo_id: str,
    content: bytes | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/memos/{memo_id}/image",
        params={"expected_version": 1},
        headers={"Content-Type": "image/png"},
        content=content if content is not None else png_bytes(),
    )
    assert response.status_code == 200
    return response.json()


def fetch_memo(client: TestClient, memo_id: str) -> dict:
    """上传响应在后台识别前就已生成，需要重新读取才能看到 OCR 结果。"""

    response = client.get(f"/api/v1/memos/{memo_id}")
    assert response.status_code == 200
    return response.json()


# ---------- 纯函数 ----------


def test_parse_ocr_payload_handles_json_fence_and_plain_text() -> None:
    """模型返回 JSON、代码块或纯文本时都能解析。"""

    text, tags = parse_ocr_payload('{"text": "营业时间", "tags": ["咖啡", "营业时间"]}')
    assert text == "营业时间"
    assert tags == ["咖啡", "营业时间"]

    fenced_text, fenced_tags = parse_ocr_payload(
        '```json\n{"text": "菜单", "tags": ["午餐"]}\n```',
    )
    assert fenced_text == "菜单"
    assert fenced_tags == ["午餐"]

    plain_text, plain_tags = parse_ocr_payload("这是一段没有 JSON 的识别结果")
    assert plain_text == "这是一段没有 JSON 的识别结果"
    assert plain_tags == []

    assert parse_ocr_payload("") == ("", [])


def test_normalize_ocr_text_strips_control_characters_and_limits_length() -> None:
    """OCR 文本去掉控制字符、空行，并限制最大长度。"""

    assert normalize_ocr_text("a\u0000b\n\n\n c ") == "ab\nc"
    assert len(normalize_ocr_text("字" * 9_000)) == 5_000


def test_derive_tags_from_text_uses_latin_frequency_and_cjk_runs() -> None:
    """本地兜底标签：英文按词频、中文按短语，过滤停用词。"""

    text = "PyTorch pytorch tutorial the and for 学习笔记 学习笔记 深度学习框架 README"
    tags = derive_tags_from_text(text, 6)
    assert "pytorch" in tags
    assert "学习笔记" in tags
    assert "the" not in tags
    assert "and" not in tags
    assert len(tags) <= 6


def test_derive_tags_from_text_handles_long_cjk_runs_and_empty_input() -> None:
    """没有分词器时用 4 字窗口，空文本返回空标签。"""

    tags = derive_tags_from_text("今天天气很好适合出门散步", 5)
    assert tags
    assert all(len(tag) == 4 for tag in tags)
    assert derive_tags_from_text("", 5) == []
    assert derive_tags_from_text("text", 0) == []


def test_merge_tags_prefers_model_tags_and_dedupes() -> None:
    """模型标签优先，本地标签去重补位。"""

    merged = merge_tags(["咖啡", "Coffee"], ["coffee", "营业时间"], 5)
    assert merged == ["咖啡", "Coffee", "营业时间"]


def test_build_ocr_preview_scales_and_reencodes() -> None:
    """发给视觉模型的预览图会缩放并转成 JPEG。"""

    preview = build_ocr_preview(png_bytes(1200, 300), 400)
    with Image.open(io.BytesIO(preview)) as image:
        assert image.format == "JPEG"
        assert max(image.size) == 400


def test_reset_image_ocr_fields_clears_state() -> None:
    """重新上传图片时需要清空旧识别结果。"""

    memo = Memo(
        image_ocr_text="旧文字",
        image_ocr_status="ready",
        image_ocr_error="旧错误",
        image_ocr_source="local",
        image_auto_tags=["旧标签"],
    )
    reset_image_ocr_fields(memo)
    assert memo.image_ocr_text is None
    assert memo.image_ocr_status == "none"
    assert memo.image_ocr_error is None
    assert memo.image_ocr_source is None
    assert memo.image_auto_tags == []
    assert memo.image_ocr_updated_at is None


# ---------- 渠道选择 ----------


def test_run_image_ocr_requires_enabled_provider() -> None:
    with pytest.raises(OcrNotConfiguredError):
        run_image_ocr(
            base_settings(image_ocr_provider="none"),
            png_bytes(),
            "image/png",
        )


def test_run_image_ocr_local_provider_derives_tags() -> None:
    """local 渠道只用本地引擎，并从识别文本生成标签。"""

    result = run_image_ocr(
        base_settings(image_ocr_provider="local"),
        png_bytes(),
        "image/png",
        local_extractor=lambda _bytes, _languages: "星巴克 营业时间 咖啡",
    )
    assert result.source == "local"
    assert "营业时间" in result.text
    assert any("咖啡" in tag or "营业时间" in tag for tag in result.tags)


def test_run_image_ocr_llm_provider_merges_model_and_local_tags() -> None:
    """llm 渠道保留模型标签，并合并本地关键词。"""

    def fake_llm(_settings: Settings, _bytes: bytes, _mime: str) -> OcrResult:
        return OcrResult(
            text="Quarterly OKR review",
            tags=["OKR", "会议"],
            source="llm",
        )

    result = run_image_ocr(
        base_settings(
            image_ocr_provider="llm",
            llm_base_url="http://llm.test/v1",
            image_ocr_vision_model="vision-1",
        ),
        png_bytes(),
        "image/png",
        llm_extractor=fake_llm,
    )
    assert result.source == "llm"
    assert result.tags[0] == "OKR"
    assert "会议" in result.tags
    assert "quarterly" in result.tags


def test_run_image_ocr_auto_falls_back_to_llm_when_local_unavailable() -> None:
    """auto 渠道在本地引擎不可用时回退视觉模型。"""

    def unavailable(_bytes: bytes, _languages: str) -> str:
        raise OcrUnavailableError("未安装本地 OCR 依赖")

    def fake_llm(_settings: Settings, _bytes: bytes, _mime: str) -> OcrResult:
        return OcrResult(text="白板内容", tags=["白板"], source="llm")

    result = run_image_ocr(
        base_settings(image_ocr_provider="auto", llm_base_url="http://llm.test/v1"),
        png_bytes(),
        "image/png",
        local_extractor=unavailable,
        llm_extractor=fake_llm,
    )
    assert result.source == "llm"
    assert result.text == "白板内容"


def test_run_image_ocr_auto_keeps_local_result_when_llm_not_configured() -> None:
    """auto 渠道本地可用但没识别到文字时，不因为没有视觉模型而失败。"""

    def not_configured(_settings: Settings, _bytes: bytes, _mime: str) -> OcrResult:
        raise OcrNotConfiguredError("未配置视觉模型")

    result = run_image_ocr(
        base_settings(image_ocr_provider="auto"),
        png_bytes(),
        "image/png",
        local_extractor=lambda _bytes, _languages: "   ",
        llm_extractor=not_configured,
    )
    assert result.source == "local"
    assert result.text == ""
    assert result.tags == []


def test_run_image_ocr_local_provider_reports_unavailable() -> None:
    """local 渠道且本地引擎不可用时抛出可用性错误。"""

    def unavailable(_bytes: bytes, _languages: str) -> str:
        raise OcrUnavailableError("未安装本地 OCR 依赖")

    with pytest.raises(OcrUnavailableError):
        run_image_ocr(
            base_settings(image_ocr_provider="local"),
            png_bytes(),
            "image/png",
            local_extractor=unavailable,
        )


def test_llm_extractor_builds_vision_request() -> None:
    """视觉模型请求包含 data URL 图片与 Bearer 头。"""

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"text": "咖啡", "tags": ["咖啡"]}'}},
                ],
            },
        )

    settings = base_settings(
        llm_base_url="http://llm.test/v1",
        llm_api_key="secret",
        image_ocr_vision_model="vision-1",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = extract_text_and_tags_llm(settings, png_bytes(), "image/png", client)

    assert result.text == "咖啡"
    assert result.tags == ["咖啡"]
    assert str(captured["url"]).endswith("/chat/completions")
    assert captured["authorization"] == "Bearer secret"
    payload = captured["payload"]
    assert payload["model"] == "vision-1"  # type: ignore[index]
    content = payload["messages"][1]["content"]  # type: ignore[index]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_llm_extractor_requires_configuration() -> None:
    """没有配置服务地址时抛出未配置错误。"""

    with pytest.raises(OcrNotConfiguredError):
        extract_text_and_tags_llm(base_settings(), png_bytes(), "image/png")


def test_real_local_extractor_reports_missing_dependency() -> None:
    """没有安装任何本地 OCR 依赖时给出明确错误，而不是静默返回空文本。"""

    if importlib.util.find_spec("rapidocr_onnxruntime") is not None:
        pytest.skip("已安装 rapidocr-onnxruntime，跳过缺失依赖断言")
    if importlib.util.find_spec("pytesseract") is not None:
        pytest.skip("已安装 pytesseract，跳过缺失依赖断言")
    with pytest.raises(OcrUnavailableError):
        real_extract_text_local(png_bytes(), "eng")


# ---------- 接口与后台任务 ----------


def test_upload_runs_local_ocr_and_indexes_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上传后在后台完成本地识别，文字和标签可被搜索命中。"""

    with build_client(
        tmp_path,
        monkeypatch,
        provider="local",
        local=lambda _bytes, _languages: "星巴克 营业时间 07:00-22:00 咖啡",
    ) as client:
        created = create_image_memo(client, "咖啡店招牌")
        pending = upload_image(client, str(created["id"]))
        assert pending["image_ocr_status"] == "pending"

        processed = fetch_memo(client, str(created["id"]))
        assert processed["image_ocr_status"] == "ready"
        assert processed["image_ocr_source"] == "local"
        assert "营业时间" in processed["image_ocr_text"]
        assert processed["image_auto_tags"]
        assert processed["image_ocr_updated_at"].endswith("Z")

        by_text = client.get("/api/v1/memos", params={"q": "营业时间"})
        assert [item["id"] for item in by_text.json()["items"]] == [created["id"]]

        tag = processed["image_auto_tags"][0]
        by_tag = client.get("/api/v1/memos", params={"tag": tag})
        assert [item["id"] for item in by_tag.json()["items"]] == [created["id"]]


def test_ocr_retry_route_updates_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """手动重试会重新识别并覆盖上一次结果。"""

    state = {"text": "第一次识别"}

    def fake_local(_bytes: bytes, _languages: str) -> str:
        return state["text"]

    with build_client(
        tmp_path,
        monkeypatch,
        provider="local",
        local=fake_local,
    ) as client:
        created = create_image_memo(client)
        upload_image(client, str(created["id"]))
        assert fetch_memo(client, str(created["id"]))["image_ocr_text"] == "第一次识别"

        state["text"] = "第二次识别"
        retried = client.post(f"/api/v1/memos/{created['id']}/image/ocr")
        assert retried.status_code == 200
        assert retried.json()["image_ocr_text"] == "第二次识别"


def test_ocr_disabled_provider_keeps_status_and_rejects_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未启用 OCR 时上传不识别，手动重试返回 503。"""

    with build_client(tmp_path, monkeypatch, provider="none") as client:
        created = create_image_memo(client)
        upload_image(client, str(created["id"]))
        stored = fetch_memo(client, str(created["id"]))
        assert stored["image_ocr_status"] == "none"
        assert stored["image_ocr_text"] is None
        assert stored["image_auto_tags"] == []

        retried = client.post(f"/api/v1/memos/{created['id']}/image/ocr")
        assert retried.status_code == 503


def test_llm_provider_without_configuration_marks_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """启用视觉模型渠道但没配置服务时，条目记录 disabled 而不是报错。"""

    with build_client(tmp_path, monkeypatch, provider="llm") as client:
        created = create_image_memo(client)
        upload_image(client, str(created["id"]))
        stored = fetch_memo(client, str(created["id"]))
        assert stored["image_ocr_status"] == "disabled"
        assert "MEMOISLE_LLM_BASE_URL" in stored["image_ocr_error"]

        retried = client.post(f"/api/v1/memos/{created['id']}/image/ocr")
        assert retried.status_code == 200
        assert retried.json()["image_ocr_status"] == "disabled"


def test_reupload_replaces_previous_ocr_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """替换图片会清空并重新识别，不会残留上一张图的文字。"""

    state = {"text": "第一张图"}

    def fake_local(_bytes: bytes, _languages: str) -> str:
        return state["text"]

    with build_client(
        tmp_path,
        monkeypatch,
        provider="local",
        local=fake_local,
    ) as client:
        created = create_image_memo(client)
        uploaded = upload_image(client, str(created["id"]))
        assert fetch_memo(client, str(created["id"]))["image_ocr_text"] == "第一张图"

        state["text"] = "第二张图"
        replaced = client.post(
            f"/api/v1/memos/{created['id']}/image",
            params={"expected_version": uploaded["version"]},
            headers={"Content-Type": "image/png"},
            content=png_bytes(48, 48),
        )
        assert replaced.status_code == 200
        assert replaced.json()["image_ocr_status"] == "pending"
        assert fetch_memo(client, str(created["id"]))["image_ocr_text"] == "第二张图"


def test_recognize_image_ocr_rejects_non_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非图片条目不能执行图片 OCR。"""

    with build_client(tmp_path, monkeypatch, provider="local") as client:
        idea = client.post(
            "/api/v1/memos",
            json={"client_id": str(uuid4()), "type": "idea", "body": "不是图片"},
        ).json()
        response = client.post(f"/api/v1/memos/{idea['id']}/image/ocr")
        assert response.status_code == 422
