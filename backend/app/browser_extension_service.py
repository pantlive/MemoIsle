"""浏览器扩展下载包生成业务。"""

from __future__ import annotations

import json
import re
from io import BytesIO
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import PROJECT_ROOT

EXTENSION_DIRECTORY = PROJECT_ROOT / "extension"
EXTENSION_RUNTIME_FILES = (
    "manifest.json",
    "background.js",
    "content.js",
    "README.md",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
    "install.cmd",
    "install.ps1",
)
EXTENSION_ARCHIVE_DIRECTORY = "memoisle-extension"
_EXTENSION_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){0,3}")


def read_browser_extension_version() -> str:
    """读取当前扩展清单中的版本号，供下载文件名使用。"""

    manifest = json.loads(
        (EXTENSION_DIRECTORY / "manifest.json").read_text(encoding="utf-8"),
    )
    version = str(manifest.get("version", "")).strip()
    if _EXTENSION_VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("invalid_extension_version")
    return version


def browser_extension_archive_filename(version: str | None = None) -> str:
    """下载 ZIP 使用带版本号的文件名，避免覆盖旧包时分不清版本。"""

    resolved = version or read_browser_extension_version()
    return f"memoisle-browser-extension-{resolved}.zip"


def _deployment_files(web_base_url: str) -> dict[str, bytes]:
    """按可信的部署配置生成网站下载版，不采用请求头里的主机名。"""

    if not web_base_url.strip():
        return {}
    parsed = urlsplit(web_base_url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid_extension_web_base_url")
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        # 本地下载版保留 Vite 的多个开发端口，与直接加载源码目录保持一致。
        return {}
    # 读取端口会校验格式；保留 9443 等部署端口，避免回连默认的 443。
    _ = parsed.port
    origin = f"{parsed.scheme}://{parsed.netloc.lower()}"
    api_base_url = f"{origin}/api/v1"
    defaults = {
        "apiBaseUrl": api_base_url,
        "webBaseUrl": f"{origin}{parsed.path.rstrip('/')}/",
    }
    background = (EXTENSION_DIRECTORY / "background.js").read_text()
    background, replacements = re.subn(
        r"\Aconst DEFAULT_CONFIG = \{.*?\n\};",
        lambda _: "const DEFAULT_CONFIG = " + json.dumps(defaults, indent=2) + ";",
        background,
        count=1,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise ValueError("extension_default_config_not_found")
    manifest = json.loads((EXTENSION_DIRECTORY / "manifest.json").read_text())
    for script in manifest["content_scripts"]:
        script["matches"] = [f"{origin}/*"]
    # 图片收藏仍需任意站点权限；正式下载包不保留多余的本机后端权限。
    manifest["host_permissions"] = list(
        dict.fromkeys(
            [
                pattern
                for pattern in manifest["host_permissions"]
                if not pattern.startswith(("http://localhost:", "http://127.0.0.1:"))
            ]
            + [f"{origin}/*"]
        )
    )
    installer = (EXTENSION_DIRECTORY / "install.ps1").read_text()
    installer, replacements = re.subn(
        r'(\[string\]\$ApiBase\s*=\s*)"[^"\n]*"',
        lambda match: match[1] + json.dumps(api_base_url),
        installer,
        count=1,
    )
    if replacements != 1:
        raise ValueError("extension_installer_api_not_found")
    return {
        "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        "background.js": background.encode(),
        "install.ps1": installer.encode(),
    }


def build_browser_extension_archive(web_base_url: str = "") -> bytes:
    """打包运行文件，并让网站下载版自动使用当前部署的 Web 与 API 地址。"""

    configured = _deployment_files(web_base_url)
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        # 只打包安装所需文件，避免把测试代码和开发依赖交付给用户。
        for file_name in EXTENSION_RUNTIME_FILES:
            source_path = EXTENSION_DIRECTORY / file_name
            archive_path = f"{EXTENSION_ARCHIVE_DIRECTORY}/{file_name}"
            content = configured.get(file_name)
            archive.writestr(
                archive_path,
                content if content is not None else source_path.read_bytes(),
            )
    return archive_buffer.getvalue()
