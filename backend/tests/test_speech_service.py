"""语音合成接口测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_tts_route_returns_private_wav(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TTS 路由应返回 WAV，而不是把音频内容写入 JSON。"""

    audio_path = tmp_path / "speech.wav"
    audio_path.write_bytes(b"RIFF" + b"0" * 64)

    def fake_synthesize_speech(text: str, settings: object, voice: str | None) -> Path:
        """模拟已经完成模型推理的 TTS 服务。"""

        assert text == "hello world"
        assert voice == "amy"
        return audio_path

    monkeypatch.setattr("app.api.synthesize_speech", fake_synthesize_speech)
    response = client.post(
        "/api/v1/speech/tts",
        json={"text": "hello world", "voice": "amy"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == audio_path.read_bytes()


def test_tts_route_maps_missing_runtime_to_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未安装 sanoTTS 时客户端应收到可回退的 503。"""

    def unavailable(*_args: object, **_kwargs: object) -> Path:
        """模拟 TTS 运行时未安装。"""

        from app.speech_service import SpeechServiceUnavailableError

        raise SpeechServiceUnavailableError("服务端未安装 sanotts")

    monkeypatch.setattr("app.api.synthesize_speech", unavailable)
    response = client.post("/api/v1/speech/tts", json={"text": "hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == "服务端未安装 sanotts"
