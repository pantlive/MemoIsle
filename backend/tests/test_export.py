"""个人资料导出测试。"""

from __future__ import annotations

import csv
from io import StringIO
from uuid import uuid4

from fastapi.testclient import TestClient


def test_csv_and_markdown_exports_keep_user_content(client: TestClient) -> None:
    """CSV 保留结构化字段，Markdown 保留可读正文和来源。"""

    login = client.post("/api/v1/auth/dev-login")
    assert login.status_code == 200
    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "idea",
            "title": "导出测试",
            "body": "第一行\n第二行",
            "transcript": "会议转写内容",
            "tags": ["学习", "迁移"],
        },
    )
    assert created.status_code == 201

    csv_response = client.get("/api/v1/exports/csv")
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert csv_response.headers["content-disposition"].endswith(".csv\"")
    rows = list(csv.DictReader(StringIO(csv_response.text)))
    assert len(rows) == 1
    assert rows[0]["title"] == "导出测试"
    assert rows[0]["body"] == "第一行\n第二行"
    assert '"学习","迁移"' in rows[0]["tags"]

    markdown_response = client.get("/api/v1/exports/markdown")
    assert markdown_response.status_code == 200
    assert "text/markdown" in markdown_response.headers["content-type"]
    assert "## 1. 导出测试" in markdown_response.text
    assert "第一行\n第二行" in markdown_response.text
    assert "### 转写" in markdown_response.text
    assert "会议转写内容" in markdown_response.text
    assert "学习" in markdown_response.text


def test_export_requires_a_persisted_user(client: TestClient) -> None:
    """未建立账号时不能生成看似成功的私人导出。"""

    response = client.get("/api/v1/exports/json")
    assert response.status_code == 404
