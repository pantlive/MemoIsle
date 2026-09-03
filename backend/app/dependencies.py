"""FastAPI 请求依赖。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth_service import get_user_by_token
from app.config import Settings
from app.database import Database


def get_database(request: Request) -> Database:
    """从应用状态获取数据库。"""

    database: Database = request.app.state.database
    return database


def get_session(request: Request) -> Iterator[Session]:
    """提供请求级数据库会话。"""

    yield from get_database(request).session()


def get_current_user_id(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> str:
    """校验 Bearer 会话；开发模式可显式回退本地用户。"""

    settings: Settings = request.app.state.settings
    authorization = request.headers.get("authorization")
    if authorization is None:
        if settings.auth_dev_mode:
            return settings.local_user_id
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证格式无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = get_user_by_token(session, token.strip())
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已过期，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user.id
    return settings.local_user_id


def get_settings(request: Request) -> Settings:
    """返回应用配置。"""

    settings: Settings = request.app.state.settings
    return settings
