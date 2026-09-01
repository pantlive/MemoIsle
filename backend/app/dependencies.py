"""FastAPI 请求依赖。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Database


def get_database(request: Request) -> Database:
    """从应用状态获取数据库。"""

    database: Database = request.app.state.database
    return database


def get_session(request: Request) -> Iterator[Session]:
    """提供请求级数据库会话。"""

    yield from get_database(request).session()


def get_current_user_id(request: Request) -> str:
    """返回本地开发用户，后续替换为认证依赖。"""

    settings: Settings = request.app.state.settings
    return settings.local_user_id


def get_settings(request: Request) -> Settings:
    """返回应用配置。"""

    settings: Settings = request.app.state.settings
    return settings
