"""当前账号的模型设置接口。"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_current_user_id, get_session, get_settings
from app.model_settings_service import (
    ModelSettingError,
    read_model_setting,
    reset_model_setting,
    save_model_setting,
    verify_model_connection,
)
from app.schemas import (
    ModelConnectionResult,
    ModelProvider,
    ModelSettingRead,
    ModelSettingUpdate,
)


class ModelSettingRoute(APIRoute):
    """避免验证错误把请求正文中的 API Key 回显给客户端。"""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """为模型设置接口统一隐藏输入校验详情。"""

        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            """保留原路由行为，只替换可能含密钥的校验错误。"""

            try:
                return await original(request)
            except RequestValidationError as error:
                raise HTTPException(
                    status_code=422,
                    detail="设置格式无效，请检查模型名称、请求地址和请求字段",
                ) from error

        return handle


router = APIRouter(
    prefix="/model-settings",
    tags=["settings"],
    route_class=ModelSettingRoute,
)
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get("", response_model=list[ModelSettingRead])
def list_model_settings_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> list[ModelSettingRead]:
    """列出当前账号可配置的模型服务。"""

    return [
        read_model_setting(session, user_id, settings, provider)
        for provider in ModelProvider
    ]


@router.put("/{provider}", response_model=ModelSettingRead)
def save_model_setting_route(
    provider: ModelProvider,
    payload: ModelSettingUpdate,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ModelSettingRead:
    """保存设置后立即生效，无需重启服务。"""

    try:
        return save_model_setting(
            session, user_id, settings, provider, payload
        )
    except ModelSettingError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/{provider}", response_model=ModelSettingRead)
def reset_model_setting_route(
    provider: ModelProvider,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ModelSettingRead:
    """删除账号保存的配置及密钥。"""

    return reset_model_setting(session, user_id, settings, provider)


@router.post("/{provider}/test", response_model=ModelConnectionResult)
def test_model_connection_route(
    provider: ModelProvider,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    payload: ModelSettingUpdate | None = None,
) -> ModelConnectionResult:
    """测试当前填写或已保存的凭据，不在测试时写入数据库。"""

    try:
        return verify_model_connection(
            session,
            user_id,
            settings,
            provider,
            payload,
        )
    except ModelSettingError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
