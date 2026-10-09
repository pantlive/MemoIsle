"""英语单词批量导入接口测试。"""

from __future__ import annotations

import csv
import io
import json
from uuid import uuid4

from fastapi.testclient import TestClient


def test_import_json_export_and_reimport_is_idempotent(client: TestClient) -> None:
    """完整 JSON 导出可以只回灌单词，重复导入不会重复建词。"""

    first_client_id = str(uuid4())
    content = json.dumps(
        {
            "format": "memoisle-json",
            "memos": [
                {
                    "client_id": first_client_id,
                    "type": "word",
                    "title": "serendipity",
                    "body": "机缘巧合",
                    "word_meaning": "机缘巧合",
                    "word_example": "A fortunate discovery.",
                    "tags": ["英语", "收藏"],
                },
                {
                    "client_id": str(uuid4()),
                    "type": "word",
                    "title": "resilient",
                    "body": "有韧性的",
                    "word_phonetic": "/rɪˈzɪliənt/",
                },
                {
                    "type": "idea",
                    "title": "不会被导入",
                    "body": "普通灵感",
                },
            ],
        },
        ensure_ascii=False,
    )

    response = client.post(
        "/api/v1/words/import?format=json",
        content=content.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "total_count": 3,
        "imported_count": 2,
        "duplicate_count": 0,
        "skipped_count": 1,
        "failed_count": 0,
        "errors": [],
    }

    second_response = client.post(
        "/api/v1/words/import?format=json",
        content=content.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert second_response.status_code == 200
    assert second_response.json()["imported_count"] == 0
    assert second_response.json()["duplicate_count"] == 2

    words = client.get("/api/v1/memos", params={"type": "word"}).json()["items"]
    assert {word["title"] for word in words} == {"serendipity", "resilient"}
    assert words[0]["body"] in {"机缘巧合", "有韧性的"}


def test_import_csv_accepts_common_aliases_and_reports_bad_rows(
    client: TestClient,
) -> None:
    """CSV 可以使用常见列名，非法行只影响当前行。"""

    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=["word", "meaning", "example", "tags", "source_url"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerow(
        {
            "word": "abundant",
            "meaning": "充足的",
            "example": "An abundant harvest.",
            "tags": "英语,积极",
            "source_url": "https://example.com/words",
        }
    )
    writer.writerow(
        {
            "word": "",
            "meaning": "缺少词形",
            "example": "",
            "tags": "",
            "source_url": "",
        }
    )

    response = client.post(
        "/api/v1/words/import?format=csv",
        content=output.getvalue().encode("utf-8"),
        headers={"Content-Type": "text/csv; charset=utf-8"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["imported_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["errors"] == [{"row": 3, "message": "缺少单词词形"}]

    imported = client.get("/api/v1/memos", params={"type": "word"}).json()["items"][0]
    assert imported["title"] == "abundant"
    assert imported["word_meaning"] == "充足的"
    assert imported["tags"] == ["英语", "积极"]
    assert imported["source_url"] == "https://example.com/words"


def test_import_rejects_invalid_format_and_oversized_payload(
    client: TestClient,
) -> None:
    """导入接口拒绝未知格式和超过安全上限的请求。"""

    invalid_format = client.post(
        "/api/v1/words/import?format=xml",
        content=b"<words />",
        headers={"Content-Type": "application/xml"},
    )
    assert invalid_format.status_code == 422

    oversized = client.post(
        "/api/v1/words/import?format=json",
        content=(b"{" + b"a" * (5 * 1024 * 1024) + b"}"),
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
