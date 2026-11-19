"""账号：邮箱注册登录、验证码、密码找回/修改、第三方登录回调与会话。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import parse_qsl, urlencode

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth_service import (
    AuthProviderDisabledError,
    AuthProviderError,
    AuthStateError,
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    EmailTokenInvalidError,
    InvalidEmailCredentialsError,
    InvitationInvalidError,
    InvitationQuotaExceededError,
    InvitationRequiredError,
    LoginRateLimitedError,
    PasswordChangeUnavailableError,
    VerificationCodeInvalidError,
    VerificationCodeRateLimitedError,
    build_authorization_url,
    change_password,
    consume_verification_code,
    create_dev_session,
    create_invitation,
    ensure_email_available,
    exchange_authorization_code,
    get_invitation_status,
    invitation_required,
    login_with_password,
    login_with_provider,
    prepare_verification_code,
    provider_enabled,
    provider_label,
    register_with_password,
    request_email_verification_token,
    request_password_reset_token,
    reset_password_with_token,
    resolve_post_login_uri,
    revoke_session,
    sign_state,
    validate_invitation,
    verify_email_token,
    verify_state,
)
from app.config import Settings
from app.email_service import (
    EmailDeliveryError,
    send_auth_email,
    send_verification_code_email,
)
from app.models import User
from app.routes.deps import SessionDependency, SettingsDependency, UserDependency
from app.schemas import (
    AuthActionResponse,
    AuthLogoutResponse,
    AuthProvider,
    AuthProviderInfo,
    AuthProvidersResponse,
    AuthSessionResponse,
    AuthUserResponse,
    EmailLoginRequest,
    EmailRegisterRequest,
    EmailRegisterResponse,
    EmailTokenConfirmRequest,
    EmailTokenRequest,
    InvitationCreateResponse,
    InvitationStatusResponse,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    VerificationCodeRequest,
)

router = APIRouter()


async def _read_callback_payload(request: Request) -> dict[str, str]:
    """读取 GET 查询或 Apple POST 表单中的回调参数。"""

    payload = dict(request.query_params)
    if request.method == "POST":
        body = await request.body()
        payload.update(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    return payload


def _auth_error_redirect(post_login_uri: str, message: str) -> RedirectResponse:
    """把登录失败信息放回前端 URL 片段，避免敏感信息进入日志。"""

    fragment = urlencode({"auth_error": message})
    separator = "#" if "#" not in post_login_uri else "&"
    return RedirectResponse(
        url=f"{post_login_uri}{separator}{fragment}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _handle_auth_callback(
    provider: AuthProvider,
    request: Request,
    session: Session,
    settings: Settings,
) -> RedirectResponse:
    """处理 OAuth 提供方回调并给前端签发登录会话。"""

    payload = await _read_callback_payload(request)
    try:
        state_provider, post_login_uri = verify_state(
            settings,
            payload.get("state", ""),
        )
        if state_provider != provider:
            raise AuthStateError("登录 state 与提供方不匹配")
        if payload.get("error"):
            return _auth_error_redirect(
                post_login_uri,
                payload.get("error_description") or payload["error"],
            )
        code = payload.get("code")
        if not code:
            return _auth_error_redirect(post_login_uri, "第三方登录未返回授权码")
        callback_user = None
        if payload.get("user"):
            callback_user = json.loads(payload["user"])
        profile = exchange_authorization_code(
            settings,
            provider,
            code,
            str(request.url.replace(query="")),
            callback_user,
        )
        created = login_with_provider(session, settings, profile)
    except AuthStateError as error:
        return _auth_error_redirect(
            resolve_post_login_uri(settings, None),
            str(error),
        )
    except AuthProviderError as error:
        return _auth_error_redirect(
            resolve_post_login_uri(settings, None),
            str(error),
        )

    expires_in = int(
        (
            created.session.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)
        ).total_seconds(),
    )
    fragment = urlencode(
        {
            "access_token": created.token,
            "token_type": "bearer",
            "expires_in": expires_in,
        },
    )
    return RedirectResponse(
        url=f"{post_login_uri}#{fragment}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/auth/providers", response_model=AuthProvidersResponse, tags=["auth"])
def read_auth_providers(
    session: SessionDependency,
    settings: SettingsDependency,
) -> AuthProvidersResponse:
    """返回当前环境可用的登录方式。第三方登录默认关闭。"""

    providers = [
        AuthProviderInfo(
            provider=provider,
            label=provider_label(provider),
            enabled=provider_enabled(settings, provider),
        )
        for provider in AuthProvider
    ]
    return AuthProvidersResponse(
        providers=providers,
        dev_login_available=settings.auth_dev_mode,
        email_login_enabled=True,
        invite_required=invitation_required(session, settings),
    )


@router.post(
    "/auth/verification-code",
    response_model=AuthActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["auth"],
)
def request_registration_verification_code(
    payload: VerificationCodeRequest,
    session: SessionDependency,
    settings: SettingsDependency,
) -> AuthActionResponse:
    """发送注册用六位邮箱验证码。"""

    try:
        # 先校验邀请码。无效时不能发信，也不能把验证码记下来。
        validate_invitation(session, settings, payload.invite_code)
        code = prepare_verification_code(session, settings, payload.email)
        send_verification_code_email(settings, payload.email, code)
    except (InvitationRequiredError, InvitationInvalidError) as error:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail="邀请码无效或已被使用",
        ) from error
    except EmailAlreadyRegisteredError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="该邮箱已被注册") from error
    except VerificationCodeRateLimitedError as error:
        session.rollback()
        raise HTTPException(
            status_code=429,
            detail="验证码发送过于频繁，请稍后重试",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except EmailDeliveryError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=str(error)) from error
    session.commit()
    return AuthActionResponse(status="sent")


@router.post(
    "/auth/register",
    response_model=EmailRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
)
def register_with_email_route(
    payload: EmailRegisterRequest,
    session: SessionDependency,
    settings: SettingsDependency,
) -> EmailRegisterResponse:
    """使用六位邮箱验证码注册账号。"""

    try:
        ensure_email_available(session, payload.email)
        # 邀请码必须在消费验证码之前校验，否则无效邀请会白白用掉验证码。
        validate_invitation(session, settings, payload.invite_code)
        consume_verification_code(
            session,
            settings,
            payload.email,
            payload.verification_code,
        )
        created = register_with_password(
            session,
            settings,
            payload.email,
            payload.password,
            payload.display_name,
            payload.invite_code,
        )
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(status_code=409, detail="该邮箱已被注册") from error
    except VerificationCodeInvalidError as error:
        raise HTTPException(status_code=400, detail="验证码无效或已过期") from error
    except InvitationQuotaExceededError as error:
        session.rollback()
        raise HTTPException(status_code=400, detail="邀请机会已用完") from error
    except (InvitationRequiredError, InvitationInvalidError) as error:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail="邀请码无效或已被使用",
        ) from error
    return EmailRegisterResponse(
        user=AuthUserResponse.model_validate(created),
    )


@router.get(
    "/auth/invitations",
    response_model=InvitationStatusResponse,
    tags=["auth"],
)
def read_invitation_status(
    session: SessionDependency,
    user_id: UserDependency,
) -> InvitationStatusResponse:
    """返回当前用户剩余的邀请名额。不返回邀请码明文。"""

    status_value = get_invitation_status(session, user_id)
    return InvitationStatusResponse(
        remaining=status_value.remaining,
        created_at=status_value.created_at,
        used_at=status_value.used_at,
        used_by_label=status_value.used_by_label,
    )


@router.post(
    "/auth/invitations",
    response_model=InvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
)
def create_invitation_route(
    session: SessionDependency,
    settings: SettingsDependency,
    user_id: UserDependency,
) -> InvitationCreateResponse:
    """生成当前用户仅有的一次邀请码。明文只在这次响应中返回。"""

    try:
        created = create_invitation(session, settings, user_id)
    except InvitationQuotaExceededError as error:
        raise HTTPException(status_code=409, detail="邀请机会已用完") from error
    return InvitationCreateResponse(code=created.code, created_at=created.created_at)


@router.post("/auth/login", response_model=AuthSessionResponse, tags=["auth"])
def login_with_email_route(
    payload: EmailLoginRequest,
    session: SessionDependency,
    settings: SettingsDependency,
) -> AuthSessionResponse:
    """使用邮箱和密码登录。"""

    try:
        created = login_with_password(
            session,
            settings,
            payload.email,
            payload.password,
        )
    except InvalidEmailCredentialsError as error:
        raise HTTPException(status_code=401, detail="邮箱或密码不正确") from error
    except EmailNotVerifiedError as error:
        raise HTTPException(status_code=403, detail="请先验证邮箱") from error
    except LoginRateLimitedError as error:
        raise HTTPException(
            status_code=429,
            detail="登录尝试次数过多，请稍后重试",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    return AuthSessionResponse(
        access_token=created.token,
        expires_at=created.session.expires_at,
        user=AuthUserResponse.model_validate(created.user),
    )


@router.post(
    "/auth/verify-email/request",
    response_model=AuthActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["auth"],
)
def request_email_verification_route(
    payload: EmailTokenRequest,
    session: SessionDependency,
    settings: SettingsDependency,
) -> AuthActionResponse:
    """请求重新发送邮箱验证链接。"""

    token_result = request_email_verification_token(session, settings, payload.email)
    if token_result is None:
        # 不区分未注册和已验证，避免暴露账号注册状态。
        return AuthActionResponse(status="ok")
    _, verification_token = token_result
    try:
        send_auth_email(settings, payload.email, "verify_email", verification_token)
    except EmailDeliveryError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return AuthActionResponse(status="ok")


@router.post(
    "/auth/verify-email",
    response_model=AuthActionResponse,
    tags=["auth"],
)
def verify_email_route(
    payload: EmailTokenConfirmRequest,
    session: SessionDependency,
) -> AuthActionResponse:
    """使用一次性令牌验证邮箱所有权。"""

    try:
        verify_email_token(session, payload.token)
    except EmailTokenInvalidError as error:
        raise HTTPException(status_code=400, detail="验证链接无效或已过期") from error
    return AuthActionResponse(status="ok")


@router.post(
    "/auth/password-reset/request",
    response_model=AuthActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["auth"],
)
def request_password_reset_route(
    payload: EmailTokenRequest,
    session: SessionDependency,
    settings: SettingsDependency,
) -> AuthActionResponse:
    """请求密码重置链接；结果不暴露邮箱是否注册。"""

    token_result = request_password_reset_token(session, settings, payload.email)
    if token_result is None:
        return AuthActionResponse(status="ok")
    _, reset_token = token_result
    try:
        send_auth_email(settings, payload.email, "password_reset", reset_token)
    except EmailDeliveryError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return AuthActionResponse(status="ok")


@router.post(
    "/auth/password-reset",
    response_model=AuthActionResponse,
    tags=["auth"],
)
def reset_password_route(
    payload: PasswordResetConfirmRequest,
    session: SessionDependency,
) -> AuthActionResponse:
    """使用一次性令牌设置新密码并撤销旧会话。"""

    try:
        reset_password_with_token(session, payload.token, payload.password)
    except EmailTokenInvalidError as error:
        raise HTTPException(status_code=400, detail="重置链接无效或已过期") from error
    return AuthActionResponse(status="ok")


@router.post(
    "/auth/password-change",
    response_model=AuthActionResponse,
    tags=["auth"],
)
def change_password_route(
    payload: PasswordChangeRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    user_id: UserDependency,
) -> AuthActionResponse:
    """登录后使用当前密码修改登录密码，完成后要求重新登录。"""

    try:
        change_password(
            session, settings, user_id, payload.current_password, payload.password,
        )
    except InvalidEmailCredentialsError as error:
        # 当前 Bearer 会话仍有效，密码校验失败使用 400，避免客户端误退出登录。
        raise HTTPException(status_code=400, detail="当前密码不正确") from error
    except PasswordChangeUnavailableError as error:
        raise HTTPException(
            status_code=400, detail="当前账号未设置邮箱登录密码",
        ) from error
    except LoginRateLimitedError as error:
        raise HTTPException(
            status_code=429,
            detail="密码尝试次数过多，请稍后重试",
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    return AuthActionResponse(status="ok")


@router.get("/auth/{provider}/authorize", tags=["auth"])
def authorize_third_party_login(
    provider: AuthProvider,
    request: Request,
    settings: SettingsDependency,
    redirect_to: str | None = Query(default=None, max_length=2048),
) -> RedirectResponse:
    """跳转到微信、Google 或 Apple 的 OAuth 授权页。"""

    try:
        post_login_uri = resolve_post_login_uri(settings, redirect_to)
        state = sign_state(settings, provider, post_login_uri)
        authorization_url = build_authorization_url(
            settings,
            provider,
            str(request.url.replace(query="")),
            state,
        )
    except AuthProviderDisabledError as error:
        raise HTTPException(status_code=404, detail="该登录方式未配置") from error
    except AuthProviderError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(url=authorization_url, status_code=302)


@router.get("/auth/{provider}/callback", tags=["auth"])
async def third_party_login_callback(
    provider: AuthProvider,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> RedirectResponse:
    """处理 OAuth 提供方的 GET 回调。"""

    return await _handle_auth_callback(provider, request, session, settings)


@router.post("/auth/{provider}/callback", tags=["auth"])
async def third_party_login_form_callback(
    provider: AuthProvider,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
) -> RedirectResponse:
    """处理 Apple 登录的 POST 表单回调。"""

    return await _handle_auth_callback(provider, request, session, settings)


@router.post(
    "/auth/dev-login",
    response_model=AuthSessionResponse,
    tags=["auth"],
    include_in_schema=False,
)
def dev_login(
    session: SessionDependency,
    settings: SettingsDependency,
) -> AuthSessionResponse:
    """仅在显式开启本地开发模式时签发登录会话。"""

    if not settings.auth_dev_mode:
        raise HTTPException(status_code=404, detail="开发登录未启用")
    created = create_dev_session(session, settings)
    return AuthSessionResponse(
        access_token=created.token,
        expires_at=created.session.expires_at,
        user=AuthUserResponse.model_validate(created.user),
    )


@router.get("/auth/me", response_model=AuthUserResponse, tags=["auth"])
def read_current_auth_user(
    session: SessionDependency,
    user_id: UserDependency,
) -> AuthUserResponse:
    """返回当前登录用户。"""

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="当前用户不存在")
    return AuthUserResponse.model_validate(user)


@router.post("/auth/logout", response_model=AuthLogoutResponse, tags=["auth"])
def logout(
    session: SessionDependency,
    user_id: UserDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthLogoutResponse:
    """撤销当前 Bearer 登录会话。"""

    if not authorization:
        return AuthLogoutResponse(revoked=False)
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return AuthLogoutResponse(revoked=False)
    return AuthLogoutResponse(revoked=revoke_session(session, token.strip()))
