"""使用私有签名配置签署 Release APK，签名密码只通过子进程环境传递。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile


def android_sdk(project: Path) -> Path:
    """从环境或本机配置定位 Android SDK，不依赖固定用户目录。"""
    value = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if value:
        return Path(value).expanduser().resolve()
    local = project / "local.properties"
    if local.is_file():
        for line in local.read_text().splitlines():
            if line.startswith("sdk.dir="):
                return Path(line.split("=", 1)[1]).expanduser().resolve()
    raise ValueError("请设置 ANDROID_SDK_ROOT 或在 local.properties 中配置 sdk.dir")


def main() -> None:
    """核对生产地址后对齐并签名，只输出产物路径和公开校验值。"""
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="签署 MemoIsle Release APK")
    parser.add_argument("--signing-config", type=Path, required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument(
        "--apk", type=Path,
        default=project / "app/build/outputs/apk/release/app-release-unsigned.apk",
    )
    parser.add_argument(
        "--output", type=Path,
        default=project / "app/build/outputs/apk/release/memoisle-android.apk",
    )
    args = parser.parse_args()
    configuration = json.loads(args.signing_config.read_text())
    keystore = Path(configuration["keystore"]).expanduser().resolve()
    if not keystore.is_file():
        raise ValueError("签名密钥文件不存在")
    # 构建时必须明确指向目标 API，防止将模拟器地址的包发布到网站。
    with ZipFile(args.apk) as archive:
        correct_api = any(
            args.api_base_url.encode() in archive.read(name)
            for name in archive.namelist()
            if name.startswith("classes") and name.endswith(".dex")
        )
    if not correct_api:
        raise ValueError("APK 中未找到预期 API 地址，请重新构建 Release")
    sdk = android_sdk(project)
    tools = sorted(
        (sdk / "build-tools").iterdir(),
        key=lambda path: tuple(int(part) for part in path.name.split(".")),
    )[-1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    aligned = args.output.with_name(f"{args.output.stem}-aligned.apk")
    environment = {
        **os.environ,
        "MEMOISLE_SIGN_STORE_PASSWORD": configuration["store_password"],
        "MEMOISLE_SIGN_KEY_PASSWORD": configuration["key_password"],
    }
    try:
        subprocess.run([
            str(tools / "zipalign"), "-f", "-P", "16", "4",
            str(args.apk), str(aligned),
        ], check=True)
        subprocess.run([
            str(tools / "apksigner"), "sign", "--ks", str(keystore),
            "--ks-key-alias", configuration["alias"],
            "--ks-pass", "env:MEMOISLE_SIGN_STORE_PASSWORD",
            "--key-pass", "env:MEMOISLE_SIGN_KEY_PASSWORD",
            "--out", str(args.output), str(aligned),
        ], env=environment, check=True)
        subprocess.run([
            str(tools / "apksigner"), "verify", "--verbose", str(args.output),
        ], check=True)
    finally:
        aligned.unlink(missing_ok=True)
    print(f"签名安装包：{args.output}")
    print(f"SHA-256：{hashlib.sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
