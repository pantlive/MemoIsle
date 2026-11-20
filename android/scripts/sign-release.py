"""使用私有签名配置签署 Release APK，签名密码只通过子进程环境传递。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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


RELEASE_PACKAGE = "com.memoisle.app"
METADATA_FILENAME = "memoisle-android.json"
_BADGING_PATTERN = re.compile(
    r"^package: name='(?P<name>[^']+)' versionCode='(?P<code>\d+)' "
    r"versionName='(?P<version>[^']*)'",
    re.MULTILINE,
)


def read_badging(tools: Path, apk: Path) -> tuple[str, int, str]:
    """用 build-tools 里的 aapt2 读出包名、versionCode 和 versionName。"""
    for name in ("aapt2", "aapt"):
        executable = tools / name
        if not executable.is_file():
            continue
        output = subprocess.run(
            [str(executable), "dump", "badging", str(apk)],
            check=True, capture_output=True, text=True,
        ).stdout
        match = _BADGING_PATTERN.search(output)
        if match:
            return match["name"], int(match["code"]), match["version"]
        raise ValueError("无法从 APK 读取版本信息")
    raise ValueError(f"{tools} 中没有 aapt2，请安装 Android build-tools")


def file_sha256(path: Path) -> str:
    """分块计算 SHA-256，避免整包读进内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_metadata(
    apk: Path, version_code: int, version_name: str, notes: str,
) -> Path:
    """在 APK 旁写版本信息，供后端 /android/latest 返回；只含公开信息，不含签名配置。"""
    metadata = {
        "versionCode": version_code,
        "versionName": version_name,
        "sha256": file_sha256(apk),
        "size": apk.stat().st_size,
        "notes": notes.strip(),
    }
    target = apk.with_name(METADATA_FILENAME)
    staged = target.with_name(f"{target.name}.tmp")
    staged.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    staged.replace(target)
    return target


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
    parser.add_argument(
        "--release-notes", default="",
        help="写入版本信息 JSON 的更新说明，手机端更新提示里展示",
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
    package, version_code, version_name = read_badging(tools, args.output)
    if package != RELEASE_PACKAGE:
        raise ValueError(f"包名应为 {RELEASE_PACKAGE}，实际为 {package}")
    metadata = write_release_metadata(
        args.output, version_code, version_name, args.release_notes,
    )
    print(f"签名安装包：{args.output}")
    print(f"版本：{version_name}（versionCode {version_code}）")
    print(f"SHA-256：{file_sha256(args.output)}")
    print(f"版本信息：{metadata}")


if __name__ == "__main__":
    main()
