"""一句话记账：规则解析器和 POST /ledger/quick 接口。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from app.auth_service import create_dev_session
from app.ledger_parser import (
    EXPENSE_CATEGORY_KEYWORDS,
    FALLBACK_CATEGORY,
    INCOME_CATEGORY_KEYWORDS,
    LedgerParseError,
    parse_ledger_sentence,
)
from fastapi.testclient import TestClient

BASE = "/api/v1/ledger"
TODAY = date(2026, 11, 16)


@pytest.mark.parametrize(
    ("text", "today", "expected"),
    [
        (
            "今天早饭花了10元",
            TODAY,
            {
                "kind": "expense",
                "category": "餐饮",
                "amount_cents": 1_000,
                "occurred_on": TODAY,
                "currency": "CNY",
                "account": None,
            },
        ),
        (
            "昨天打车25块",
            TODAY,
            {
                "occurred_on": date(2026, 11, 15),
                "category": "交通",
                "amount_cents": 2_500,
            },
        ),
        (
            "前天午饭20",
            TODAY,
            {"occurred_on": date(2026, 11, 14), "amount_cents": 2_000},
        ),
        (
            "大前天看电影45元",
            TODAY,
            {"occurred_on": date(2026, 11, 13), "category": "娱乐"},
        ),
        # 没写年份且今年的日期还没到，回退到去年；日期里的数字不算金额。
        (
            "3月5号午饭20",
            date(2026, 2, 10),
            {
                "occurred_on": date(2025, 3, 5),
                "amount_cents": 2_000,
                "category": "餐饮",
            },
        ),
        ("3月5号午饭20", TODAY, {"occurred_on": date(2026, 3, 5)}),
        (
            "十二月一日电费100",
            TODAY,
            {
                "occurred_on": date(2025, 12, 1),
                "category": "住房",
                "amount_cents": 10_000,
            },
        ),
        (
            "2026年10月8日房租3000",
            TODAY,
            {"occurred_on": date(2026, 10, 8), "amount_cents": 300_000},
        ),
        (
            "2026-11-01 买药35",
            TODAY,
            {"occurred_on": date(2026, 11, 1), "category": "医疗"},
        ),
        ("早饭三块五", TODAY, {"amount_cents": 350, "category": "餐饮"}),
        ("十块五毛", TODAY, {"amount_cents": 1_050, "category": FALLBACK_CATEGORY}),
        ("花了一百二", TODAY, {"amount_cents": 12_000}),
        ("午饭12.5块", TODAY, {"amount_cents": 1_250}),
        ("午饭１２．５元", TODAY, {"amount_cents": 1_250}),
        (
            "￥３０奶茶",
            TODAY,
            {"amount_cents": 3_000, "currency": "CNY", "category": "餐饮"},
        ),
        ("1,000元买衣服", TODAY, {"amount_cents": 100_000, "category": "购物"}),
        (
            "发工资8000",
            TODAY,
            {"kind": "income", "category": "工资", "amount_cents": 800_000},
        ),
        ("工资1.5万", TODAY, {"kind": "income", "amount_cents": 1_500_000}),
        ("收到红包200", TODAY, {"kind": "income", "category": FALLBACK_CATEGORY}),
        ("退款120", TODAY, {"kind": "income", "amount_cents": 12_000}),
        (
            "咖啡5美元",
            TODAY,
            {"currency": "USD", "amount_cents": 500, "category": "餐饮"},
        ),
        ("订阅续费$20", TODAY, {"currency": "USD", "category": "订阅"}),
        ("酒店住宿800港币", TODAY, {"currency": "HKD", "category": "住房"}),
        (
            "微信付了30块打车",
            TODAY,
            {"account": "微信", "amount_cents": 3_000, "category": "交通"},
        ),
        # “支付宝”里的“付”不算支出动词。
        ("支付宝收到转账200", TODAY, {"kind": "income", "account": "支付宝"}),
        # 数量、时间、序号里的数字不是金额。
        ("买了2杯咖啡花了30", TODAY, {"amount_cents": 3_000, "category": "餐饮"}),
        ("我们一块去吃饭花了100", TODAY, {"amount_cents": 10_000}),
        ("早上8:30吃早饭10元", TODAY, {"amount_cents": 1_000}),
        ("坐地铁2号线4元", TODAY, {"amount_cents": 400, "category": "交通"}),
        ("超市买菜88", TODAY, {"category": "餐饮"}),
    ],
)
def test_parse_ledger_sentence(
    text: str, today: date, expected: dict[str, object]
) -> None:
    parsed = parse_ledger_sentence(text, today)
    for field, value in expected.items():
        assert getattr(parsed, field) == value, (text, field)
    assert parsed.note == text


def test_parse_keeps_stripped_sentence_as_note() -> None:
    parsed = parse_ledger_sentence("  今天早饭花了10元 \n", TODAY)
    assert parsed.note == "今天早饭花了10元"
    assert parsed.model_dump() == {
        "kind": "expense",
        "amount_cents": 1_000,
        "currency": "CNY",
        "occurred_on": TODAY,
        "category": "餐饮",
        "account": None,
        "note": "今天早饭花了10元",
    }


def test_parse_prefers_used_custom_category() -> None:
    """句中直接写到用过的分类时优先用它，只看同一方向、长的优先。"""

    known = [("expense", "早点"), ("expense", "早点铺"), ("income", "包子")]
    parsed = parse_ledger_sentence("早点铺买包子8元", TODAY, known)
    assert parsed.category == "早点铺"
    # 只用过“包子”作收入分类，支出仍按关键词归到餐饮。
    assert parse_ledger_sentence("买包子8元", TODAY, known).category == "餐饮"
    assert (
        parse_ledger_sentence(
            "ChatGPT 续费20刀", TODAY, [("expense", "chatgpt")]
        ).category
        == "chatgpt"
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("早饭", "没有识别到金额"),
        ("   ", "请输入一句话"),
        ("早饭10元午饭20元", "一句话只能记一笔"),
        ("早饭10 午饭20", "一句话只能记一笔"),
        ("花了12.345元", "最多两位小数"),
        ("捡到0元", "大于 0"),
        ("买房花了1000000001元", "不能超过 10 亿"),
        ("买房花了20亿", "不能超过 10 亿"),
        ("2026年2月30日午饭20", "不存在"),
        ("13月5日午饭20", "不存在"),
    ],
)
def test_parse_rejects_unclear_sentences(text: str, message: str) -> None:
    with pytest.raises(LedgerParseError, match=message):
        parse_ledger_sentence(text, TODAY)


def test_parse_accepts_amount_limit_and_date_range() -> None:
    assert (
        parse_ledger_sentence("买房1000000000元", TODAY).amount_cents == 100_000_000_000
    )
    with pytest.raises(LedgerParseError, match="范围"):
        parse_ledger_sentence("昨天午饭10元", date(1900, 1, 1))


def test_preset_categories_match_web_presets() -> None:
    """预置分类与 web/src/ledger.ts 的 LEDGER_PRESET_CATEGORIES 一致。"""

    expense = [category for category, _ in EXPENSE_CATEGORY_KEYWORDS]
    income = [category for category, _ in INCOME_CATEGORY_KEYWORDS]
    assert sorted([*expense, FALLBACK_CATEGORY]) == sorted(
        ["餐饮", "交通", "购物", "订阅", "住房", "娱乐", "医疗", "其他"]
    )
    assert sorted([*income, FALLBACK_CATEGORY]) == sorted(["工资", "其他"])


def quick(client: TestClient, text: str, **extra: object) -> object:
    return client.post(
        f"{BASE}/quick", json={"text": text, "today": "2026-11-16", **extra}
    )


def test_quick_create_saves_parsed_entry(client: TestClient) -> None:
    response = quick(client, "  今天早饭花了10元  ")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "expense"
    assert body["category"] == "餐饮"
    assert body["amount_cents"] == 1_000
    assert body["currency"] == "CNY"
    assert body["occurred_on"] == "2026-11-16"
    assert body["note"] == "今天早饭花了10元"
    assert body["version"] == 1

    listed = client.get(f"{BASE}/entries", params={"month": "2026-11"}).json()
    assert [item["id"] for item in listed] == [body["id"]]
    summary = client.get(f"{BASE}/summary", params={"month": "2026-11"}).json()
    assert summary["totals"][0]["expense_cents"] == 1_000


def test_quick_create_uses_categories_used_before(client: TestClient) -> None:
    created = client.post(
        f"{BASE}/entries",
        json={
            "kind": "expense",
            "amount_cents": 100,
            "occurred_on": "2026-11-01",
            "category": "小卖部",
        },
    )
    assert created.status_code == 201
    response = quick(client, "昨天小卖部买水3元")
    assert response.status_code == 201, response.text
    assert response.json()["category"] == "小卖部"
    assert response.json()["occurred_on"] == "2026-11-15"


def test_quick_create_rejects_unclear_text_without_saving(client: TestClient) -> None:
    for text in ["早饭", "早饭10元午饭20元", "2026年2月30日午饭20"]:
        response = quick(client, text)
        assert response.status_code == 422, text
        detail = response.json()["detail"]
        assert isinstance(detail, str) and detail
    assert quick(client, "早饭").json()["detail"].startswith("没有识别到金额")
    assert client.get(f"{BASE}/entries").json() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "今天早饭花了10元", "today": "2026-13-01"},
        {"text": "今天早饭花了10元", "today": "2026/11/16"},
        {"text": "今天早饭花了10元", "today": "2026-11-16T00:00:00"},
        {"text": "今天早饭花了10元", "today": "1899-12-31"},
        {"text": "今天早饭花了10元"},
        {"text": "   ", "today": "2026-11-16"},
        {"text": "饭" * 201 + "10元", "today": "2026-11-16"},
        {"text": 10, "today": "2026-11-16"},
    ],
)
def test_quick_create_validates_payload(
    client: TestClient, payload: dict[str, object]
) -> None:
    response = client.post(f"{BASE}/quick", json=payload)
    assert response.status_code == 422, payload
    assert client.get(f"{BASE}/entries").json() == []


def test_quick_create_is_account_scoped(client: TestClient) -> None:
    """其他账号看不到这笔，也用不到这个账号的自定义分类；未登录返回 401。"""

    client.post(
        f"{BASE}/entries",
        json={
            "kind": "expense",
            "amount_cents": 100,
            "occurred_on": "2026-11-01",
            "category": "小卖部",
        },
    )
    owned = quick(client, "小卖部买水3元").json()
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    other = {"Authorization": f"Bearer {token}"}

    assert quick(client, "今天早饭花了10元").status_code == 401
    mine = client.post(
        f"{BASE}/quick",
        json={"text": "小卖部买水3元", "today": "2026-11-16"},
        headers=other,
    )
    assert mine.status_code == 201, mine.text
    assert mine.json()["category"] == "购物"
    assert [
        item["id"] for item in client.get(f"{BASE}/entries", headers=other).json()
    ] == [mine.json()["id"]]

    # 原账号仍是自己的两笔，用到了自己的分类，没有混入对方那笔。
    client.app.state.settings = replace(settings, auth_dev_mode=True)
    listed = client.get(f"{BASE}/entries").json()
    assert len(listed) == 2
    assert listed[0]["id"] == owned["id"]
    assert owned["category"] == "小卖部"
    assert mine.json()["id"] not in {item["id"] for item in listed}


def test_quick_create_respects_entry_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.ledger_service.MAX_LEDGER_ENTRIES", 1)
    assert quick(client, "今天早饭花了10元").status_code == 201
    over = quick(client, "今天午饭花了20元")
    assert over.status_code == 400
    assert "上限" in over.json()["detail"]
