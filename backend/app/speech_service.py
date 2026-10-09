"""可选的语音合成服务。"""

from __future__ import annotations

import hashlib
import threading
import wave
from pathlib import Path
from typing import Any

from app.config import Settings


class SpeechServiceUnavailableError(RuntimeError):
    """语音合成运行时或语音包没有安装。"""


class SpeechTextTooLongError(ValueError):
    """语音合成文本超过服务端限制。"""


_SYNTHESIZERS: dict[str, Any] = {}
_SYNTHESIZER_LOCK = threading.Lock()


def _cache_path(settings: Settings, text: str, voice: str) -> Path:
    """根据文本和音色构造稳定的缓存路径。"""

    digest = hashlib.sha256(f"{voice}\0{text}".encode()).hexdigest()
    return settings.sanotts_cache_directory / "audio" / f"{digest}.wav"


def _write_wave(path: Path, samples: Any, sample_rate: int) -> None:
    """把 sanoTTS 的 float32 单声道采样写成 PCM WAV。"""

    try:
        import numpy as np
    except ImportError as error:
        raise SpeechServiceUnavailableError(
            "TTS 依赖 numpy 未安装，请重新创建 conda 环境",
        ) from error

    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim != 1 or audio.size == 0:
        raise SpeechServiceUnavailableError("TTS 没有生成有效音频")
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    try:
        with wave.open(str(temporary_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(pcm)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def synthesize_speech(
    text: str,
    settings: Settings,
    voice: str | None = None,
) -> Path:
    """使用可选的 sanoTTS 生成并缓存 WAV 音频。"""

    cleaned_text = " ".join(text.split())
    if not cleaned_text:
        raise ValueError("语音文本不能为空")
    if len(cleaned_text) > settings.tts_max_text_length:
        raise SpeechTextTooLongError("语音文本过长")
    if not settings.tts_enabled or settings.tts_provider == "none":
        raise SpeechServiceUnavailableError("服务端 TTS 未启用")

    resolved_voice = (voice or settings.sanotts_voice).strip() or settings.sanotts_voice
    if not resolved_voice.replace("-", "").replace("_", "").isalnum():
        raise ValueError("TTS 音色名称无效")
    path = _cache_path(settings, cleaned_text, resolved_voice)
    if path.is_file() and path.stat().st_size > 44:
        return path

    try:
        import sanotts
    except ImportError as error:
        raise SpeechServiceUnavailableError(
            "服务端未安装 sanotts，请按文档安装 TTS 依赖",
        ) from error

    with _SYNTHESIZER_LOCK:
        synthesizer = _SYNTHESIZERS.get(resolved_voice)
        if synthesizer is None:
            try:
                synthesizer = sanotts.Synthesizer(
                    voice=resolved_voice,
                    cache_dir=settings.sanotts_cache_directory,
                )
            except Exception as error:
                raise SpeechServiceUnavailableError(
                    "sanoTTS 音色加载失败，请检查音色包或网络",
                ) from error
            _SYNTHESIZERS[resolved_voice] = synthesizer
        try:
            result = synthesizer.synthesize(cleaned_text)
            _write_wave(path, result.audio, int(result.sample_rate))
        except SpeechServiceUnavailableError:
            raise
        except Exception as error:
            raise SpeechServiceUnavailableError("sanoTTS 合成失败") from error
    return path
