"""预先下载本地 PyTorch 中英文 OCR 权重，运行时不再访问模型下载地址。"""

import argparse
from pathlib import Path


def prepare_models(model_directory: Path) -> None:
    """初始化本地模型。内部 Tensor Shape: (B, C, H, W)，推理不计算梯度。"""

    import easyocr
    import torch

    model_directory.mkdir(parents=True, exist_ok=True)
    # 根据当前环境选择设备，不绑定 CUDA 或特定显卡。
    with torch.inference_mode():
        easyocr.Reader(
            ["ch_sim", "en"],
            gpu=torch.cuda.is_available() or torch.backends.mps.is_available(),
            model_storage_directory=str(model_directory.resolve()),
            verbose=False,
        )


def main() -> None:
    """通过显式目录准备权重，不读取或上传用户图片。"""

    parser = argparse.ArgumentParser(description="准备本地中英文 OCR 权重")
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    prepare_models(args.models)
    print("本地 OCR 模型已准备，可在图片收藏中启动批量识别。")


if __name__ == "__main__":
    main()
