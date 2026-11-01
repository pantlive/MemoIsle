"""路由共用的依赖注入别名。"""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    Depends,
)
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_current_user_id, get_session, get_settings

SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
