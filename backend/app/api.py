"""Memo API 路由。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from urllib.parse import parse_qsl, urlencode
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth_service import (
    AuthProviderDisabledError,
    AuthProviderError,
    AuthStateError,
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    EmailTokenInvalidError,
    InvalidEmailCredentialsError,
    LoginRateLimitedError,
    PasswordChangeUnavailableError,
    VerificationCodeInvalidError,
    VerificationCodeRateLimitedError,
    build_authorization_url,
    change_password,
    consume_verification_code,
    create_dev_session,
    ensure_email_available,
    exchange_authorization_code,
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
    verify_email_token,
    verify_state,
)
from app.bookmark_service import (
    BookmarkBatchNotFoundError,
    BookmarkBatchStateError,
    create_bookmark_batch,
    preview_bookmarks,
    process_bookmark_batch_in_background,
    read_bookmark_batch,
    retry_bookmark_batch,
    undo_bookmark_batch,
)
from app.browser_capture_service import (
    BrowserBookmarkRevisionConflictError,
    BrowserCaptureConsumedError,
    BrowserCaptureExpiredError,
    BrowserCaptureNotFoundError,
    BrowserCaptureOriginError,
    create_browser_capture,
    exchange_browser_capture,
    list_open_browser_tabs,
    read_browser_bookmark_snapshot,
    sync_browser_bookmark_delta,
    sync_browser_bookmarks,
    sync_open_browser_tabs,
)
from app.browser_extension_service import (
    browser_extension_archive_filename,
    build_browser_extension_archive,
)
from app.browser_history_service import (
    BrowserHistoryOriginError,
    HistoryDeviceMergeError,
    HistoryDeviceNotFoundError,
    clear_browser_history,
    delete_history_device,
    history_extended_search_enabled,
    list_browser_history,
    merge_history_devices,
    rename_history_device,
    sync_browser_history,
    update_history_extended_search,
)
from app.category_generation_service import (
    CategoryGenerationNotConfiguredError,
    CategoryGenerationUnavailableError,
    generate_category_suggestions,
)
from app.category_service import (
    CategoryCodeNotFoundError,
    CategoryNameConflictError,
    CategoryParentError,
    CategoryRuleNotFoundError,
    CategoryTemplateNotFoundError,
    CategoryVersionConflictError,
    category_code_exists,
    category_label,
    category_template_to_option,
    create_category_rule,
    create_category_template,
    delete_category_rule,
    delete_category_template,
    library_pages_for_generation,
    list_category_rules,
    list_resource_category_options,
    serialize_category_templates,
    update_category_rule,
    update_category_template,
)
from app.cloud_account_service import (
    CloudAccountExistsError,
    CloudAccountNotFoundError,
    CloudCredentialRejectedError,
    create_cloud_account,
    delete_cloud_account,
    list_cloud_accounts,
    verify_cloud_account,
)
from app.cloud_drive import UnsupportedProviderError
from app.config import Settings, normalize_image_ocr_provider
from app.database import is_sqlite_lock_error
from app.dependencies import get_current_user_id, get_session, get_settings
from app.ebook_service import (
    EbookJobNotFoundError,
    EbookJobStateError,
    EbookLinkError,
    create_ebook_job,
    get_ebook_job,
    list_ebook_jobs,
    process_ebook_job_in_background,
    retry_ebook_job,
)
from app.email_service import (
    EmailDeliveryError,
    send_auth_email,
    send_verification_code_email,
)
from app.export_service import serialize_memos_csv, serialize_memos_markdown
from app.image_ocr_service import (
    mark_image_ocr_pending,
    process_image_ocr_in_background,
    recognize_image_ocr,
)
from app.import_service import (
    MAX_LIBRARY_IMPORT_BYTES,
    LibraryImportFormatError,
    LibraryImportTooLargeError,
    import_library_memos,
    parse_library_import,
)
from app.link_health_service import (
    apply_link_health_action,
    check_resource_link,
    get_link_health_settings,
    list_link_health_center,
    update_link_health_settings,
    update_link_health_site_pause,
)
from app.meeting_service import (
    MeetingSummaryNotConfiguredError,
    MeetingSummaryUnavailableError,
    summarize_meeting,
)
from app.memo_deletion_service import sync_change_page
from app.model_settings_service import resolve_model_settings
from app.models import Memo, MemoDeletion, ResourceCategoryRule, User
from app.resource_processing import UnsafeResourceUrlError
from app.resource_service import (
    apply_user_category_rules_in_background,
    enrich_resource,
    enrich_resource_in_background,
    reclassify_user_rule_resources_in_background,
)
from app.schemas import (
    AuthActionResponse,
    AuthLogoutResponse,
    AuthProvider,
    AuthProviderInfo,
    AuthProvidersResponse,
    AuthSessionResponse,
    AuthUserResponse,
    BookmarkImportBatchRead,
    BookmarkImportPreview,
    BookmarkImportRequest,
    BrowserBookmarkDeltaSyncRequest,
    BrowserBookmarkSnapshotRead,
    BrowserBookmarkSyncRequest,
    BrowserBookmarkSyncResponse,
    BrowserCaptureContext,
    BrowserCaptureCreate,
    BrowserCaptureCreated,
    BrowserCaptureExchangeRequest,
    BrowserHistoryDeviceMerge,
    BrowserHistoryDeviceRead,
    BrowserHistoryDeviceUpdate,
    BrowserHistoryListResponse,
    BrowserHistorySettingsRead,
    BrowserHistorySettingsUpdate,
    BrowserHistorySyncRequest,
    BrowserHistorySyncResponse,
    BrowserOpenTabListResponse,
    BrowserOpenTabRead,
    BrowserTabSyncRequest,
    BrowserTabSyncResponse,
    CloudAccountCreate,
    CloudAccountRead,
    EbookJobCreate,
    EbookJobRead,
    EmailLoginRequest,
    EmailRegisterRequest,
    EmailRegisterResponse,
    EmailTokenConfirmRequest,
    EmailTokenRequest,
    LinkHealthActionRequest,
    LinkHealthListResponse,
    LinkHealthSettingsUpdate,
    LinkHealthSitePauseRequest,
    LinkHealthStatus,
    MeetingSummaryRequest,
    MeetingSummaryResponse,
    MemoCountsResponse,
    MemoCreate,
    MemoListResponse,
    MemoRead,
    MemoSort,
    MemoStatus,
    MemoType,
    MemoUpdate,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    ResourceCategoryCreate,
    ResourceCategoryGenerateRequest,
    ResourceCategoryGenerateResponse,
    ResourceCategoryRead,
    ResourceCategoryRuleCreate,
    ResourceCategoryRuleRead,
    ResourceCategoryRuleUpdate,
    ResourceCategoryUpdate,
    ResourceKind,
    ResourceOpenRead,
    ResourceQuickAccessRead,
    ResourceQuickAccessUpdate,
    ResourceReadingStatus,
    ReviewQueueResponse,
    ReviewSettingsResponse,
    ReviewSettingsUpdate,
    ReviewSkipRequest,
    SpeechTtsRequest,
    SyncResponse,
    VerificationCodeRequest,
    WordDictionarySenseRead,
    WordImportErrorRead,
    WordImportResponse,
    WordLookupRequest,
    WordLookupResponse,
    WordMergeRequest,
    WordReviewRequest,
)
from app.service import (
    MAX_IMAGE_BYTES,
    AudioValidationError,
    ImageValidationError,
    MemoNotFoundError,
    MemoNotTrashedError,
    MemoTypeError,
    MemoVersionConflictError,
    ResourceDuplicateError,
    WordDuplicateError,
    attach_audio,
    attach_image,
    count_memos,
    count_memos_by_type,
    create_memo,
    empty_trash,
    get_audio_path,
    get_image_path,
    get_memo,
    get_review_settings,
    is_trash_expired,
    list_memos,
    list_memos_for_export,
    list_quick_access,
    list_review_queue,
    merge_word,
    move_memo_to_trash,
    permanently_delete_memo,
    purge_expired_trash,
    record_resource_open,
    restore_all_trash,
    restore_memo,
    review_word,
    set_resource_quick_access_hidden,
    skip_review_item,
    update_memo,
    update_review_settings,
)
from app.speech_service import (
    SpeechServiceUnavailableError,
    SpeechTextTooLongError,
    synthesize_speech,
)
from app.word_import_service import (
    MAX_WORD_IMPORT_BYTES,
    WordImportFormatError,
    WordImportTooLargeError,
    build_word_import_payload,
    is_word_record,
    parse_word_import,
)
from app.word_service import (
    WordDictionaryUnavailableError,
    enrich_word,
    enrich_word_in_background,
    lookup_word_preview,
    normalize_word_lemma,
)

# 记录「这台机器」的设备 ID Cookie。一年有效，覆盖绝大多数重装场景。
# 由服务端下发 HttpOnly，避免页面脚本读取，也避开 Safari 对 JS Cookie 的 7 天限制。
HISTORY_DEVICE_COOKIE = "memoisle_device"
HISTORY_DEVICE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60

router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


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


def resource_category_rule_read(
    session: Session,
    user_id: str,
    rule: ResourceCategoryRule,
) -> ResourceCategoryRuleRead:
    """将数据库规则补充分类名称后返回给客户端。"""

    return ResourceCategoryRuleRead(
        id=rule.id,
        name=rule.name,
        category_code=rule.category_code,
        category_label=category_label(session, user_id, rule.category_code)
        or rule.category_code,
        match_type=rule.match_type,
        pattern=rule.pattern,
        priority=rule.priority,
        enabled=rule.enabled,
        version=rule.version,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """提供部署和开发环境健康检查。"""

    return {"status": "ok"}


@router.get("/auth/providers", response_model=AuthProvidersResponse, tags=["auth"])
def read_auth_providers(settings: SettingsDependency) -> AuthProvidersResponse:
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
        code = prepare_verification_code(session, settings, payload.email)
        send_verification_code_email(settings, payload.email, code)
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
        )
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(status_code=409, detail="该邮箱已被注册") from error
    except VerificationCodeInvalidError as error:
        raise HTTPException(status_code=400, detail="验证码无效或已过期") from error
    return EmailRegisterResponse(
        user=AuthUserResponse.model_validate(created),
    )


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


def _prepare_export_data(
    session: Session,
    user_id: str,
    settings: Settings,
) -> tuple[User, list[Memo], datetime]:
    """清理过期回收站并读取当前账号可导出的数据。"""

    # 导出的数据必须遵循回收站保留期，避免把已永久删除内容重新带出。
    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="当前用户不存在")
    exported_at = datetime.now(UTC)
    return user, list_memos_for_export(session, user_id), exported_at


async def _read_request_body_limited(request: Request, max_bytes: int) -> bytes:
    """按块读取请求体，超过上限立即中断，不依赖 Content-Length。"""

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="备份文件不能超过 10 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _export_headers(filename: str) -> dict[str, str]:
    """为私人导出响应设置下载文件名和缓存策略。"""

    return {
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }


@router.get("/exports/json", tags=["exports"])
def export_json_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> Response:
    """下载当前用户的 JSON 数据副本，不包含访问令牌和录音二进制。"""

    user, memos, exported_at = _prepare_export_data(session, user_id, settings)
    payload = {
        "format": "memoisle-json",
        "version": 1,
        "exported_at": exported_at.isoformat().replace("+00:00", "Z"),
        "audio_files_included": False,
        "image_files_included": False,
        "user": AuthUserResponse.model_validate(user).model_dump(mode="json"),
        "categories": serialize_category_templates(session, user_id),
        "memos": [
            MemoRead.model_validate(memo).model_dump(mode="json") for memo in memos
        ],
    }
    filename = f"memoisle-export-{exported_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    # 不缓存私人数据；响应中只放可迁移的条目字段，不暴露内部音频存储名。
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers=_export_headers(filename),
    )


@router.get("/exports/csv", tags=["exports"])
def export_csv_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> Response:
    """下载当前用户的完整 CSV 数据副本。"""

    _, memos, exported_at = _prepare_export_data(session, user_id, settings)
    filename = f"memoisle-export-{exported_at.strftime('%Y%m%dT%H%M%SZ')}.csv"
    return Response(
        content=serialize_memos_csv(memos),
        media_type="text/csv; charset=utf-8",
        headers=_export_headers(filename),
    )


@router.get("/exports/markdown", tags=["exports"])
def export_markdown_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> Response:
    """下载当前用户的可读 Markdown 数据副本。"""

    _, memos, exported_at = _prepare_export_data(session, user_id, settings)
    filename = f"memoisle-export-{exported_at.strftime('%Y%m%dT%H%M%SZ')}.md"
    return Response(
        content=serialize_memos_markdown(memos),
        media_type="text/markdown; charset=utf-8",
        headers=_export_headers(filename),
    )


@router.post(
    "/imports",
    response_model=WordImportResponse,
    tags=["exports"],
)
async def import_library_route(
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
    file_format: Annotated[str, Query(alias="format")] = "json",
) -> WordImportResponse:
    """导入 JSON 或 CSV 备份，按 client_id、词形和网址跳过重复项。"""

    if file_format.strip().lower() == "markdown":
        raise HTTPException(
            status_code=422,
            detail="Markdown 仅供阅读，完整恢复请使用 JSON 或 CSV 备份",
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 无效",
            ) from error
        if declared_size > MAX_LIBRARY_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="备份文件不能超过 10 MB")

    content = await _read_request_body_limited(request, MAX_LIBRARY_IMPORT_BYTES)
    try:
        parsed = parse_library_import(content, file_format)
        result = import_library_memos(session, user_id, parsed)
    except LibraryImportTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except LibraryImportFormatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return WordImportResponse(
        total_count=result.total_count,
        imported_count=result.imported_count,
        duplicate_count=result.duplicate_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        errors=[
            WordImportErrorRead(row=row, message=message)
            for row, message in result.errors
        ],
    )


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


@router.api_route(
    "/android/download",
    methods=["GET", "HEAD"],
    response_class=FileResponse,
    tags=["android"],
)
def download_android_route(settings: SettingsDependency) -> FileResponse:
    """公开下载已发布的签名 APK，支持手机浏览器及断点续传。"""

    if not settings.android_apk_path.is_file():
        raise HTTPException(status_code=404, detail="安卓安装包暂未发布")
    return FileResponse(
        settings.android_apk_path,
        media_type="application/vnd.android.package-archive",
        filename="MemoIsle-android.apk",
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.get(
    "/browser-extension/download",
    response_class=Response,
    tags=["browser-extension"],
)
def download_browser_extension_route() -> Response:
    """下载可解压后加载到 Chrome 或 Edge 的扩展包。"""

    archive = build_browser_extension_archive()
    filename = browser_extension_archive_filename()
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/browser-captures",
    response_model=BrowserCaptureCreated,
    status_code=status.HTTP_201_CREATED,
    tags=["browser-captures"],
)
def create_browser_capture_route(
    payload: BrowserCaptureCreate,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserCaptureCreated:
    """接收扩展明确授权的当前页并签发短时一次性凭据。"""

    try:
        return create_browser_capture(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except (UnsafeResourceUrlError, ValueError) as error:
        raise HTTPException(status_code=422, detail="当前网页不支持收藏") from error


@router.post(
    "/browser-captures/exchange",
    response_model=BrowserCaptureContext,
    tags=["browser-captures"],
)
def exchange_browser_capture_route(
    payload: BrowserCaptureExchangeRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserCaptureContext:
    """由 Web 一次性换取扩展授权的网页附件。"""

    try:
        return exchange_browser_capture(session, user_id, payload.token)
    except BrowserCaptureNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页授权不存在") from error
    except BrowserCaptureExpiredError as error:
        raise HTTPException(
            status_code=410,
            detail="网页授权已过期，请重新点击扩展",
        ) from error
    except BrowserCaptureConsumedError as error:
        raise HTTPException(status_code=409, detail="网页授权已经使用") from error


@router.post(
    "/browser-tabs/sync",
    response_model=BrowserTabSyncResponse,
    tags=["browser-tabs"],
)
def sync_browser_tabs_route(
    payload: BrowserTabSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserTabSyncResponse:
    """接收扩展同步的当前浏览器打开标签页快照。"""

    try:
        synced_count = sync_open_browser_tabs(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail="浏览器标签页快照无效") from error
    except OperationalError as error:
        if is_sqlite_lock_error(error):
            raise HTTPException(
                status_code=503,
                detail="浏览器标签页同步繁忙",
            ) from error
        raise
    return BrowserTabSyncResponse(synced_count=synced_count)


@router.get(
    "/browser-tabs/open",
    response_model=BrowserOpenTabListResponse,
    tags=["browser-tabs"],
)
def list_open_browser_tabs_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BrowserOpenTabListResponse:
    """读取当前浏览器正在打开、且可安全收藏的网页。"""

    items = list_open_browser_tabs(session, user_id, limit=limit)
    return BrowserOpenTabListResponse(
        items=[BrowserOpenTabRead.model_validate(item) for item in items]
    )


@router.post(
    "/browser-bookmarks/sync",
    response_model=BrowserBookmarkSyncResponse,
    tags=["browser-bookmarks"],
)
def sync_browser_bookmarks_route(
    payload: BrowserBookmarkSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSyncResponse:
    """接收扩展直接读取的当前浏览器书签树快照。"""

    try:
        snapshot = sync_browser_bookmarks(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    return BrowserBookmarkSyncResponse(
        synced_count=len(snapshot.bookmarks),
        truncated=snapshot.truncated,
        total_count=snapshot.total_count,
        revision=snapshot.revision,
    )


@router.post(
    "/browser-bookmarks/delta",
    response_model=BrowserBookmarkSyncResponse,
    tags=["browser-bookmarks"],
)
def sync_browser_bookmark_delta_route(
    payload: BrowserBookmarkDeltaSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSyncResponse:
    """应用扩展书签增量；版本落后时要求扩展重新上传完整快照。"""

    try:
        snapshot = sync_browser_bookmark_delta(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserBookmarkRevisionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "bookmark_revision_conflict",
                "message": "书签快照已在其他设备更新，请重新同步",
            },
        ) from error
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return BrowserBookmarkSyncResponse(
        synced_count=len(snapshot.bookmarks),
        truncated=snapshot.truncated,
        total_count=snapshot.total_count,
        revision=snapshot.revision,
    )


@router.get(
    "/browser-bookmarks/current",
    response_model=BrowserBookmarkSnapshotRead,
    tags=["browser-bookmarks"],
)
def read_browser_bookmarks_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSnapshotRead:
    """向 Web 返回最近一次扩展同步的浏览器书签。"""

    return read_browser_bookmark_snapshot(session, user_id)


@router.post(
    "/browser-history/sync",
    response_model=BrowserHistorySyncResponse,
    tags=["browser-history"],
)
def sync_browser_history_route(
    payload: BrowserHistorySyncRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySyncResponse:
    """接收扩展上报的浏览器历史记录。"""

    # 设备 ID 同时写一份到 Cookie：扩展被卸载时 chrome.storage.local 会被清空，
    # 而 Cookie 不会，重装后靠它认出「还是这台机器」。
    # 由服务端下发 HttpOnly，避免页面脚本读取，也避开 Safari 对 JS Cookie
    # 的 7 天限制。
    cookie_device_id = request.cookies.get(HISTORY_DEVICE_COOKIE)
    try:
        result = sync_browser_history(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
            cookie_device_id=cookie_device_id,
        )
    except BrowserHistoryOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    if result.device_id and result.device_id != cookie_device_id:
        response.set_cookie(
            HISTORY_DEVICE_COOKIE,
            result.device_id,
            max_age=HISTORY_DEVICE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            # 扩展与 API 同站请求，无需跨站 Cookie。
            secure=request.url.scheme == "https",
            path="/",
        )
    return result


@router.get(
    "/browser-history",
    response_model=BrowserHistoryListResponse,
    tags=["browser-history"],
)
def list_browser_history_route(
    session: SessionDependency,
    user_id: UserDependency,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    tz_offset: Annotated[int | None, Query(ge=-840, le=840)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    device_id: Annotated[str | None, Query(max_length=64)] = None,
) -> BrowserHistoryListResponse:
    """向 Web 返回浏览历史；默认 30 天，只有账号开启扩展搜索才放宽。

    ``days=0`` 表示不限时间，同样需要账号已打开「搜索更久的历史」。
    ``from`` / ``to`` 按本地日期精确筛选，优先于天数窗口；
    ``tz_offset`` 是浏览器时区相对 UTC 的分钟数，用来划分「某一天」。
    深翻页时改传上一页返回的 ``next_cursor``，查询开销不再随深度增长。
    ``device_id`` 只看某台设备；不传则按网址合并同一账号下所有设备。
    """

    return list_browser_history(
        session,
        user_id,
        query_text=q,
        limit=limit,
        offset=offset,
        days=days,
        date_from=date_from,
        date_to=date_to,
        tz_offset_minutes=tz_offset,
        cursor=cursor,
        device_id=device_id,
    )


@router.get(
    "/browser-history/settings",
    response_model=BrowserHistorySettingsRead,
    tags=["browser-history"],
)
def read_browser_history_settings_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySettingsRead:
    """读取账号是否允许搜索更久的浏览历史。"""

    return BrowserHistorySettingsRead(
        extended_search_enabled=history_extended_search_enabled(session, user_id),
    )


@router.patch(
    "/browser-history/settings",
    response_model=BrowserHistorySettingsRead,
    tags=["browser-history"],
)
def update_browser_history_settings_route(
    payload: BrowserHistorySettingsUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySettingsRead:
    """打开或关闭「搜索更久的历史」。"""

    return BrowserHistorySettingsRead(
        extended_search_enabled=update_history_extended_search(
            session,
            user_id,
            payload,
        ),
    )


@router.delete(
    "/browser-history",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["browser-history"],
)
def clear_browser_history_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> Response:
    """清空当前账号的浏览历史；已收藏进资料库的网页不受影响。"""

    clear_browser_history(session, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/browser-history/devices/{device_id}",
    response_model=BrowserHistoryDeviceRead,
    tags=["browser-history"],
)
def rename_browser_history_device_route(
    device_id: str,
    payload: BrowserHistoryDeviceUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistoryDeviceRead:
    """给设备改名，便于区分两台同款电脑。"""

    try:
        state = rename_history_device(
            session,
            user_id,
            device_id,
            payload.device_name,
        )
    except HistoryDeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在。",
        ) from error
    return BrowserHistoryDeviceRead(
        device_id=state.device_id,
        device_name=state.device_name,
        total_count=state.total_count,
        synced_at=state.synced_at,
    )


@router.delete(
    "/browser-history/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["browser-history"],
)
def delete_browser_history_device_route(
    device_id: str,
    session: SessionDependency,
    user_id: UserDependency,
) -> Response:
    """删除一台设备及其历史，其他设备不受影响。"""

    try:
        delete_history_device(session, user_id, device_id)
    except HistoryDeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在。",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/browser-history/devices/{device_id}/merge",
    response_model=BrowserHistorySyncResponse,
    tags=["browser-history"],
)
def merge_browser_history_device_route(
    device_id: str,
    payload: BrowserHistoryDeviceMerge,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySyncResponse:
    """把一台设备的历史并进另一台，用于确认「同一台机器重装」。"""

    try:
        moved, total = merge_history_devices(
            session,
            user_id,
            device_id,
            payload.target_device_id,
        )
    except HistoryDeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在。",
        ) from error
    except HistoryDeviceMergeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能把设备合并到它自己。",
        ) from error
    return BrowserHistorySyncResponse(
        synced_count=moved,
        total_count=total,
        device_id=payload.target_device_id,
    )


@router.post(
    "/memos",
    response_model=MemoRead,
    status_code=status.HTTP_201_CREATED,
    tags=["memos"],
)
def create_memo_route(
    payload: MemoCreate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """创建或返回同一客户端标识对应的条目。"""

    if (
        session.scalar(
            select(MemoDeletion.memo_id).where(
                MemoDeletion.user_id == user_id,
                MemoDeletion.client_id == str(payload.client_id),
            )
        )
        is not None
    ):
        raise HTTPException(
            status_code=410,
            detail="该条目已永久删除，请使用新的收藏标识",
        )
    try:
        memo = create_memo(session, user_id, payload)
    except WordDuplicateError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "code": "duplicate_lemma",
                "current": current.model_dump(mode="json"),
            },
        ) from error
    except ResourceDuplicateError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "code": "duplicate_resource",
                "current": current.model_dump(mode="json"),
            },
        ) from error
    if (
        memo.type == MemoType.RESOURCE
        and settings.resource_enrichment_enabled
        and memo.resource_metadata_status in {"pending", "failed"}
    ):
        background_tasks.add_task(
            enrich_resource_in_background,
            settings.database_url,
            user_id,
            memo.id,
            settings,
        )
    if memo.type == MemoType.WORD and settings.word_dictionary_enabled:
        background_tasks.add_task(
            enrich_word_in_background,
            settings.database_url,
            user_id,
            memo.id,
            settings,
        )
    return MemoRead.model_validate(memo)


@router.post(
    "/resources/{memo_id}/enrich",
    response_model=MemoRead,
    tags=["resources"],
)
def enrich_resource_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """手动重试网页元数据与自动分类。"""

    try:
        memo = enrich_resource(
            session,
            user_id,
            str(memo_id),
            settings,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页资料不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return MemoRead.model_validate(memo)


@router.get(
    "/resources/link-health",
    response_model=LinkHealthListResponse,
    tags=["resources"],
)
def list_link_health_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    health_status: Annotated[
        LinkHealthStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LinkHealthListResponse:
    """读取失效、重定向、变化和暂时失败的网页资料。"""

    items, counts = list_link_health_center(
        session,
        user_id,
        health_status,
        limit,
        offset=offset,
    )
    return LinkHealthListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        counts=counts,
        settings=get_link_health_settings(session, user_id, settings),
    )


@router.patch(
    "/resources/link-health/settings",
    response_model=LinkHealthListResponse,
    tags=["resources"],
)
def update_link_health_settings_route(
    payload: LinkHealthSettingsUpdate,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> LinkHealthListResponse:
    """更新账号级巡检设置并返回最新巡检中心。"""

    try:
        health_settings = update_link_health_settings(
            session,
            user_id,
            payload,
            settings,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    items, counts = list_link_health_center(session, user_id)
    return LinkHealthListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        counts=counts,
        settings=health_settings,
    )


@router.post(
    "/resources/link-health/site-pauses",
    response_model=LinkHealthListResponse,
    tags=["resources"],
)
def update_link_health_site_pause_route(
    payload: LinkHealthSitePauseRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> LinkHealthListResponse:
    """暂停或恢复当前账号下某个网站的巡检。"""

    health_settings = update_link_health_site_pause(
        session,
        user_id,
        payload,
        settings,
    )
    items, counts = list_link_health_center(session, user_id)
    return LinkHealthListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        counts=counts,
        settings=health_settings,
    )


@router.post(
    "/resources/{memo_id}/link-checks",
    response_model=MemoRead,
    tags=["resources"],
)
def check_resource_link_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """人工触发一次带 SSRF 防护的网页链接检查。"""

    try:
        memo = check_resource_link(
            session,
            user_id,
            str(memo_id),
            settings,
            expected_version=expected_version,
            force=True,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页资料不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/resources/{memo_id}/link-health-actions",
    response_model=MemoRead,
    tags=["resources"],
)
def apply_link_health_action_route(
    memo_id: UUID,
    payload: LinkHealthActionRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """处理一条巡检提醒。"""

    try:
        memo = apply_link_health_action(
            session,
            user_id,
            str(memo_id),
            payload,
            settings,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页资料不存在") from error
    except (MemoTypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/bookmark-imports/preview",
    response_model=BookmarkImportPreview,
    tags=["bookmark-imports"],
)
def preview_bookmark_import_route(
    payload: BookmarkImportRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> BookmarkImportPreview:
    """校验浏览器本地解析的书签，并返回去重预览。"""

    return preview_bookmarks(session, user_id, payload)


@router.post(
    "/bookmark-imports",
    response_model=BookmarkImportBatchRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["bookmark-imports"],
)
def create_bookmark_import_route(
    payload: BookmarkImportRequest,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> BookmarkImportBatchRead:
    """确认并异步处理一个 Chrome 书签导入批次。"""

    batch = create_bookmark_batch(session, user_id, payload)
    response = read_bookmark_batch(session, user_id, batch.id)
    background_tasks.add_task(
        process_bookmark_batch_in_background,
        settings.database_url,
        user_id,
        batch.id,
        settings,
    )
    return response


@router.get(
    "/bookmark-imports/{batch_id}",
    response_model=BookmarkImportBatchRead,
    tags=["bookmark-imports"],
)
def get_bookmark_import_route(
    batch_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> BookmarkImportBatchRead:
    """读取书签导入批次进度和逐项结果。"""

    try:
        return read_bookmark_batch(session, user_id, str(batch_id))
    except BookmarkBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail="书签导入批次不存在") from error


@router.post(
    "/bookmark-imports/{batch_id}/retry",
    response_model=BookmarkImportBatchRead,
    tags=["bookmark-imports"],
)
def retry_bookmark_import_route(
    batch_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> BookmarkImportBatchRead:
    """重新处理书签导入批次中的失败项目。"""

    try:
        retry_bookmark_batch(
            session,
            user_id,
            str(batch_id),
            settings,
        )
        return read_bookmark_batch(session, user_id, str(batch_id))
    except BookmarkBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail="书签导入批次不存在") from error
    except BookmarkBatchStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/bookmark-imports/{batch_id}/undo",
    response_model=BookmarkImportBatchRead,
    tags=["bookmark-imports"],
)
def undo_bookmark_import_route(
    batch_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> BookmarkImportBatchRead:
    """撤销本批导入且尚未被用户编辑的网页资料。"""

    try:
        undo_bookmark_batch(session, user_id, str(batch_id))
        return read_bookmark_batch(session, user_id, str(batch_id))
    except BookmarkBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail="书签导入批次不存在") from error


@router.get("/memos", response_model=MemoListResponse, tags=["memos"])
def list_memos_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    memo_type: Annotated[MemoType | None, Query(alias="type")] = None,
    query_text: Annotated[str | None, Query(alias="q", max_length=200)] = None,
    resource_category: Annotated[
        str | None,
        Query(alias="category", max_length=50),
    ] = None,
    resource_kind: Annotated[
        ResourceKind | None,
        Query(alias="resource_kind"),
    ] = None,
    resource_reading_status: Annotated[
        ResourceReadingStatus | None,
        Query(alias="reading_status"),
    ] = None,
    link_health_status: Annotated[
        LinkHealthStatus | None,
        Query(alias="health"),
    ] = None,
    tag: Annotated[str | None, Query(max_length=100)] = None,
    collection: Annotated[str | None, Query(max_length=100)] = None,
    starred: Annotated[bool | None, Query()] = None,
    memo_status: Annotated[MemoStatus | None, Query(alias="status")] = None,
    created_from: Annotated[date | None, Query()] = None,
    created_to: Annotated[date | None, Query()] = None,
    sort: Annotated[MemoSort, Query()] = MemoSort.UPDATED_DESC,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemoListResponse:
    """按类型及关键词读取当前用户条目。"""

    if memo_status == MemoStatus.TRASHED:
        purge_expired_trash(
            session,
            settings.audio_directory,
            settings.image_directory,
            settings.trash_retention_days,
            user_id=user_id,
        )
    normalized_health_status = (
        link_health_status.value if link_health_status is not None else None
    )
    normalized_created_from = (
        datetime.combine(created_from, time.min, tzinfo=UTC)
        if created_from is not None
        else None
    )
    normalized_created_to = (
        datetime.combine(created_to, time.min, tzinfo=UTC) + timedelta(days=1)
        if created_to is not None
        else None
    )
    items = list_memos(
        session,
        user_id,
        memo_type=memo_type,
        query_text=query_text,
        resource_category=resource_category,
        resource_kind=resource_kind,
        resource_reading_status=resource_reading_status,
        link_health_status=normalized_health_status,
        tag=tag,
        collection=collection,
        starred=starred,
        memo_status=memo_status,
        created_from=normalized_created_from,
        created_to=normalized_created_to,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    total_count = count_memos(
        session,
        user_id,
        memo_type=memo_type,
        query_text=query_text,
        resource_category=resource_category,
        resource_kind=resource_kind,
        resource_reading_status=resource_reading_status,
        link_health_status=normalized_health_status,
        tag=tag,
        collection=collection,
        starred=starred,
        memo_status=memo_status,
        created_from=normalized_created_from,
        created_to=normalized_created_to,
    )
    return MemoListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        total_count=total_count,
    )


@router.get("/memos/counts", response_model=MemoCountsResponse, tags=["memos"])
def count_memos_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoCountsResponse:
    """返回当前用户未删除内容的类型数量。"""

    counts = count_memos_by_type(session, user_id)
    return MemoCountsResponse(
        total_count=sum(counts.values()),
        word_count=counts[MemoType.WORD],
        resource_count=counts[MemoType.RESOURCE],
        idea_count=counts[MemoType.IDEA],
        image_count=counts[MemoType.IMAGE],
        inbox_count=count_memos(session, user_id, memo_status=MemoStatus.INBOX),
    )


@router.get(
    "/resource-categories",
    response_model=list[ResourceCategoryRead],
    tags=["resources"],
)
def list_resource_categories_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[ResourceCategoryRead]:
    """返回系统分类和当前用户的自定义分类模板。"""

    return [
        ResourceCategoryRead.model_validate(option)
        for option in list_resource_category_options(session, user_id)
    ]


@router.post(
    "/resource-categories/generate",
    response_model=ResourceCategoryGenerateResponse,
    tags=["resources"],
)
def generate_resource_categories_route(
    payload: ResourceCategoryGenerateRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryGenerateResponse:
    """根据整理要求和收藏网页聚类，生成当前用户可添加的分类建议。"""

    existing = [
        ResourceCategoryRead.model_validate(option)
        for option in list_resource_category_options(session, user_id)
    ]
    library_pages = library_pages_for_generation(session, user_id)
    if not payload.instructions and not library_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请说明整理要求，或先收藏网页后再根据网页聚类",
        )
    try:
        return generate_category_suggestions(
            payload.instructions,
            existing,
            resolve_model_settings(session, user_id, settings),
            payload.max_categories,
            library_pages=library_pages,
            mode=payload.mode,
        )
    except CategoryGenerationNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except CategoryGenerationUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.post(
    "/resource-categories",
    response_model=ResourceCategoryRead,
    status_code=status.HTTP_201_CREATED,
    tags=["resources"],
)
def create_resource_category_route(
    payload: ResourceCategoryCreate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ResourceCategoryRead:
    """创建当前用户的自定义网页资料分类。"""

    try:
        template = create_category_template(
            session,
            user_id,
            payload.name,
            payload.description,
            payload.parent_code,
            definition=payload.definition,
            include_examples=payload.include_examples,
            exclude_examples=payload.exclude_examples,
        )
    except CategoryNameConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CategoryParentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ResourceCategoryRead.model_validate(
        category_template_to_option(session, user_id, template),
    )


@router.patch(
    "/resource-categories/{category_id}",
    response_model=ResourceCategoryRead,
    tags=["resources"],
)
def update_resource_category_route(
    category_id: UUID,
    payload: ResourceCategoryUpdate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryRead:
    """更新或停用当前用户的自定义网页资料分类。"""

    try:
        template = update_category_template(
            session,
            user_id,
            str(category_id),
            payload.expected_version,
            payload.model_dump(exclude_unset=True, exclude={"expected_version"}),
        )
    except CategoryTemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类模板不存在") from error
    except CategoryNameConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CategoryParentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CategoryVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error)},
        ) from error
    background_tasks.add_task(
        reclassify_user_rule_resources_in_background,
        settings.database_url,
        user_id,
        settings,
    )
    return ResourceCategoryRead.model_validate(
        category_template_to_option(session, user_id, template),
    )


@router.delete(
    "/resource-categories/{category_id}",
    response_model=dict[str, bool],
    tags=["resources"],
)
def delete_resource_category_route(
    category_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, bool]:
    """删除自定义分类模板，并重新判断原先使用该分类的资料。"""

    try:
        delete_category_template(session, user_id, str(category_id))
    except CategoryTemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类模板不存在") from error
    background_tasks.add_task(
        apply_user_category_rules_in_background,
        settings.database_url,
        user_id,
    )
    return {"deleted": True}


@router.get(
    "/resource-category-rules",
    response_model=list[ResourceCategoryRuleRead],
    tags=["resources"],
)
def list_resource_category_rules_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[ResourceCategoryRuleRead]:
    """返回当前用户的网页资料分类规则。"""

    return [
        resource_category_rule_read(session, user_id, rule)
        for rule in list_category_rules(session, user_id)
    ]


@router.post(
    "/resource-category-rules",
    response_model=ResourceCategoryRuleRead,
    status_code=status.HTTP_201_CREATED,
    tags=["resources"],
)
def create_resource_category_rule_route(
    payload: ResourceCategoryRuleCreate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryRuleRead:
    """创建规则并异步应用到已有网页资料。"""

    try:
        rule = create_category_rule(
            session,
            user_id,
            payload.name,
            payload.category_code,
            payload.match_type,
            payload.pattern,
            payload.priority,
            payload.enabled,
        )
    except CategoryCodeNotFoundError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    background_tasks.add_task(
        apply_user_category_rules_in_background,
        settings.database_url,
        user_id,
    )
    return resource_category_rule_read(session, user_id, rule)


@router.patch(
    "/resource-category-rules/{rule_id}",
    response_model=ResourceCategoryRuleRead,
    tags=["resources"],
)
def update_resource_category_rule_route(
    rule_id: UUID,
    payload: ResourceCategoryRuleUpdate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryRuleRead:
    """更新规则并重新处理受影响的资料。"""

    try:
        rule = update_category_rule(
            session,
            user_id,
            str(rule_id),
            payload.expected_version,
            payload.model_dump(exclude_unset=True, exclude={"expected_version"}),
        )
    except CategoryRuleNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类规则不存在") from error
    except CategoryCodeNotFoundError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CategoryVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error)},
        ) from error
    background_tasks.add_task(
        reclassify_user_rule_resources_in_background,
        settings.database_url,
        user_id,
        settings,
    )
    return resource_category_rule_read(session, user_id, rule)


@router.delete(
    "/resource-category-rules/{rule_id}",
    response_model=dict[str, bool],
    tags=["resources"],
)
def delete_resource_category_rule_route(
    rule_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, bool]:
    """删除规则并重新处理原先由用户规则分类的资料。"""

    try:
        delete_category_rule(session, user_id, str(rule_id))
    except CategoryRuleNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类规则不存在") from error
    background_tasks.add_task(
        reclassify_user_rule_resources_in_background,
        settings.database_url,
        user_id,
        settings,
    )
    return {"deleted": True}


@router.delete(
    "/memos/trash",
    tags=["memos"],
)
def empty_trash_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, int]:
    """清空当前用户的回收站，返回永久删除的条目数。"""

    deleted = empty_trash(
        session,
        user_id,
        settings.audio_directory,
        settings.image_directory,
    )
    return {"deleted_count": deleted}


@router.post("/memos/trash/restore", tags=["memos"])
def restore_all_trash_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, int]:
    """还原当前账号的全部回收站条目，遵循已有保留期限。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    return {"restored_count": restore_all_trash(session, user_id)}


@router.get("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def get_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """读取一条内容。"""

    try:
        memo = get_memo(session, user_id, str(memo_id))
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    if is_trash_expired(memo, settings.trash_retention_days):
        permanently_delete_memo(
            session,
            user_id,
            memo.id,
            memo.version,
            settings.audio_directory,
            settings.image_directory,
        )
        raise HTTPException(status_code=404, detail="条目不存在")
    return MemoRead.model_validate(memo)


@router.patch("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def update_memo_route(
    memo_id: UUID,
    payload: MemoUpdate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """更新条目并检测跨设备版本冲突。"""

    category_codes = payload.resource_categories
    if category_codes is None and payload.resource_category is not None:
        category_codes = [payload.resource_category]
    if category_codes:
        try:
            for code in category_codes:
                if not category_code_exists(session, user_id, code):
                    raise CategoryCodeNotFoundError("分类不存在或已停用")
        except CategoryCodeNotFoundError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        memo = update_memo(session, user_id, str(memo_id), payload)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except WordDuplicateError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "code": "duplicate_lemma",
                "current": current.model_dump(mode="json"),
            },
        ) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    if (
        memo.type == MemoType.RESOURCE
        and settings.resource_enrichment_enabled
        and memo.resource_metadata_status in {"pending", "failed"}
    ):
        background_tasks.add_task(
            enrich_resource_in_background,
            settings.database_url,
            user_id,
            memo.id,
            settings,
        )
    if "resource_category" in payload.model_fields_set:
        memo.resource_category_label = (
            category_label(session, user_id, payload.resource_category)
            if payload.resource_category is not None
            else None
        )
        session.commit()
        session.refresh(memo)
    return MemoRead.model_validate(memo)


@router.delete("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def trash_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """把条目移入回收站。"""

    try:
        memo = move_memo_to_trash(
            session,
            user_id,
            str(memo_id),
            expected_version,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/resources/{memo_id}/open",
    response_model=ResourceOpenRead,
    tags=["resources"],
)
def record_resource_open_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> ResourceOpenRead:
    """记录一次打开原网页，用于快速访问排序。"""

    try:
        memo = record_resource_open(session, user_id, str(memo_id))
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ResourceOpenRead(
        resource_open_count=memo.resource_open_count,
        resource_last_opened_at=memo.resource_last_opened_at,
    )


@router.get(
    "/resources/quick-access",
    response_model=list[MemoRead],
    tags=["resources"],
)
def list_quick_access_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> list[MemoRead]:
    """快速访问：按打开次数排列常用网页，已移除的不出现。"""

    return [
        MemoRead.model_validate(memo)
        for memo in list_quick_access(session, user_id, limit)
    ]


@router.put(
    "/resources/{memo_id}/quick-access",
    response_model=ResourceQuickAccessRead,
    tags=["resources"],
)
def update_quick_access_route(
    memo_id: UUID,
    payload: ResourceQuickAccessUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ResourceQuickAccessRead:
    """从快速访问移除，或重新显示。"""

    try:
        memo = set_resource_quick_access_hidden(
            session, user_id, str(memo_id), payload.hidden,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ResourceQuickAccessRead(
        resource_quick_access_hidden=memo.resource_quick_access_hidden,
    )


@router.post("/memos/{memo_id}/restore", response_model=MemoRead, tags=["memos"])
def restore_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """从回收站恢复条目。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    try:
        memo = restore_memo(
            session,
            user_id,
            str(memo_id),
            expected_version,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoNotTrashedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.delete(
    "/memos/{memo_id}/permanent",
    response_model=AuthActionResponse,
    tags=["memos"],
)
def permanently_delete_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> AuthActionResponse:
    """永久删除回收站中的条目，需要客户端二次确认后调用。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    try:
        permanently_delete_memo(
            session,
            user_id,
            str(memo_id),
            expected_version,
            settings.audio_directory,
            settings.image_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoNotTrashedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return AuthActionResponse(status="deleted")


@router.get("/sync/changes", response_model=SyncResponse, tags=["sync"])
def sync_changes_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    cursor: Annotated[datetime | None, Query()] = None,
    cursor_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> SyncResponse:
    """按服务端更新时间返回增量同步数据。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    return sync_change_page(
        session,
        user_id,
        cursor,
        str(cursor_id) if cursor_id else None,
        limit,
    )


@router.get(
    "/review-settings",
    response_model=ReviewSettingsResponse,
    tags=["review"],
)
def read_review_settings_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> ReviewSettingsResponse:
    """返回当前账号的自定义复习计划。"""

    daily_limit, intervals_days = get_review_settings(session, user_id)
    return ReviewSettingsResponse(
        daily_limit=daily_limit,
        intervals_days=list(intervals_days),
    )


@router.patch(
    "/review-settings",
    response_model=ReviewSettingsResponse,
    tags=["review"],
)
def update_review_settings_route(
    payload: ReviewSettingsUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ReviewSettingsResponse:
    """更新当前账号的自定义复习计划。"""

    daily_limit, intervals_days = update_review_settings(
        session,
        user_id,
        payload,
    )
    return ReviewSettingsResponse(
        daily_limit=daily_limit,
        intervals_days=list(intervals_days),
    )


@router.get("/review-queue", response_model=ReviewQueueResponse, tags=["review"])
def review_queue_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    memo_type: Annotated[MemoType | None, Query(alias="type")] = None,
) -> ReviewQueueResponse:
    """返回今日回顾：到期单词、未读资料和待整理灵感。"""

    items, counts = list_review_queue(
        session,
        user_id,
        limit=limit,
        memo_type=memo_type,
    )
    return ReviewQueueResponse(
        items=[MemoRead.model_validate(item) for item in items],
        word_count=counts["word_count"],
        resource_count=counts["resource_count"],
        idea_count=counts["idea_count"],
        daily_limit=counts["daily_limit"],
        scheduled_count=counts["scheduled_count"],
    )


@router.post(
    "/review-queue/{memo_id}/skip",
    response_model=MemoRead,
    tags=["review"],
)
def skip_review_route(
    memo_id: UUID,
    payload: ReviewSkipRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """跳过当前回顾条目，明天之前不再出现。"""

    try:
        memo = skip_review_item(
            session,
            user_id,
            str(memo_id),
            payload.expected_version,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="内容不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/words/{memo_id}/merge",
    response_model=MemoRead,
    tags=["words"],
)
def merge_word_route(
    memo_id: UUID,
    payload: WordMergeRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """把新语境合并进已有单词，不新建重复词形。"""

    try:
        memo = merge_word(session, user_id, str(memo_id), payload)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="单词不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/words/import",
    response_model=WordImportResponse,
    tags=["words"],
)
async def import_words_route(
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    file_format: Annotated[str, Query(alias="format")] = "json",
) -> WordImportResponse:
    """导入 JSON 或 CSV 单词，只保留当前账号的单词内容。"""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 无效",
            ) from error
        if declared_size > MAX_WORD_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="单词导入文件不能超过 5 MB")

    content = await request.body()
    try:
        records = parse_word_import(content, file_format)
    except WordImportTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except WordImportFormatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    imported_count = 0
    duplicate_count = 0
    skipped_count = 0
    failed_count = 0
    errors: list[WordImportErrorRead] = []
    for record in records:
        if not is_word_record(record):
            # 允许直接回灌完整 MemoIsle JSON/CSV，只提取其中的 word 条目。
            skipped_count += 1
            continue
        try:
            payload = build_word_import_payload(record)
        except (TypeError, ValueError) as error:
            failed_count += 1
            if len(errors) < 50:
                message = str(error).strip() or "字段校验失败"
                errors.append(
                    WordImportErrorRead(
                        row=record.row_number,
                        message=message[:200],
                    )
                )
            continue

        existing = session.scalar(
            select(Memo).where(
                Memo.user_id == user_id,
                Memo.client_id == str(payload.client_id),
            )
        )
        if existing is not None:
            if existing.type == MemoType.WORD and existing.status != MemoStatus.TRASHED:
                duplicate_count += 1
                continue
            # client_id 已被其他类型或回收站条目占用时，换用新标识继续导入。
            payload = payload.model_copy(update={"client_id": uuid4()})
        try:
            memo = create_memo(session, user_id, payload)
        except WordDuplicateError:
            duplicate_count += 1
            continue
        imported_count += 1
        if settings.word_dictionary_enabled:
            background_tasks.add_task(
                enrich_word_in_background,
                settings.database_url,
                user_id,
                memo.id,
                settings,
            )

    return WordImportResponse(
        total_count=len(records),
        imported_count=imported_count,
        duplicate_count=duplicate_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        errors=errors,
    )


@router.post(
    "/words/lookup",
    response_model=WordLookupResponse,
    tags=["words"],
)
def lookup_word_route(
    payload: WordLookupRequest,
    _user_id: UserDependency,
    settings: SettingsDependency,
) -> WordLookupResponse:
    """查询单词并返回可由用户选择的中文释义预览。"""

    lemma = normalize_word_lemma(payload.word)
    if not lemma:
        raise HTTPException(status_code=422, detail="请输入有效的英语单词或短语")
    try:
        dictionary = lookup_word_preview(lemma, settings)
    except WordDictionaryUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return WordLookupResponse(
        word=payload.word,
        lemma=lemma,
        phonetic=dictionary.phonetic,
        us_audio_url=dictionary.us_audio_url,
        uk_audio_url=dictionary.uk_audio_url,
        senses=[
            WordDictionarySenseRead(
                index=index,
                part_of_speech=sense.part_of_speech,
                definition=sense.definition,
                example=sense.example,
            )
            for index, sense in enumerate(dictionary.senses)
        ],
        source_name=dictionary.source_name,
        source_url=dictionary.source_url,
    )


@router.post(
    "/words/{memo_id}/dictionary",
    response_model=MemoRead,
    tags=["words"],
)
def enrich_word_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """手动补全单词释义、音标、例句和英美音源。"""

    try:
        memo = enrich_word(session, user_id, str(memo_id), settings)
    except WordDictionaryUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/words/{memo_id}/reviews",
    response_model=MemoRead,
    tags=["review"],
)
def review_word_route(
    memo_id: UUID,
    payload: WordReviewRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """提交一次单词复习反馈。"""

    try:
        memo = review_word(session, user_id, str(memo_id), payload)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="单词不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post("/memos/{memo_id}/audio", response_model=MemoRead, tags=["audio"])
async def upload_memo_audio_route(
    memo_id: UUID,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
    duration_ms: Annotated[int | None, Header(alias="X-Audio-Duration-Ms")] = None,
) -> MemoRead:
    """接收原始音频字节并关联到一条灵感。"""

    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 无效",
            ) from error
        if declared_size > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="录音不能超过 20 MB")
    content = await request.body()
    try:
        memo = attach_audio(
            session=session,
            user_id=user_id,
            memo_id=str(memo_id),
            expected_version=expected_version,
            content=content,
            mime_type=content_type,
            duration_ms=duration_ms,
            audio_directory=settings.audio_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="灵感不存在") from error
    except (MemoTypeError, AudioValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.get("/memos/{memo_id}/audio", tags=["audio"])
def download_memo_audio_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """下载或播放当前用户的一条录音。"""

    try:
        memo, audio_path = get_audio_path(
            session,
            user_id,
            str(memo_id),
            settings.audio_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="录音不存在") from error
    return FileResponse(
        path=audio_path,
        media_type=memo.audio_mime_type or "application/octet-stream",
        filename=f"memoisle-{memo.id}.audio",
        content_disposition_type="inline",
    )


@router.post("/memos/{memo_id}/image", response_model=MemoRead, tags=["image"])
async def upload_memo_image_route(
    memo_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """接收原始图片字节并关联到一条图片收藏。"""

    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 无效",
            ) from error
        if declared_size > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="图片不能超过 20 MB")
    content = await request.body()
    try:
        memo = attach_image(
            session=session,
            user_id=user_id,
            memo_id=str(memo_id),
            expected_version=expected_version,
            content=content,
            mime_type=content_type,
            image_directory=settings.image_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="图片收藏不存在") from error
    except (MemoTypeError, ImageValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    if normalize_image_ocr_provider(settings.image_ocr_provider) != "none":
        # 图片落盘后再在后台识别；识别失败不影响图片本身已经保存。
        mark_image_ocr_pending(session, memo)
        background_tasks.add_task(
            process_image_ocr_in_background,
            settings.database_url,
            user_id,
            memo.id,
            settings,
        )
    return MemoRead.model_validate(memo)


@router.get("/memos/{memo_id}/image", tags=["image"])
def download_memo_image_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """查看当前用户图片收藏的原图。"""

    try:
        memo, image_path = get_image_path(
            session,
            user_id,
            str(memo_id),
            settings.image_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="图片不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FileResponse(
        path=image_path,
        media_type=memo.image_mime_type or "application/octet-stream",
        filename=f"memoisle-{memo.id}.image",
        content_disposition_type="inline",
    )


@router.get("/memos/{memo_id}/image/thumbnail", tags=["image"])
def download_memo_image_thumbnail_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """查看当前用户图片收藏的缩略图。"""

    try:
        memo, image_path = get_image_path(
            session,
            user_id,
            str(memo_id),
            settings.image_directory,
            thumbnail=True,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="缩略图不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FileResponse(
        path=image_path,
        media_type="image/webp",
        filename=f"memoisle-{memo.id}.thumbnail.webp",
        content_disposition_type="inline",
    )


@router.post(
    "/memos/{memo_id}/image/ocr",
    response_model=MemoRead,
    tags=["image"],
)
def recognize_image_ocr_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """手动重试图片文字识别与自动标签。"""

    if normalize_image_ocr_provider(settings.image_ocr_provider) == "none":
        raise HTTPException(
            status_code=503,
            detail="服务端未启用图片 OCR（MEMOISLE_IMAGE_OCR_PROVIDER）",
        )
    try:
        memo = recognize_image_ocr(session, user_id, str(memo_id), settings)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="图片不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/meeting/summary",
    response_model=MeetingSummaryResponse,
    tags=["meeting"],
)
def summarize_meeting_route(
    payload: MeetingSummaryRequest,
    _user_id: UserDependency,
    settings: SettingsDependency,
) -> MeetingSummaryResponse:
    """根据会议转写生成结构化会议纪要。"""

    try:
        summary = summarize_meeting(
            transcript=payload.transcript,
            title=payload.title,
            settings=settings,
        )
    except MeetingSummaryNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except MeetingSummaryUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return MeetingSummaryResponse(summary=summary)


@router.post("/speech/tts", tags=["speech"])
def synthesize_speech_route(
    payload: SpeechTtsRequest,
    _user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """使用可选的 sanoTTS 服务生成私有语音。"""

    try:
        audio_path = synthesize_speech(
            text=payload.text,
            settings=settings,
            voice=payload.voice,
        )
    except SpeechTextTooLongError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SpeechServiceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return FileResponse(
        path=audio_path,
        media_type="audio/wav",
        filename="memoisle-speech.wav",
        content_disposition_type="inline",
    )


@router.get(
    "/cloud-accounts",
    response_model=list[CloudAccountRead],
    tags=["cloud"],
)
def list_cloud_accounts_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[CloudAccountRead]:
    """返回当前用户已绑定的云盘账号。"""

    return [
        CloudAccountRead.model_validate(account)
        for account in list_cloud_accounts(session, user_id)
    ]


@router.post(
    "/cloud-accounts",
    response_model=CloudAccountRead,
    status_code=status.HTTP_201_CREATED,
    tags=["cloud"],
)
def create_cloud_account_route(
    payload: CloudAccountCreate,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> CloudAccountRead:
    """绑定云盘账号：先校验凭据，再加密保存。"""

    try:
        account = create_cloud_account(
            session,
            user_id,
            provider=payload.provider.value,
            credential=payload.credential,
            default_folder=payload.default_folder,
            settings=settings,
        )
    except CloudAccountExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (CloudCredentialRejectedError, UnsupportedProviderError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CloudAccountRead.model_validate(account)


@router.delete(
    "/cloud-accounts/{account_id}",
    response_model=dict[str, bool],
    tags=["cloud"],
)
def delete_cloud_account_route(
    account_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> dict[str, bool]:
    """解绑云盘账号。"""

    try:
        delete_cloud_account(session, user_id, str(account_id))
    except CloudAccountNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"deleted": True}


@router.post(
    "/cloud-accounts/{account_id}/verify",
    response_model=CloudAccountRead,
    tags=["cloud"],
)
def verify_cloud_account_route(
    account_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> CloudAccountRead:
    """重新校验云盘凭据并刷新状态。"""

    try:
        account = verify_cloud_account(
            session,
            user_id,
            str(account_id),
            settings=settings,
        )
    except CloudAccountNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CloudCredentialRejectedError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CloudAccountRead.model_validate(account)


@router.get(
    "/ebooks/jobs",
    response_model=list[EbookJobRead],
    tags=["ebooks"],
)
def list_ebook_jobs_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[EbookJobRead]:
    """返回当前用户最近的电子书任务。"""

    return [
        EbookJobRead.model_validate(job) for job in list_ebook_jobs(session, user_id)
    ]


@router.post(
    "/ebooks/jobs",
    response_model=EbookJobRead,
    status_code=status.HTTP_201_CREATED,
    tags=["ebooks"],
)
def create_ebook_job_route(
    payload: EbookJobCreate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> EbookJobRead:
    """提交电子书链接，并立刻在后台开始转存或下载上传。"""

    try:
        job = create_ebook_job(
            session,
            user_id,
            url=payload.url,
            settings=settings,
            provider=payload.provider.value if payload.provider else None,
            share_password=payload.share_password,
            target_folder=payload.target_folder,
            tags=payload.tags,
            collections=payload.collections,
            note=payload.note,
        )
    except EbookLinkError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    background_tasks.add_task(
        process_ebook_job_in_background,
        settings.database_url,
        user_id,
        job.id,
        settings,
    )
    return EbookJobRead.model_validate(job)


@router.get(
    "/ebooks/jobs/{job_id}",
    response_model=EbookJobRead,
    tags=["ebooks"],
)
def read_ebook_job_route(
    job_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> EbookJobRead:
    """查询单个电子书任务进度。"""

    try:
        job = get_ebook_job(session, user_id, str(job_id))
    except EbookJobNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return EbookJobRead.model_validate(job)


@router.post(
    "/ebooks/jobs/{job_id}/retry",
    response_model=EbookJobRead,
    tags=["ebooks"],
)
def retry_ebook_job_route(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> EbookJobRead:
    """重试失败的电子书任务。"""

    try:
        job = retry_ebook_job(session, user_id, str(job_id))
    except EbookJobNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except EbookJobStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    background_tasks.add_task(
        process_ebook_job_in_background,
        settings.database_url,
        user_id,
        job.id,
        settings,
    )
    return EbookJobRead.model_validate(job)
