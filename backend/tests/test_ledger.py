"""记账接口测试：增删改查、版本冲突、按月汇总和账号隔离。"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from app.auth_service import create_dev_session
from app.database import Database
from app.models import User
from fastapi.testclient import TestClient
from sqlalchemy import inspect

BASE = "/api/v1/ledger"


def entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "expense",
        "amount_cents": 2_550,
        "currency": "CNY",
        "occurred_on": "2026-11-03",
        "category": "餐饮",
        "account": "银行卡",
        "note": "午饭",
    }
    payload.update(overrides)
    return payload


def create(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.post(f"{BASE}/entries", json=entry(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def other_account_headers(client: TestClient) -> dict[str, str]:
    """新建另一个账号并关闭开发模式回退，之后不带令牌的请求会被拒绝。"""

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    return {"Authorization": f"Bearer {token}"}


def test_ledger_entry_crud_with_versions(client: TestClient) -> None:
    """新建、读取、修改、删除都按版本号，字段清洗后保存。"""

    created = create(
        client,
        currency=" usd ",
        category="  订阅 ",
        account="   ",
        note="",
    )
    assert created["currency"] == "USD"
    assert created["category"] == "订阅"
    assert created["account"] is None
    assert created["note"] is None
    assert created["version"] == 1
    assert created["occurred_on"] == "2026-11-03"
    assert created["created_at"].endswith("Z")

    listed = client.get(f"{BASE}/entries", params={"month": "2026-11"}).json()
    assert [item["id"] for item in listed] == [created["id"]]

    entry_id = created["id"]
    updated = client.put(
        f"{BASE}/entries/{entry_id}",
        json=entry(
            kind="income",
            amount_cents=10_000,
            category="报销",
            occurred_on="2026-10-31",
            expected_version=1,
        ),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["version"] == 2
    assert body["kind"] == "income"
    assert body["amount_cents"] == 10_000
    assert body["currency"] == "CNY"
    assert body["occurred_on"] == "2026-10-31"
    # 改了日期后换到十月。
    assert client.get(f"{BASE}/entries", params={"month": "2026-11"}).json() == []
    assert len(client.get(f"{BASE}/entries", params={"month": "2026-10"}).json()) == 1

    # 旧版本号修改：409，并带上服务端当前内容。
    stale = client.put(
        f"{BASE}/entries/{entry_id}",
        json=entry(expected_version=1),
    )
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "version_conflict"
    assert detail["current"]["version"] == 2
    assert detail["current"]["category"] == "报销"

    stale_delete = client.delete(
        f"{BASE}/entries/{entry_id}", params={"expected_version": 1}
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["detail"]["current"]["version"] == 2

    deleted = client.delete(
        f"{BASE}/entries/{entry_id}", params={"expected_version": 2}
    )
    assert deleted.status_code == 204
    assert client.get(f"{BASE}/entries").json() == []
    assert (
        client.put(
            f"{BASE}/entries/{entry_id}", json=entry(expected_version=2)
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"{BASE}/entries/{entry_id}", params={"expected_version": 2}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_cents": 0},
        {"amount_cents": -100},
        {"amount_cents": 100_000_000_001},
        {"amount_cents": "100"},
        {"amount_cents": 12.5},
        {"amount_cents": 100.0},
        {"amount_cents": True},
        {"currency": "CN"},
        {"currency": "CNYY"},
        {"currency": "12A"},
        {"currency": None},
        {"occurred_on": "2026/11/03"},
        {"occurred_on": "2026-13-01"},
        {"occurred_on": "2026-02-30"},
        {"occurred_on": "2026-11-03T08:00:00"},
        {"occurred_on": 1_762_000_000},
        {"occurred_on": "1899-12-31"},
        {"kind": "transfer"},
        {"kind": None},
        {"category": "   "},
        {"category": None},
        {"category": "类" * 31},
        {"account": "户" * 31},
        {"note": "注" * 501},
    ],
)
def test_ledger_rejects_invalid_entries(
    client: TestClient, overrides: dict[str, object]
) -> None:
    """金额、币种、日期、方向、分类不合法都拒绝。"""

    response = client.post(f"{BASE}/entries", json=entry(**overrides))
    assert response.status_code == 422, overrides
    assert client.get(f"{BASE}/entries").json() == []


def test_ledger_accepts_boundary_values(client: TestClient) -> None:
    """最小 1 分、最大 10 亿元、30 字分类都能保存；缺省币种为人民币。"""

    payload = entry(amount_cents=1, category="类" * 30)
    payload.pop("currency")
    smallest = client.post(f"{BASE}/entries", json=payload)
    assert smallest.status_code == 201
    assert smallest.json()["currency"] == "CNY"
    largest = create(client, amount_cents=100_000_000_000)
    assert largest["amount_cents"] == 100_000_000_000


def test_ledger_rejects_invalid_queries(client: TestClient) -> None:
    """月份必须是 YYYY-MM，ID 必须是 UUID，版本号必填。"""

    for month in [
        "2026-13",
        "2026-1",
        "2026-00",
        "26-11",
        "2026-11-01",
        "0000-01",
        "9999-12",
        "1899-12",
        "2101-01",
    ]:
        assert client.get(f"{BASE}/summary", params={"month": month}).status_code == 422
        assert client.get(f"{BASE}/entries", params={"month": month}).status_code == 422
    assert client.get(f"{BASE}/summary").status_code == 422
    assert client.get(f"{BASE}/entries", params={"kind": "transfer"}).status_code == 422
    assert (
        client.put(
            f"{BASE}/entries/not-a-uuid", json=entry(expected_version=1)
        ).status_code
        == 422
    )
    created = create(client)
    assert client.delete(f"{BASE}/entries/{created['id']}").status_code == 422
    assert (
        client.put(f"{BASE}/entries/{created['id']}", json=entry()).status_code == 422
    )


def test_ledger_list_filters_and_order(client: TestClient) -> None:
    """按方向、分类筛选；同一天后记的排在前面。"""

    first = create(client, occurred_on="2026-11-05", category="交通")
    second = create(client, occurred_on="2026-11-05", category="餐饮")
    older = create(client, occurred_on="2026-11-01", category="餐饮")
    salary = create(client, kind="income", category="工资", occurred_on="2026-11-10")

    listed = client.get(f"{BASE}/entries", params={"month": "2026-11"}).json()
    assert [item["id"] for item in listed] == [
        salary["id"],
        second["id"],
        first["id"],
        older["id"],
    ]
    expenses = client.get(
        f"{BASE}/entries", params={"month": "2026-11", "kind": "expense"}
    ).json()
    assert salary["id"] not in {item["id"] for item in expenses}
    meals = client.get(
        f"{BASE}/entries", params={"month": "2026-11", "category": "餐饮"}
    ).json()
    assert [item["id"] for item in meals] == [second["id"], older["id"]]
    limited = client.get(f"{BASE}/entries", params={"limit": 1}).json()
    assert [item["id"] for item in limited] == [salary["id"]]

    categories = client.get(f"{BASE}/categories").json()
    assert categories[0] == {"kind": "expense", "category": "餐饮", "entry_count": 2}
    assert {"kind": "income", "category": "工资", "entry_count": 1} in categories


def test_ledger_month_boundaries(client: TestClient) -> None:
    """只统计当月：月初、月末都算，相邻月份不算，跨年也正确。"""

    for day in ["2026-01-31", "2026-02-01", "2026-02-28", "2026-03-01"]:
        create(client, occurred_on=day, amount_cents=100)
    february = client.get(f"{BASE}/entries", params={"month": "2026-02"}).json()
    assert sorted(item["occurred_on"] for item in february) == [
        "2026-02-01",
        "2026-02-28",
    ]
    summary = client.get(f"{BASE}/summary", params={"month": "2026-02"}).json()
    assert summary["totals"] == [
        {
            "currency": "CNY",
            "income_cents": 0,
            "expense_cents": 200,
            "balance_cents": -200,
            "entry_count": 2,
        }
    ]

    create(client, occurred_on="2026-12-31", amount_cents=300)
    create(client, occurred_on="2027-01-01", amount_cents=500)
    december = client.get(f"{BASE}/summary", params={"month": "2026-12"}).json()
    assert december["totals"][0]["expense_cents"] == 300
    january = client.get(f"{BASE}/summary", params={"month": "2027-01"}).json()
    assert january["totals"][0]["expense_cents"] == 500

    empty = client.get(f"{BASE}/summary", params={"month": "2025-06"}).json()
    assert empty == {"month": "2025-06", "totals": [], "categories": []}


def test_ledger_summary_splits_currencies_and_categories(client: TestClient) -> None:
    """不同币种分开算，分类小计按币种和方向区分。"""

    create(client, amount_cents=1_200, category="餐饮")
    create(client, amount_cents=800, category="餐饮")
    create(client, amount_cents=5_000, category="交通")
    create(client, kind="income", amount_cents=1_000_000, category="工资")
    create(client, kind="income", amount_cents=300, category="其他")
    create(client, amount_cents=150, category="其他")
    create(client, currency="USD", amount_cents=2_000, category="订阅")
    create(client, currency="USD", kind="income", amount_cents=500, category="其他")

    summary = client.get(f"{BASE}/summary", params={"month": "2026-11"}).json()
    assert summary["month"] == "2026-11"
    assert summary["totals"] == [
        {
            "currency": "CNY",
            "income_cents": 1_000_300,
            "expense_cents": 7_150,
            "balance_cents": 993_150,
            "entry_count": 6,
        },
        {
            "currency": "USD",
            "income_cents": 500,
            "expense_cents": 2_000,
            "balance_cents": -1_500,
            "entry_count": 2,
        },
    ]
    assert [
        (item["currency"], item["kind"], item["category"], item["amount_cents"])
        for item in summary["categories"]
    ] == [
        ("CNY", "expense", "交通", 5_000),
        ("CNY", "expense", "餐饮", 2_000),
        ("CNY", "expense", "其他", 150),
        ("CNY", "income", "工资", 1_000_000),
        ("CNY", "income", "其他", 300),
        ("USD", "expense", "订阅", 2_000),
        ("USD", "income", "其他", 500),
    ]
    meals = next(item for item in summary["categories"] if item["category"] == "餐饮")
    assert meals["entry_count"] == 2


def test_ledger_is_account_scoped(client: TestClient) -> None:
    """其他账号看不到、改不了、删不掉；未登录返回 401。"""

    owned = create(client)
    other = other_account_headers(client)

    assert client.get(f"{BASE}/entries").status_code == 401
    assert client.post(f"{BASE}/entries", json=entry()).status_code == 401
    assert client.get(f"{BASE}/summary", params={"month": "2026-11"}).status_code == 401
    assert client.get(f"{BASE}/categories").status_code == 401
    assert (
        client.delete(
            f"{BASE}/entries/{owned['id']}", params={"expected_version": 1}
        ).status_code
        == 401
    )

    assert client.get(f"{BASE}/entries", headers=other).json() == []
    assert client.get(f"{BASE}/categories", headers=other).json() == []
    assert (
        client.get(
            f"{BASE}/summary", params={"month": "2026-11"}, headers=other
        ).json()["totals"]
        == []
    )
    assert (
        client.put(
            f"{BASE}/entries/{owned['id']}",
            json=entry(expected_version=1),
            headers=other,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"{BASE}/entries/{owned['id']}",
            params={"expected_version": 1},
            headers=other,
        ).status_code
        == 404
    )
    mine = client.post(f"{BASE}/entries", json=entry(amount_cents=99), headers=other)
    assert mine.status_code == 201
    assert [
        item["id"] for item in client.get(f"{BASE}/entries", headers=other).json()
    ] == [mine.json()["id"]]

    # 原账号的数据没有被动过。
    client.app.state.settings = replace(client.app.state.settings, auth_dev_mode=True)
    listed = client.get(f"{BASE}/entries").json()
    assert [(item["id"], item["version"]) for item in listed] == [(owned["id"], 1)]


def test_ledger_entry_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每个账号的条数有上限，超出返回 400，别的账号不受影响。"""

    monkeypatch.setattr("app.ledger_service.MAX_LEDGER_ENTRIES", 2)
    create(client)
    create(client)
    over = client.post(f"{BASE}/entries", json=entry())
    assert over.status_code == 400
    assert "上限" in over.json()["detail"]
    other = other_account_headers(client)
    assert (
        client.post(f"{BASE}/entries", json=entry(), headers=other).status_code == 201
    )


def test_existing_database_gains_ledger_table(tmp_path: Path) -> None:
    """旧库启动时自动建出记账表和索引，重复执行不出错，已有数据不受影响。"""

    database_path = tmp_path / "upgrade.db"
    database = Database(f"sqlite+pysqlite:///{database_path}")
    database.create_schema()
    with database.session_factory() as session:
        session.add(User(id="u1", display_name="老用户"))
        session.commit()
    database.dispose()

    # 模拟升级前的库：没有记账表。
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE ledger_entry")

    upgraded = Database(f"sqlite+pysqlite:///{database_path}")
    try:
        upgraded.create_schema()
        upgraded.create_schema()
        inspector = inspect(upgraded.engine)
        assert "ledger_entry" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("ledger_entry")}
        assert {
            "id",
            "user_id",
            "kind",
            "amount_cents",
            "currency",
            "occurred_on",
            "category",
            "account",
            "note",
            "version",
            "created_at",
            "updated_at",
        } <= columns
        indexes = {index["name"] for index in inspector.get_indexes("ledger_entry")}
        assert "ix_ledger_entry_user_occurred" in indexes
        with upgraded.engine.connect() as connection:
            name = connection.exec_driver_sql(
                "SELECT display_name FROM user WHERE id='u1'"
            ).scalar()
        assert name == "老用户"
    finally:
        upgraded.dispose()


def test_ledger_pagination(client: TestClient) -> None:
    """分页不遗漏同日记录，汇总不受分页影响。"""

    ids = [create(client)["id"] for _ in range(3)]
    pages = [
        client.get(f"{BASE}/entries", params={"limit": 1, "offset": index}).json()
        for index in range(4)
    ]
    assert [page[0]["id"] for page in pages[:3]] == list(reversed(ids))
    assert pages[3] == []
    assert client.get(f"{BASE}/entries", params={"offset": -1}).status_code == 422


def test_ledger_simultaneous_writes_do_not_overwrite(client: TestClient) -> None:
    """两个会话都读到版本 1，后提交的修改与删除必须报冲突。"""

    from app.ledger_service import (
        LedgerVersionConflictError,
        delete_entry,
        update_entry,
    )
    from app.models import LedgerEntry
    from app.schemas import LedgerEntryUpdate

    created = create(client)
    factory = client.app.state.database.session_factory
    user_id = client.app.state.settings.local_user_id
    with factory() as first, factory() as second:
        # 保持旧实例在身份映射中，真实模拟两个客户端同时读取旧版本。
        stale = second.get(LedgerEntry, created["id"])
        assert stale.version == 1
        update_entry(
            first,
            user_id,
            created["id"],
            LedgerEntryUpdate(**entry(expected_version=1)),
        )
        with pytest.raises(LedgerVersionConflictError) as conflict:
            update_entry(
                second,
                user_id,
                created["id"],
                LedgerEntryUpdate(**entry(expected_version=1, note="旧修改")),
            )
        assert conflict.value.current.version == 2
    with factory() as first, factory() as second:
        stale = second.get(LedgerEntry, created["id"])
        assert stale.version == 2
        update_entry(
            first,
            user_id,
            created["id"],
            LedgerEntryUpdate(**entry(expected_version=2)),
        )
        with pytest.raises(LedgerVersionConflictError) as conflict:
            delete_entry(second, user_id, created["id"], 2)
        assert conflict.value.current.version == 3


def test_ledger_concurrent_creation_respects_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同时新增也不能越过账号配额。"""

    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.ledger_service import LedgerLimitError, create_entry
    from app.schemas import LedgerEntryCreate

    create(client)
    monkeypatch.setattr("app.ledger_service.MAX_LEDGER_ENTRIES", 2)
    barrier = Barrier(2)
    factory = client.app.state.database.session_factory
    user_id = client.app.state.settings.local_user_id

    def attempt() -> bool:
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                create_entry(session, user_id, LedgerEntryCreate(**entry()))
                return True
            except LedgerLimitError:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == [False, True]
    assert len(client.get(f"{BASE}/entries").json()) == 2
