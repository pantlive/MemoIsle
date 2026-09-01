"""后端测试夹具。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.config import Settings
from app.database import Database
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """使用隔离 SQLite 文件提供 API 客户端。"""

    database_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database_path}",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        audio_directory=tmp_path / "audio",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
    )
    app = create_app(settings=settings, database=Database(settings.database_url))
    with TestClient(app) as test_client:
        yield test_client
