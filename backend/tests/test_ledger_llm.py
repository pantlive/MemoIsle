"""一句话记账的本地大模型识别：回复解析、逐项校验、失败退回规则。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.ledger_llm import (
    LedgerLlmUnavailableError,
    allowed_categories,
    extract_json_object,
    ledger_llm_enabled,
    parse_with_llm,
)
from fastapi.testclient import TestClient

BASE = "/api/v1/ledger"
TODAY = date(2026, 11, 16)
SENTENCE = "今天早饭花了10元"
LLM_SETTINGS = Settings(
    database_url="sqlite+pysqlite:///:memory:",
    cors_origins=(),
    local_user_id="00000000-0000-0000-0000-000000000001",
    audio_directory=Path("/tmp/memoisle-test-audio"),
    ledger_llm_base_url="http://127.0.0.1:11434/v1",
    ledger_llm_model="qwen2.5:7b",
)
BREAKFAST = {
    "kind": "expense",
    "amount": 10,
    "currency": "CNY",
    "occurred_on": "2026-11-16",
    "category": "餐饮",
    "account": None,
}

Handler = Callable[[httpx.Request], httpx.Response]


def reply(content: object) -> httpx.Response:
    """OpenAI 兼容的 chat/completions 回复。"""

    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


class Recorder:
    """记下发给模型的请求，并按预设回复。"""

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


def parse(
    content: object,
    text: str = SENTENCE,
    known: list[tuple[str, str]] | None = None,
    settings: Settings = LLM_SETTINGS,
) -> object:
    recorder = Recorder(lambda _request: reply(content))
    with recorder.client() as client:
        return parse_with_llm(text, TODAY, known or [], settings, client=client)


def test_enabled_only_with_base_url_and_model() -> None:
    assert ledger_llm_enabled(LLM_SETTINGS)
    assert not ledger_llm_enabled(replace(LLM_SETTINGS, ledger_llm_base_url=None))
    assert not ledger_llm_enabled(replace(LLM_SETTINGS, ledger_llm_model="  "))


def test_settings_read_separate_ledger_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMOISLE_LLM_BASE_URL", "https://llm.example.com/v1")
    monkeypatch.setenv("MEMOISLE_LLM_MODEL", "cloud-model")
    for name in ("BASE_URL", "API_KEY", "MODEL", "TIMEOUT_SECONDS"):
        monkeypatch.delenv(f"MEMOISLE_LEDGER_LLM_{name}", raising=False)
    settings = Settings.from_environment()
    # 只配了会议总结的模型时，记账不会顺带用上它。
    assert not ledger_llm_enabled(settings)
    assert settings.ledger_llm_timeout_seconds == 15.0

    monkeypatch.setenv("MEMOISLE_LEDGER_LLM_BASE_URL", " http://127.0.0.1:11434/v1/ ")
    monkeypatch.setenv("MEMOISLE_LEDGER_LLM_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("MEMOISLE_LEDGER_LLM_API_KEY", "")
    monkeypatch.setenv("MEMOISLE_LEDGER_LLM_TIMEOUT_SECONDS", "0.2")
    settings = Settings.from_environment()
    assert settings.ledger_llm_base_url == "http://127.0.0.1:11434/v1"
    assert settings.ledger_llm_model == "qwen2.5:7b"
    assert settings.ledger_llm_api_key is None
    assert settings.ledger_llm_timeout_seconds == 1.0
    assert ledger_llm_enabled(settings)


def test_parses_model_json_and_sends_expected_request() -> None:
    recorder = Recorder(lambda _request: reply(BREAKFAST))
    with recorder.client() as client:
        parsed = parse_with_llm(
            SENTENCE, TODAY, [("expense", "小卖部"), ("income", "兼职")],
            LLM_SETTINGS, client=client,
        )
    assert parsed.model_dump() == {
        "kind": "expense",
        "amount_cents": 1_000,
        "currency": "CNY",
        "occurred_on": TODAY,
        "category": "餐饮",
        "account": None,
        "note": SENTENCE,
    }
    [request] = recorder.requests
    assert str(request.url) == "http://127.0.0.1:11434/v1/chat/completions"
    assert "authorization" not in request.headers
    body = recorder.body()
    assert body["model"] == "qwen2.5:7b"
    assert body["temperature"] == 0
    assert body["max_tokens"] == 256
    assert "response_format" not in body
    system, user = body["messages"]
    assert system["role"] == "system" and "JSON" in system["content"]
    assert "今天是 2026-11-16（星期一）" in user["content"]
    assert "一句话：今天早饭花了10元" in user["content"]
    # 用过的分类按方向分别给出。
    assert "支出分类：餐饮、交通" in user["content"]
    assert "小卖部" in user["content"].split("收入分类")[0]
    assert "兼职" in user["content"].split("收入分类")[1]


def test_sends_bearer_token_only_when_api_key_is_set() -> None:
    recorder = Recorder(lambda _request: reply(BREAKFAST))
    settings = replace(LLM_SETTINGS, ledger_llm_api_key="local-test-key")
    with recorder.client() as client:
        parse_with_llm(SENTENCE, TODAY, [], settings, client=client)
    assert recorder.requests[0].headers["authorization"] == "Bearer local-test-key"


@pytest.mark.parametrize(
    "content",
    [
        "<think>\n用户说今天早饭，金额 10 元 {不是答案}\n</think>\n"
        + json.dumps(BREAKFAST, ensure_ascii=False),
        "```json\n" + json.dumps(BREAKFAST, ensure_ascii=False) + "\n```",
        "<think>\n\n</think>\n\n```json\n"
        + json.dumps(BREAKFAST, ensure_ascii=False)
        + "\n```\n以上是识别结果。",
        # 有的服务吞掉开头的 <think>，只留结尾标签。
        "先想一想 {草稿}</think>" + json.dumps(BREAKFAST, ensure_ascii=False),
        "识别结果：" + json.dumps({**BREAKFAST, "amount": "10.00"}, ensure_ascii=False),
    ],
)
def test_parses_reply_with_think_block_and_code_fence(content: str) -> None:
    parsed = parse(content)
    assert parsed.amount_cents == 1_000
    assert parsed.category == "餐饮"


def test_extract_json_object_rejects_truncated_thinking() -> None:
    with pytest.raises(LedgerLlmUnavailableError):
        extract_json_object('<think>先算金额 {"amount": 10')
    with pytest.raises(LedgerLlmUnavailableError):
        extract_json_object("[1, 2]")
    assert extract_json_object('前缀 {坏的} 然后 {"a": {"b": 1}}') == {"a": {"b": 1}}


@pytest.mark.parametrize(
    "content",
    [
        "好的，今天早饭花了 10 元。",
        "{kind: expense, amount: 10}",
        {**BREAKFAST, "amount": 0},
        {**BREAKFAST, "amount": -10},
        {**BREAKFAST, "amount": 1_000_000_000.01},
        {**BREAKFAST, "amount": 12.345},
        {**BREAKFAST, "amount": True},
        {**BREAKFAST, "amount": "十元"},
        {**BREAKFAST, "amount": None},
        {**BREAKFAST, "kind": "transfer"},
        {**BREAKFAST, "currency": "RMB元"},
        {"error": "没有金额"},
        {**BREAKFAST, "error": "一句话有两笔"},
    ],
)
def test_rejects_invalid_model_output(content: object) -> None:
    with pytest.raises(LedgerLlmUnavailableError):
        parse(content)


def test_accepts_amount_limit_chinese_kind_and_default_currency() -> None:
    parsed = parse(
        {**BREAKFAST, "kind": "收入", "amount": 1_000_000_000, "currency": None},
        text="今天收到奖金1000000000元",
    )
    assert parsed.kind == "income"
    assert parsed.amount_cents == 100_000_000_000
    assert parsed.currency == "CNY"
    assert parsed.category == "其他"
    assert parse({**BREAKFAST, "amount": 12.5, "currency": "usd"}).currency == "USD"


def test_category_must_be_preset_or_used_before() -> None:
    known = [("expense", "小卖部"), ("income", "兼职")]
    # 不在列表里的分类改用规则选的。
    assert parse({**BREAKFAST, "category": "早餐"}).category == "餐饮"
    assert parse({**BREAKFAST, "category": None}).category == "餐饮"
    # 用过的分类可以选，大小写按已有的写法保存。
    assert parse({**BREAKFAST, "category": "小卖部"}, known=known).category == "小卖部"
    assert (
        parse(
            {**BREAKFAST, "category": "CHATGPT"},
            text="ChatGPT 续费20刀",
            known=[("expense", "chatgpt")],
        ).category
        == "chatgpt"
    )
    # 收入分类不能用在支出上。
    assert parse({**BREAKFAST, "category": "兼职"}, known=known).category == "餐饮"


def test_allowed_categories_caps_used_categories() -> None:
    known = [("expense", f"分类{index}") for index in range(80)]
    allowed = allowed_categories("expense", [("expense", "餐饮"), *known])
    presets = ["餐饮", "交通", "住房", "订阅", "医疗", "娱乐", "购物", "其他"]
    assert allowed[:8] == presets
    assert allowed[8:] == [f"分类{index}" for index in range(50)]
    assert allowed_categories("income", known) == ["工资", "其他"]


@pytest.mark.parametrize(
    ("text", "model_date", "expected"),
    [
        # 句中写了规则认得出的日期时以规则为准，不信模型算错的日期。
        (SENTENCE, "2024-06-01", TODAY),
        ("昨天打车25块", "2026-11-16", date(2026, 11, 15)),
        ("3月5号午饭20", "2026-03-05", date(2026, 3, 5)),
        # 规则认不出的说法用模型的日期，但不能晚于明天，也不能越界。
        ("上周五聚餐花了88", "2026-11-13", date(2026, 11, 13)),
        ("明天的车票花了50", "2026-11-17", date(2026, 11, 17)),
        ("聚餐花了88", "2026-11-18", TODAY),
        ("聚餐花了88", "1899-12-31", TODAY),
        ("聚餐花了88", "2026-02-30", TODAY),
        ("聚餐花了88", "2026/11/13", TODAY),
        ("聚餐花了88", None, TODAY),
    ],
)
def test_date_prefers_rule_and_checks_model_date(
    text: str, model_date: str | None, expected: date
) -> None:
    assert parse({**BREAKFAST, "occurred_on": model_date}, text=text).occurred_on == (
        expected
    )


def test_nonexistent_date_in_sentence_is_left_to_rules() -> None:
    with pytest.raises(LedgerLlmUnavailableError):
        parse({**BREAKFAST, "occurred_on": "2026-03-01"}, text="2026年2月30日午饭20")


def test_account_must_appear_in_sentence() -> None:
    assert parse({**BREAKFAST, "account": "现金"}).account is None
    assert (
        parse({**BREAKFAST, "account": None}, text="微信付了30块打车").account
        == "微信"
    )
    assert (
        parse({**BREAKFAST, "account": "招商银行卡"}, text="招商银行卡付了30块").account
        == "招商银行卡"
    )


def test_not_configured_does_not_send_request() -> None:
    recorder = Recorder(lambda _request: reply(BREAKFAST))
    with recorder.client() as client, pytest.raises(LedgerLlmUnavailableError):
        parse_with_llm(
            SENTENCE,
            TODAY,
            [],
            replace(LLM_SETTINGS, ledger_llm_base_url=None),
            client=client,
        )
    assert recorder.requests == []


def test_failure_log_omits_sentence_and_key(caplog: pytest.LogCaptureFixture) -> None:
    settings = replace(LLM_SETTINGS, ledger_llm_api_key="local-test-key")
    recorder = Recorder(lambda _request: httpx.Response(500, text=SENTENCE))
    with (
        caplog.at_level(logging.WARNING, logger="app.ledger_llm"),
        recorder.client() as client,
        pytest.raises(LedgerLlmUnavailableError),
    ):
        parse_with_llm(SENTENCE, TODAY, [], settings, client=client)
    assert "HTTP 500" in caplog.text
    assert "早饭" not in caplog.text
    assert "local-test-key" not in caplog.text


# ---- POST /ledger/quick 接入模型 ----


@pytest.fixture
def model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[Handler], Recorder]]:
    """打开记账模型配置，并把发给模型的请求换成假的回复。"""

    original = client.app.state.settings
    client.app.state.settings = replace(
        original,
        ledger_llm_base_url=LLM_SETTINGS.ledger_llm_base_url,
        ledger_llm_model=LLM_SETTINGS.ledger_llm_model,
    )
    recorders: list[Recorder] = []

    def install(handler: Handler) -> Recorder:
        recorder = Recorder(handler)
        recorders.append(recorder)
        monkeypatch.setattr(
            "app.ledger_llm._create_client", lambda _settings: recorder.client()
        )
        return recorder

    yield install
    client.app.state.settings = original


def quick(client: TestClient, text: str = SENTENCE) -> httpx.Response:
    return client.post(f"{BASE}/quick", json={"text": text, "today": "2026-11-16"})


def test_quick_uses_local_model(
    client: TestClient, model: Callable[[Handler], Recorder]
) -> None:
    recorder = model(lambda _request: reply(BREAKFAST))
    response = quick(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parsed_by"] == "llm"
    assert body["kind"] == "expense"
    assert body["category"] == "餐饮"
    assert body["amount_cents"] == 1_000
    assert body["occurred_on"] == "2026-11-16"
    assert body["note"] == SENTENCE
    assert len(recorder.requests) == 1
    listed = client.get(f"{BASE}/entries", params={"month": "2026-11"}).json()
    assert [item["id"] for item in listed] == [body["id"]]
    assert "parsed_by" not in listed[0]


def test_quick_model_handles_sentence_rules_cannot(
    client: TestClient, model: Callable[[Handler], Recorder]
) -> None:
    text = "上周五聚餐AA，我出了八十八"
    assert quick(client, text).status_code == 422  # 规则认不出这个金额

    model(
        lambda _request: reply(
            {**BREAKFAST, "amount": 88, "occurred_on": "2026-11-13"}
        )
    )
    response = quick(client, text)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parsed_by"] == "llm"
    assert body["amount_cents"] == 8_800
    assert body["occurred_on"] == "2026-11-13"


def _raise(error: Exception) -> Handler:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    return handler


@pytest.mark.parametrize(
    "handler",
    [
        lambda _request: reply("今天早饭 10 元"),
        lambda _request: reply({**BREAKFAST, "amount": 0}),
        lambda _request: reply({**BREAKFAST, "amount": 2_000_000_000}),
        lambda _request: reply({"error": "看不懂"}),
        lambda _request: httpx.Response(500, json={"error": "model crashed"}),
        lambda _request: httpx.Response(200, json={"choices": []}),
        _raise(httpx.ReadTimeout("timed out")),
        _raise(httpx.ConnectError("connection refused")),
    ],
)
def test_quick_falls_back_to_rules(
    client: TestClient, model: Callable[[Handler], Recorder], handler: Handler
) -> None:
    recorder = model(handler)
    response = quick(client, "昨天打车25块")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parsed_by"] == "rule"
    assert body["category"] == "交通"
    assert body["amount_cents"] == 2_500
    assert body["occurred_on"] == "2026-11-15"
    assert len(recorder.requests) == 1


def test_quick_replaces_unknown_category_but_keeps_model_result(
    client: TestClient, model: Callable[[Handler], Recorder]
) -> None:
    model(lambda _request: reply({**BREAKFAST, "category": "早点"}))
    body = quick(client).json()
    assert body["parsed_by"] == "llm"
    assert body["category"] == "餐饮"


def test_quick_model_and_rules_both_fail_returns_422_without_saving(
    client: TestClient, model: Callable[[Handler], Recorder]
) -> None:
    recorder = model(lambda _request: reply({"error": "没有金额"}))
    response = quick(client, "早饭")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("没有识别到金额")
    assert len(recorder.requests) == 1
    assert client.get(f"{BASE}/entries").json() == []


def test_quick_without_model_config_sends_no_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(_settings: Settings) -> httpx.Client:
        raise AssertionError("未配置记账模型时不应发请求")

    monkeypatch.setattr("app.ledger_llm._create_client", unexpected)
    # 会议总结配了模型也不影响记账。
    client.app.state.settings = replace(
        client.app.state.settings,
        llm_base_url="https://llm.example.com/v1",
        llm_model="cloud-model",
    )
    response = quick(client)
    assert response.status_code == 201, response.text
    assert response.json()["parsed_by"] == "rule"
    assert response.json()["category"] == "餐饮"


def test_quick_model_sees_categories_used_before(
    client: TestClient, model: Callable[[Handler], Recorder]
) -> None:
    client.post(
        f"{BASE}/entries",
        json={
            "kind": "expense",
            "amount_cents": 100,
            "occurred_on": "2026-11-01",
            "category": "小卖部",
        },
    )
    recorder = model(
        lambda _request: reply({**BREAKFAST, "amount": 3, "category": "小卖部"})
    )
    response = quick(client, "楼下买水3元")
    assert response.status_code == 201, response.text
    assert response.json()["category"] == "小卖部"
    assert "小卖部" in recorder.body()["messages"][1]["content"]
