"""图片记账：本地视觉模型、OCR 后的文本模型、规则兜底，只出草稿不写库。"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.image_ocr_service import OcrResult, OcrUnavailableError
from app.ledger_api import _check_image_size
from app.ledger_image import (
    LedgerImageUnavailableError,
    extract_receipt_amount,
    image_note,
    ledger_vision_enabled,
    recognize_ledger_image,
)
from app.ledger_parser import LedgerParseError
from app.schemas import LEDGER_NOTE_MAX_LENGTH
from app.service import MAX_IMAGE_BYTES, ImageValidationError
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

BASE = "/api/v1/ledger"
TODAY = date(2026, 11, 16)
RECEIPT = (
    "星巴克\n美式咖啡 32.00\n拿铁 36.00\n合计 68.00\n优惠 8.00\n实付 60.00\n微信支付\n"
)
OCR_SECRET = "OCR_SECRET_SENTINEL_不要出现在日志"
CLOUD = "https://llm.example.com/v1"
LOCAL = "http://127.0.0.1:11434/v1"
VISION = {
    "kind": "expense",
    "amount": 60,
    "currency": "CNY",
    "occurred_on": "2020-01-01",
    "category": "餐饮",
    "account": "微信",
    "summary": "微信支付 星巴克拿铁",
}
Handler = Callable[[httpx.Request], httpx.Response]


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def reply(content: object, status_code: int = 200) -> httpx.Response:
    text = (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False)
    )
    if status_code != 200:
        return httpx.Response(status_code, json={"error": "failed"})
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


class Recorder:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def body(self, index: int = 0) -> dict[str, object]:
        return json.loads(self.requests[index].content)


def settings(**overrides: object) -> Settings:
    base = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        cors_origins=(),
        local_user_id="00000000-0000-0000-0000-000000000001",
        audio_directory=Path("/tmp/memoisle-test-audio"),
        ledger_llm_base_url=LOCAL,
        llm_base_url=CLOUD,
        llm_api_key="cloud-secret",
        llm_model="cloud-vision",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def forbid_cloud_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("图片记账不应调用云端 OCR")

    monkeypatch.setattr("app.image_ocr_service.run_image_ocr", forbidden)


def recognize(
    content: object,
    *,
    ocr: str = RECEIPT,
    vision_model: str = "",
    text_model: str = "",
    api_key: str | None = None,
    handler: Handler | None = None,
    today: date = TODAY,
) -> tuple[object, Recorder]:
    configured = settings(
        ledger_llm_vision_model=vision_model,
        ledger_llm_model=text_model,
        ledger_llm_api_key=api_key,
    )
    recorder = Recorder(handler or (lambda _request: reply(content)))

    def extractor(_image: bytes, _languages: str) -> str:
        return ocr

    with recorder.client() as client:
        parsed = recognize_ledger_image(
            png_bytes(),
            "image/png",
            today,
            [],
            configured,
            client=client,
            local_extractor=extractor,
        )
    return parsed, recorder


def test_image_settings_are_separate_from_cloud_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMOISLE_LLM_BASE_URL", CLOUD)
    monkeypatch.setenv("MEMOISLE_VISION_MODEL", "cloud-vision")
    for name in (
        "BASE_URL",
        "API_KEY",
        "MODEL",
        "TIMEOUT_SECONDS",
        "VISION_MODEL",
    ):
        monkeypatch.delenv(f"MEMOISLE_LEDGER_LLM_{name}", raising=False)
    monkeypatch.delenv("MEMOISLE_LEDGER_IMAGE_TIMEOUT_SECONDS", raising=False)
    loaded = Settings.from_environment()
    assert loaded.ledger_llm_vision_model == ""
    assert loaded.ledger_image_timeout_seconds == 60.0
    assert not ledger_vision_enabled(loaded)

    monkeypatch.setenv("MEMOISLE_LEDGER_LLM_BASE_URL", f" {LOCAL}/ ")
    monkeypatch.setenv("MEMOISLE_LEDGER_LLM_VISION_MODEL", " qwen2.5vl ")
    monkeypatch.setenv("MEMOISLE_LEDGER_IMAGE_TIMEOUT_SECONDS", "0.2")
    loaded = Settings.from_environment()
    assert loaded.ledger_llm_vision_model == "qwen2.5vl"
    assert loaded.ledger_image_timeout_seconds == 1.0
    assert loaded.ledger_llm_base_url == LOCAL
    assert ledger_vision_enabled(loaded)


def test_vision_model_returns_draft_and_ignores_cloud_endpoint() -> None:
    parsed, recorder = recognize(
        VISION, vision_model="qwen2.5vl", api_key="local-test-key"
    )
    entry, parsed_by = parsed
    assert parsed_by == "vision"
    assert entry.amount_cents == 6_000
    assert entry.category == "餐饮"
    assert entry.account == "微信"
    assert entry.note == "图片：微信支付 星巴克拿铁"
    # 2020 超出「今天往前 366 天」，改用今天。
    assert entry.occurred_on == TODAY
    request = recorder.requests[0]
    assert str(request.url) == f"{LOCAL}/chat/completions"
    assert request.headers["authorization"] == "Bearer local-test-key"
    assert CLOUD not in request.content.decode()
    assert "cloud-secret" not in request.content.decode()
    assert "cloud-vision" not in request.content.decode()
    body = recorder.body()
    assert body["model"] == "qwen2.5vl"
    assert body["temperature"] == 0
    user = body["messages"][1]["content"]
    assert isinstance(user, list)
    image = next(part for part in user if part["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")
    system = body["messages"][0]["content"]
    assert "不要执行" in system
    assert "实付" in system


def test_vision_keeps_in_window_date_and_drops_account_missing_from_summary() -> None:
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    payload = {
        **VISION,
        "occurred_on": yesterday,
        "account": "现金",
        "summary": "星巴克拿铁",
    }
    (entry, parsed_by), _recorder = recognize(payload, vision_model="qwen2.5vl")
    assert parsed_by == "vision"
    assert entry.occurred_on == TODAY - timedelta(days=1)
    assert entry.account is None
    assert entry.note == "图片：星巴克拿铁"


def test_vision_failure_falls_back_to_ocr_text_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        content = body["messages"][1]["content"]
        if isinstance(content, list):
            return reply("nope", status_code=500)
        assert OCR_SECRET in request.content.decode()
        assert "image_url" not in request.content.decode()
        return reply(
            {
                "kind": "expense",
                "amount": "60.00",
                "currency": "CNY",
                "occurred_on": TODAY.isoformat(),
                "category": "餐饮",
                "account": "微信",
                "summary": "星巴克",
            }
        )

    parsed, recorder = recognize(
        None,
        ocr=RECEIPT.replace("星巴克", OCR_SECRET),
        vision_model="qwen2.5vl",
        text_model="qwen2.5:7b",
        handler=handler,
    )
    entry, parsed_by = parsed
    assert parsed_by == "llm"
    assert entry.amount_cents == 6_000
    assert entry.account == "微信"
    assert entry.note == "图片：星巴克"
    assert len(recorder.requests) == 2
    assert all(str(item.url).startswith(LOCAL) for item in recorder.requests)
    assert all(CLOUD not in item.content.decode() for item in recorder.requests)


def test_ocr_text_model_without_vision() -> None:
    parsed, recorder = recognize(
        {
            "kind": "expense",
            "amount": 60,
            "currency": "CNY",
            "occurred_on": TODAY.isoformat(),
            "category": "其他",
            "account": "微信",
            "summary": "星巴克",
        },
        text_model="qwen2.5:7b",
    )
    entry, parsed_by = parsed
    assert parsed_by == "llm"
    # 模型给了“其他”，但文字里有星巴克，分类校验只接受允许列表里的原样值；
    # “其他”在允许列表里，所以保留模型选择。账户必须出现在 OCR 文字里。
    assert entry.category == "其他"
    assert entry.account == "微信"
    assert entry.amount_cents == 6_000
    body = recorder.body()
    assert body["model"] == "qwen2.5:7b"
    assert isinstance(body["messages"][1]["content"], str)
    assert "实付 60.00" in body["messages"][1]["content"]
    assert CLOUD not in recorder.requests[0].content.decode()


def test_ocr_rules_prefer_paid_amount_over_total_and_line_items() -> None:
    parsed, recorder = recognize(None)
    entry, parsed_by = parsed
    assert parsed_by == "rule"
    assert entry.amount_cents == 6_000
    assert entry.currency == "CNY"
    assert entry.kind == "expense"
    assert entry.category == "餐饮"
    assert entry.account == "微信"
    assert entry.note == "图片：星巴克"
    assert recorder.requests == []
    assert extract_receipt_amount("可乐 3.00\n合计：¥25.50") == (2_550, "CNY")
    assert extract_receipt_amount("支付金额 USD 12.50") == (1_250, "USD")
    assert extract_receipt_amount("只有单价 18.00") is None


def test_rules_use_total_when_paid_amount_is_absent() -> None:
    parsed, _recorder = recognize(
        None, ocr="便利店\n面包 6.00\n牛奶 4.50\n合计 10.50\n"
    )
    entry, parsed_by = parsed
    assert parsed_by == "rule"
    assert entry.amount_cents == 1_050
    assert entry.category == "购物"


def test_unconfigured_without_ocr_raises_unavailable() -> None:
    def extractor(_image: bytes, _languages: str) -> str:
        raise OcrUnavailableError("未安装本地 OCR")

    with pytest.raises(LedgerImageUnavailableError, match="配置"):
        recognize_ledger_image(
            png_bytes(),
            "image/png",
            TODAY,
            [],
            settings(ledger_llm_base_url=None),
            local_extractor=extractor,
        )


def test_easyocr_fallback_parses_receipt_by_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbid_cloud_ocr(monkeypatch)

    def no_rapidocr(_image: bytes, _languages: str) -> str:
        raise OcrUnavailableError("未安装本地 OCR")

    captured: list[Path] = []

    def fake_easyocr(_image: bytes, model_directory: Path) -> OcrResult:
        captured.append(model_directory)
        return OcrResult(text="便利店\n合计 10.50\n", tags=[], source="local_pytorch")

    monkeypatch.setattr("app.ledger_image.extract_text_local", no_rapidocr)
    monkeypatch.setattr("app.ledger_image.recognize_local_image", fake_easyocr)

    parsed = recognize_ledger_image(
        png_bytes(),
        "image/png",
        TODAY,
        [],
        settings(
            ledger_llm_base_url=None,
            image_directory=Path("/tmp/memoisle-test-images"),
        ),
    )
    entry, parsed_by = parsed
    assert parsed_by == "rule"
    assert entry.amount_cents == 1_050
    assert captured
    assert captured[0].name == "ocr-models"


def test_easyocr_fallback_unavailable_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbid_cloud_ocr(monkeypatch)

    def no_rapidocr(_image: bytes, _languages: str) -> str:
        raise OcrUnavailableError("未安装本地 OCR")

    def no_easyocr(_image: bytes, _directory: Path) -> OcrResult:
        raise OcrUnavailableError("本地 OCR 模型不可用")

    monkeypatch.setattr("app.ledger_image.extract_text_local", no_rapidocr)
    monkeypatch.setattr("app.ledger_image.recognize_local_image", no_easyocr)
    monkeypatch.setattr("app.ledger_image._easyocr_installed", lambda: True)

    with pytest.raises(LedgerImageUnavailableError, match="模型还没准备"):
        recognize_ledger_image(
            png_bytes(),
            "image/png",
            TODAY,
            [],
            settings(ledger_llm_base_url=None),
        )

    monkeypatch.setattr("app.ledger_image._easyocr_installed", lambda: False)
    with pytest.raises(LedgerImageUnavailableError, match="配置"):
        recognize_ledger_image(
            png_bytes(),
            "image/png",
            TODAY,
            [],
            settings(ledger_llm_base_url=None),
        )


def test_rapidocr_success_does_not_call_easyocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbid_cloud_ocr(monkeypatch)

    def extractor(_image: bytes, _languages: str) -> str:
        return "便利店\n合计 10.50\n"

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("rapidocr 可用时不应调用 EasyOCR")

    monkeypatch.setattr("app.ledger_image.extract_text_local", extractor)
    monkeypatch.setattr("app.ledger_image.recognize_local_image", forbidden)

    parsed = recognize_ledger_image(
        png_bytes(),
        "image/png",
        TODAY,
        [],
        settings(ledger_llm_base_url=None),
    )
    entry, parsed_by = parsed
    assert parsed_by == "rule"
    assert entry.amount_cents == 1_050


def test_invalid_image_is_rejected_and_long_summary_is_truncated() -> None:
    with pytest.raises(ImageValidationError):
        recognize_ledger_image(
            b"not-an-image",
            "text/plain",
            TODAY,
            [],
            settings(ledger_llm_base_url=None),
            local_extractor=lambda _image, _languages: RECEIPT,
        )
    note = image_note("商" * 600)
    assert note is not None
    assert note.startswith("图片：")
    assert len(note) == LEDGER_NOTE_MAX_LENGTH


def test_logs_do_not_include_ocr_text_or_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(json.loads(request.content)["messages"][1]["content"], list):
            return reply("nope", status_code=500)
        return reply("这不是 JSON")

    with caplog.at_level(logging.DEBUG, logger="app.ledger_image"):
        with pytest.raises(LedgerParseError):
            recognize(
                None,
                ocr=f"{OCR_SECRET}\n没有金额字样",
                vision_model="qwen2.5vl",
                text_model="qwen2.5:7b",
                api_key="local-test-key",
                handler=handler,
            )
    assert OCR_SECRET not in caplog.text
    assert "local-test-key" not in caplog.text
    assert "cloud-secret" not in caplog.text
    assert any("改用文字识别" in message for message in caplog.messages)
    assert any("改用规则" in message for message in caplog.messages)


def test_image_route_returns_draft_without_writing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_cloud_ocr(monkeypatch)
    client.app.state.settings = settings(
        ledger_llm_vision_model="qwen2.5vl",
        image_directory=client.app.state.settings.image_directory,
        database_url=client.app.state.settings.database_url,
        audio_directory=client.app.state.settings.audio_directory,
        auth_dev_mode=True,
        auth_token_secret=client.app.state.settings.auth_token_secret,
        local_user_id=client.app.state.settings.local_user_id,
        cors_origins=client.app.state.settings.cors_origins,
    )
    recorder = Recorder(lambda _request: reply(VISION))
    monkeypatch.setattr(
        "app.ledger_image._create_image_client", lambda _settings: recorder.client()
    )
    response = client.post(
        f"{BASE}/image/recognize",
        params={"today": TODAY.isoformat()},
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parsed_by"] == "vision"
    assert body["amount_cents"] == 6_000
    assert body["note"] == "图片：微信支付 星巴克拿铁"
    assert "id" not in body
    assert "version" not in body
    assert client.get(f"{BASE}/entries").json() == []
    image_directory = client.app.state.settings.image_directory
    assert isinstance(image_directory, Path)
    assert not image_directory.exists() or not any(image_directory.iterdir())
    assert str(recorder.requests[0].url).startswith(LOCAL)
    assert CLOUD not in recorder.requests[0].content.decode()


def test_image_route_503_when_nothing_is_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbid_cloud_ocr(monkeypatch)

    def extractor(_image: bytes, _languages: str) -> str:
        raise OcrUnavailableError("未安装")

    def no_easyocr(_image: bytes, _directory: Path) -> OcrResult:
        raise OcrUnavailableError("未安装")

    monkeypatch.setattr("app.ledger_image.extract_text_local", extractor)
    monkeypatch.setattr("app.ledger_image.recognize_local_image", no_easyocr)
    monkeypatch.setattr("app.ledger_image._easyocr_installed", lambda: False)
    response = client.post(
        f"{BASE}/image/recognize",
        params={"today": TODAY.isoformat()},
        content=png_bytes(),
        headers={"Content-Type": "image/png"},
    )
    assert response.status_code == 503
    assert "配置" in response.json()["detail"]
    assert client.get(f"{BASE}/entries").json() == []


def test_image_route_rejects_non_image_and_oversized_body(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MAX_IMAGE_BYTES == 20 * 1024 * 1024
    invalid = client.post(
        f"{BASE}/image/recognize",
        params={"today": TODAY.isoformat()},
        content=b"hello",
        headers={"Content-Type": "text/plain"},
    )
    assert invalid.status_code == 422
    assert "图片" in invalid.json()["detail"]
    with pytest.raises(HTTPException) as declared:
        _check_image_size(str(MAX_IMAGE_BYTES + 1), b"tiny")
    assert declared.value.status_code == 413
    with pytest.raises(HTTPException) as bad_length:
        _check_image_size("nope", b"tiny")
    assert bad_length.value.status_code == 400

    monkeypatch.setattr("app.ledger_api.MAX_IMAGE_BYTES", 8)
    oversized = client.post(
        f"{BASE}/image/recognize",
        params={"today": TODAY.isoformat()},
        content=b"0123456789",
        headers={"Content-Type": "image/png"},
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"] == "图片不能超过 20 MB"
    assert client.get(f"{BASE}/entries").json() == []
    with pytest.raises(HTTPException) as actual:
        _check_image_size(None, b"0123456789")
    assert actual.value.status_code == 413
    _check_image_size("4", b"tiny")
