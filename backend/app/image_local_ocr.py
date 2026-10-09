"""本地 PyTorch 图片识别，模型初始化与推理均不上传图片。"""

from pathlib import Path
from threading import RLock
from typing import Any

from app.image_ocr_service import (
    OcrResult,
    OcrUnavailableError,
    build_ocr_preview,
    derive_tags_from_text,
    normalize_ocr_text,
)

_readers: dict[str, Any] = {}
_reader_lock = RLock()


def recognize_local_image(image_bytes: bytes, model_directory: Path) -> OcrResult:
    """本地识别中英文。引擎内部 Tensor Shape: (B, C, H, W)，B=1。"""

    try:
        import easyocr
        import torch
    except ImportError as error:
        raise OcrUnavailableError("请先在 conda 环境安装 PyTorch 和 EasyOCR") from error
    try:
        # 预览限制输入尺寸；串行复用阅读器，避免多个批次同时占用显存。
        preview = build_ocr_preview(image_bytes, 2400)
        with _reader_lock, torch.inference_mode():
            key = str(model_directory.resolve())
            reader = _readers.get(key)
            if reader is None:
                gpu_available = (
                    torch.cuda.is_available() or torch.backends.mps.is_available()
                )
                reader = easyocr.Reader(
                    ["ch_sim", "en"],
                    gpu=gpu_available,
                    model_storage_directory=str(model_directory),
                    download_enabled=False,
                    verbose=False,
                )
                _readers[key] = reader
            lines = reader.readtext(preview, detail=0, workers=0, batch_size=1)
        text = normalize_ocr_text("\n".join(str(line) for line in lines))
        return OcrResult(
            text=text, tags=derive_tags_from_text(text, 8), source="local_pytorch"
        )
    except Exception as error:
        raise OcrUnavailableError(
            "本地 OCR 模型不可用，请准备中英文识别模型后继续"
        ) from error
