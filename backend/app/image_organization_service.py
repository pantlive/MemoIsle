"""本地图片批量识别、文本模板归类和精确重复组查询。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.category_service import category_code_exists, classification_categories
from app.config import Settings
from app.database import Database
from app.image_local_ocr import recognize_local_image
from app.image_ocr_service import OcrUnavailableError
from app.model_settings_service import resolve_model_settings
from app.models import ImageOrganizationJob, Memo
from app.resource_classification_quality import (
    UncertainClassificationError,
    empty_assessment,
)
from app.resource_classification_retry import classify_service_failure
from app.resource_processing import ResourceMetadata, classify_resource_with_jev
from app.schemas import (
    ImageDuplicateGroup,
    ImageDuplicateItem,
    ImageDuplicateList,
    ImageOrganizationJobRead,
    ImageOrganizationRequest,
    ImageOrganizationState,
)

ACTIVE = {"pending", "processing"}


def image_filters(user_id: str) -> tuple[ColumnElement[bool], ...]:
    """仅处理本人未移入回收站且已有文件的图片。"""

    return (
        Memo.user_id == user_id,
        Memo.type == "image",
        Memo.status != "trashed",
        Memo.image_storage_name.is_not(None),
        Memo.image_hash.is_not(None),
    )


def needs_classification() -> tuple[ColumnElement[bool], ...]:
    """已尝试的模型判断和人工分类不重复处理。"""

    return (
        Memo.resource_ai_classified_at.is_(None),
        Memo.resource_ai_assessment["status"].as_string().is_(None),
        Memo.resource_ai_confirmation.is_(None),
        or_(
            Memo.resource_category_source.is_(None),
            Memo.resource_category_source.not_in({"manual", "user_rule", "jev", "llm"}),
        ),
    )


def duplicate_hash_query(user_id: str) -> Select[tuple[str | None]]:
    """仅把完整文件哈希相同的图片视为精确重复。"""

    return (
        select(Memo.image_hash)
        .where(*image_filters(user_id))
        .group_by(Memo.image_hash)
        .having(func.count() > 1)
    )


def list_duplicate_images(
    session: Session, user_id: str, offset: int = 0, limit: int = 10
) -> ImageDuplicateList:
    """重复组分页，每组最多展示五十条，完整组可按哈希另行分页。"""

    query = duplicate_hash_query(user_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    hashes = session.scalars(
        query.order_by(Memo.image_hash).offset(offset).limit(limit)
    ).all()
    groups = []
    for image_hash in hashes:
        filters = (*image_filters(user_id), Memo.image_hash == image_hash)
        count = (
            session.scalar(select(func.count()).select_from(Memo).where(*filters)) or 0
        )
        rows = session.scalars(
            select(Memo).where(*filters).order_by(Memo.created_at, Memo.id).limit(50)
        ).all()
        groups.append(
            ImageDuplicateGroup(
                image_hash=image_hash,
                count=count,
                items=[ImageDuplicateItem.model_validate(row) for row in rows],
            )
        )
    return ImageDuplicateList(
        groups=groups, total_count=total, offset=offset, limit=limit
    )


def image_organization_state(session: Session, user_id: str) -> ImageOrganizationState:
    """读取任务进度，计数不受图片列表展示页数限制。"""

    def count(*extra: ColumnElement[bool]) -> int:
        """按相同图片准入条件统计未完成条目。"""

        return (
            session.scalar(
                select(func.count())
                .select_from(Memo)
                .where(*image_filters(user_id), *extra)
            )
            or 0
        )

    job = session.get(ImageOrganizationJob, user_id)
    return ImageOrganizationState(
        pending_ocr_count=count(Memo.image_ocr_status != "ready"),
        pending_classification_count=count(*needs_classification()),
        duplicate_group_count=session.scalar(
            select(func.count()).select_from(duplicate_hash_query(user_id).subquery())
        )
        or 0,
        job=ImageOrganizationJobRead.model_validate(job) if job else None,
    )


def start_image_organization(
    session: Session,
    user_id: str,
    settings: Settings,
    payload: ImageOrganizationRequest,
) -> ImageOrganizationState:
    """固定全库未完成图片或明确选择的版本；重复启动不创建第二批请求。"""

    current = session.get(ImageOrganizationJob, user_id)
    if current is not None and current.status in ACTIVE:
        return image_organization_state(session, user_id)
    if payload.action != "ocr":
        resolved = resolve_model_settings(session, user_id, settings)
        if not resolved.jev_api_key or not resolved.jev_model:
            raise ValueError("请在设置 → 模型服务配置并启用 Jev")
        if len(classification_categories(session, user_id)) > 255:
            raise ValueError("Jev 最多支持 255 个启用分类")
    filters = list(image_filters(user_id))
    if payload.scope == "all":
        filters.extend(
            (Memo.image_ocr_status != "ready",)
            if payload.action == "ocr"
            else needs_classification()
        )
    else:
        filters.append(Memo.id.in_([str(item.memo_id) for item in payload.items]))
    rows = session.scalars(
        select(Memo).where(*filters).order_by(Memo.created_at, Memo.id)
    ).all()
    versions = {str(item.memo_id): item.expected_version for item in payload.items}
    snapshots = [
        {
            "memo_id": row.id,
            "version": versions.get(row.id, row.version),
            "image_hash": row.image_hash,
        }
        for row in rows
    ]
    now = datetime.now(UTC)
    values = dict(
        id=str(uuid4()),
        action=payload.action,
        status="pending" if snapshots else "completed",
        items=snapshots,
        total_count=len(snapshots),
        processed_count=0,
        succeeded_count=0,
        failed_count=0,
        skipped_count=0,
        error=None,
        worker_token=None,
        lease_expires_at=None,
        created_at=now,
        updated_at=now,
    )
    if current:
        result = session.execute(
            update(ImageOrganizationJob)
            .where(
                ImageOrganizationJob.user_id == user_id,
                ImageOrganizationJob.id == current.id,
                ImageOrganizationJob.status.not_in(ACTIVE),
            )
            .values(**values)
        )
        if result.rowcount != 1:
            session.rollback()
            return image_organization_state(session, user_id)
    else:
        session.add(ImageOrganizationJob(user_id=user_id, **values))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    session.expire_all()
    return image_organization_state(session, user_id)


def resume_image_organization(session: Session, user_id: str) -> ImageOrganizationState:
    """只继续暂停批次，不重跑成功、未确定或跳过的条目。"""

    result = session.execute(
        update(ImageOrganizationJob)
        .where(
            ImageOrganizationJob.user_id == user_id,
            ImageOrganizationJob.status == "failed",
        )
        .values(status="pending", error=None, worker_token=None, lease_expires_at=None)
    )
    session.commit()
    if result.rowcount != 1:
        raise ValueError("当前没有可继续的图片任务")
    return image_organization_state(session, user_id)


def process_image_job(
    session: Session,
    user_id: str,
    settings: Settings,
    stop_event: asyncio.Event | None = None,
) -> None:
    """逐张执行本地 OCR 和文本分类，结果、版本与游标同事务提交。"""

    now = datetime.now(UTC)
    token = str(uuid4())
    result = session.execute(
        update(ImageOrganizationJob)
        .where(
            ImageOrganizationJob.user_id == user_id,
            ImageOrganizationJob.status.in_(ACTIVE),
            or_(
                ImageOrganizationJob.lease_expires_at.is_(None),
                ImageOrganizationJob.lease_expires_at <= now,
            ),
        )
        .values(
            status="processing",
            worker_token=token,
            lease_expires_at=now + timedelta(seconds=180),
        )
    )
    session.commit()
    if result.rowcount != 1:
        return
    try:
        _process_claimed_job(session, user_id, settings, token, stop_event)
    except Exception:
        # 未预期错误也只暂停本 worker 持有的批次，不泄露模型配置或中断其他账号。
        session.rollback()
        session.execute(
            update(ImageOrganizationJob)
            .where(
                ImageOrganizationJob.user_id == user_id,
                ImageOrganizationJob.worker_token == token,
            )
            .values(
                status="failed",
                error="图片整理暂时失败，请检查本地文件和模型设置后继续。",
                worker_token=None,
                lease_expires_at=None,
            )
        )
        session.commit()


def _process_claimed_job(
    session: Session,
    user_id: str,
    settings: Settings,
    token: str,
    stop_event: asyncio.Event | None,
) -> None:
    """持有租约后处理快照，每次提交前重新检查所有者与版本。"""

    while True:
        session.expire_all()
        job = session.get(ImageOrganizationJob, user_id)
        if job is None or job.worker_token != token:
            return
        cursor, job_id = job.processed_count, job.id
        guards = (
            ImageOrganizationJob.user_id == user_id,
            ImageOrganizationJob.id == job_id,
            ImageOrganizationJob.worker_token == token,
            ImageOrganizationJob.processed_count == cursor,
        )
        if (
            stop_event is not None and stop_event.is_set()
        ) or cursor >= job.total_count:
            session.execute(
                update(ImageOrganizationJob)
                .where(*guards)
                .values(
                    status="completed" if cursor >= job.total_count else "pending",
                    worker_token=None,
                    lease_expires_at=None,
                )
            )
            session.commit()
            return
        item = job.items[cursor]
        memo = session.get(Memo, item["memo_id"])
        action = job.action
        values: dict[str, object] = {}
        chosen_category: str | None = None
        outcome = "skipped"
        error_message = None
        eligible = (
            memo is not None
            and memo.user_id == user_id
            and memo.type == "image"
            and memo.status != "trashed"
            and memo.version == item["version"]
            and memo.image_hash == item["image_hash"]
        )
        if eligible:
            if action == "ocr" and memo.image_ocr_status == "ready":
                eligible = False
            elif action != "ocr" and (
                memo.resource_ai_assessment
                or memo.resource_ai_classified_at
                or memo.resource_ai_confirmation
                or memo.resource_category_source
                in {"manual", "user_rule", "jev", "llm"}
            ):
                eligible = False
        if eligible:
            title, text, image_hash, version = (
                memo.title,
                memo.image_ocr_text,
                memo.image_hash,
                memo.version,
            )
            ocr_status = memo.image_ocr_status
            snapshots = list(job.items)
            path = settings.image_directory / (memo.image_storage_name or "")
            if path.name != memo.image_storage_name:
                eligible = False
            else:
                session.rollback()
                try:
                    if action != "classify" and ocr_status != "ready":
                        ocr = recognize_local_image(
                            path.read_bytes(),
                            settings.image_directory.parent / "ocr-models",
                        )
                        text = ocr.text
                        values.update(
                            image_ocr_text=text or None,
                            image_ocr_status="ready",
                            image_ocr_source=ocr.source,
                            image_auto_tags=ocr.tags,
                            image_ocr_error=None,
                            image_ocr_updated_at=datetime.now(UTC),
                        )
                    outcome = "succeeded"
                    if action != "ocr":
                        resolved = resolve_model_settings(session, user_id, settings)
                        categories = classification_categories(session, user_id)
                        session.rollback()
                        if not resolved.jev_api_key:
                            raise ValueError("model_disabled")
                        if not text or not text.strip():
                            assessment = empty_assessment(
                                "no_ocr_text",
                                resolved.jev_min_confidence,
                                resolved.jev_model,
                                False,
                            )
                            assessment["input_source"] = "image_ocr"
                            raise UncertainClassificationError(assessment)
                        decision = classify_resource_with_jev(
                            ResourceMetadata(
                                "",
                                title,
                                None,
                                None,
                                None,
                                200,
                                text_excerpt=text[:3000],
                            ),
                            categories,
                            resolved.jev_api_key,
                            resolved.jev_base_url,
                            resolved.jev_model,
                            resolved.jev_min_confidence,
                            content_kind="image",
                        )
                        if not category_code_exists(
                            session, user_id, decision.category, active_only=True
                        ):
                            raise ValueError("category_changed")
                        values.update(
                            resource_category=decision.category,
                            resource_category_label=decision.category_label,
                            resource_categories=[decision.category],
                            resource_category_source="jev",
                            resource_category_status="ready",
                            resource_category_confidence=decision.confidence,
                            resource_ai_classified_at=datetime.now(UTC),
                            resource_ai_assessment=decision.assessment,
                        )
                        chosen_category = decision.category
                except UncertainClassificationError as error:
                    values["resource_ai_assessment"] = error.assessment
                    outcome = "failed"
                except OcrUnavailableError:
                    error_message = (
                        "本地 PyTorch OCR 不可用，请准备中英文模型后继续任务。"
                    )
                except (httpx.HTTPError, httpx.InvalidURL) as error:
                    error_message = classify_service_failure(
                        error, datetime.now(UTC)
                    ).message
                except ValueError:
                    error_message = "分类模型已停用或模板已变化，请检查设置后继续任务。"
                except OSError:
                    outcome = "failed"
                    values.update(
                        image_ocr_status="failed",
                        image_ocr_error="图片文件无法读取，请重新上传后再识别。",
                        image_ocr_updated_at=datetime.now(UTC),
                    )
                session.rollback()
                # 先验证租约所有者再保存，条目改动、图片替换和回收站操作均受版本保护。
                if (
                    session.execute(
                        update(ImageOrganizationJob)
                        .where(*guards)
                        .values(
                            updated_at=datetime.now(UTC),
                            lease_expires_at=datetime.now(UTC) + timedelta(seconds=180),
                        )
                    ).rowcount
                    != 1
                ):
                    session.rollback()
                    return
                # 获得写入事务后复查模板，避免等待模型期间停用的分类被写回。
                if chosen_category and not category_code_exists(
                    session, user_id, chosen_category, active_only=True
                ):
                    values = {
                        key: value
                        for key, value in values.items()
                        if not key.startswith("resource_")
                    }
                    error_message = "分类模板已变化，请检查设置后继续任务。"
                if values:
                    values.update(
                        updated_at=datetime.now(UTC), version=Memo.version + 1
                    )
                    saved = session.execute(
                        update(Memo)
                        .where(
                            Memo.id == item["memo_id"],
                            *image_filters(user_id),
                            Memo.version == version,
                            Memo.image_hash == image_hash,
                        )
                        .values(**values)
                    )
                    if saved.rowcount != 1:
                        outcome = "skipped"
                        error_message = None
                    elif error_message:
                        snapshots[cursor] = {**item, "version": version + 1}
                        session.execute(
                            update(ImageOrganizationJob)
                            .where(*guards)
                            .values(items=snapshots)
                        )
        if error_message:
            session.execute(
                update(ImageOrganizationJob)
                .where(*guards)
                .values(
                    status="failed",
                    error=error_message,
                    worker_token=None,
                    lease_expires_at=None,
                )
            )
            session.commit()
            return
        field = getattr(ImageOrganizationJob, f"{outcome}_count")
        session.execute(
            update(ImageOrganizationJob)
            .where(*guards)
            .values(processed_count=cursor + 1, **{f"{outcome}_count": field + 1})
        )
        session.commit()


async def image_organization_loop(
    database_url: str, settings: Settings, stop_event: asyncio.Event
) -> None:
    """独立恢复图片整理批次，不主动创建任务或访问真实图片。"""

    def run() -> None:
        """每轮用独立会话处理已有任务。"""

        database = Database(database_url)
        try:
            with database.session_factory() as session:
                users = session.scalars(
                    select(ImageOrganizationJob.user_id).where(
                        ImageOrganizationJob.status.in_(ACTIVE)
                    )
                ).all()
                for user_id in users:
                    process_image_job(session, user_id, settings, stop_event)
        finally:
            database.dispose()

    while not stop_event.is_set():
        await asyncio.to_thread(run)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3)
        except TimeoutError:
            pass
