"""会议总结服务的接口行为测试。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from app.config import Settings
from app.meeting_service import (
    MeetingSummaryNotConfiguredError,
    summarize_meeting,
)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    """构造只用于服务测试的隔离配置。"""

    values: dict[str, object] = {
        "database_url": f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        "cors_origins": ("http://localhost:5173",),
        "local_user_id": "00000000-0000-0000-0000-000000000001",
        "audio_directory": tmp_path / "audio",
        "llm_base_url": "https://llm.example/v1",
        "llm_api_key": "test-key",
        "llm_model": "test-model",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_summarize_meeting_calls_openai_compatible_api(tmp_path: Path) -> None:
    """服务端应调用 chat/completions 并返回模型生成的纪要。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "会议概要\n关键要点\n行动项"}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = summarize_meeting(
            "主持人：确认周五上线。",
            "产品周会",
            _settings(tmp_path),
            client,
        )

    assert summary == "会议概要\n关键要点\n行动项"
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer test-key"
    payload = json.loads(requests[0].content)
    assert "对方1" in payload["messages"][0]["content"]
    assert "不代表真实姓名" in payload["messages"][0]["content"]


def test_summarize_meeting_requires_llm_config(tmp_path: Path) -> None:
    """没有配置模型地址时给出可操作的错误。"""

    with pytest.raises(MeetingSummaryNotConfiguredError):
        summarize_meeting(
            "主持人：确认周五上线。",
            "产品周会",
            _settings(tmp_path, llm_base_url=None),
        )


def test_meeting_summary_route_reports_missing_configuration(client) -> None:
    """未配置 LLM 时接口应返回可诊断的 503，而不是静默失败。"""

    response = client.post(
        "/api/v1/meeting/summary",
        json={"title": "产品周会", "transcript": "主持人：确认周五上线。"},
    )

    assert response.status_code == 503
    assert "MEMOISLE_LLM_BASE_URL" in response.json()["detail"]
