"""后端测试夹具。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# 必须在 import app 模块之前设置：conftest 顶层会 import app.main，而它模块级
# 会执行 create_app() → from_environment()。未配置登录密钥时会在真实数据目录
# 生成密钥文件，测试不应改动开发者的数据目录，所以用固定值兜底。
os.environ.setdefault("MEMOISLE_AUTH_TOKEN_SECRET", "test-auth-token-secret")

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """使用隔离 SQLite 文件提供 API 客户端。"""

    database_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database_path}",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_dev_mode=True,
        auth_token_secret="test-auth-token-secret",
        audio_directory=tmp_path / "audio",
        image_directory=tmp_path / "images",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
        word_dictionary_enabled=False,
    )
    app = create_app(settings=settings, database=Database(settings.database_url))
    with TestClient(app) as test_client:
        yield test_client
