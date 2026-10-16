"""分类脚本共用的只读读取逻辑：不依赖新字段，也不写数据库。"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.category_service import (  # noqa: E402
    category_exemplars,
    category_rejected_examples,
    system_category_options,
)
from app.config import Settings  # noqa: E402
from app.model_settings_service import (  # noqa: E402
    credential_cipher,
    resolve_model_settings,
)
from app.models import Memo, ResourceCategoryTemplate, User  # noqa: E402
from app.resource_processing import ClassificationCategory  # noqa: E402
from app.schemas import MemoType  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


def resolve_account(
    session: Session,
    settings: Settings,
    user_id: str | None,
) -> tuple[str, Settings]:
    """取账号和已解密的模型配置；默认选资料最多的账号。"""

    account = user_id
    if account is None:
        account = session.scalar(
            select(Memo.user_id)
            .where(Memo.type == MemoType.RESOURCE)
            .group_by(Memo.user_id)
            .order_by(func.count().desc())
            .limit(1)
        )
    if account is None:
        account = session.scalar(select(User.id).limit(1))
    if account is None:
        raise SystemExit("数据库里没有账号")
    try:
        resolved = resolve_model_settings(session, str(account), settings)
    except OperationalError:
        # 数据库还没执行本次升级时，用旧字段拼出账号配置，脚本仍可只读运行。
        resolved = _legacy_settings(session, settings, str(account))
    return str(account), resolved


def _legacy_settings(
    session: Session,
    settings: Settings,
    user_id: str,
) -> Settings:
    """读取升级前的模型配置字段，凭据照旧解密。"""

    values: dict[str, object] = {}
    for provider, prefix in (("deepseek", "deepseek"), ("jev", "jev")):
        row = session.execute(
            text(
                "SELECT model, base_url, enabled, credential_cipher "
                "FROM model_provider_setting "
                "WHERE user_id = :user_id AND provider = :provider"
            ),
            {"user_id": user_id, "provider": provider},
        ).first()
        if row is None:
            continue
        model, base_url, enabled, cipher = row
        api_key: str | None = None
        if cipher:
            try:
                api_key = (
                    credential_cipher(settings)
                    .decrypt(str(cipher).encode("ascii"))
                    .decode("utf-8")
                )
            except Exception:  # noqa: BLE001 - 读不出密钥时按未配置处理
                api_key = None
        values[f"{prefix}_model"] = model
        if base_url:
            values[f"{prefix}_base_url"] = base_url
        values[f"{prefix}_api_key"] = api_key if enabled else None
    return replace(settings, **values)


def user_categories(
    session: Session,
    user_id: str,
) -> list[ClassificationCategory]:
    """只读现有字段拼出启用的自定义分类，不触碰新增的口径列。"""

    rows = session.execute(
        select(
            ResourceCategoryTemplate.code,
            ResourceCategoryTemplate.name,
            ResourceCategoryTemplate.description,
            ResourceCategoryTemplate.parent_code,
            ResourceCategoryTemplate.is_active,
        ).where(ResourceCategoryTemplate.user_id == user_id)
    ).all()
    names = {str(code): str(name) for code, name, _, _, _ in rows}
    parents = {
        str(code): (str(parent) if parent else None)
        for code, _, _, parent, _ in rows
    }
    categories: list[ClassificationCategory] = []
    for code, name, description, _parent, is_active in rows:
        if not is_active:
            continue
        parts = [str(name)]
        current = parents.get(str(code))
        while current and len(parts) < 4:
            parts.append(names.get(current, current))
            current = parents.get(current)
        categories.append(
            ClassificationCategory(
                code=str(code),
                label=str(name),
                description=description,
                path=" / ".join(reversed(parts)),
            )
        )
    return categories


def classification_options(
    session: Session,
    user_id: str,
    definitions: Mapping[str, Mapping[str, str]] | None = None,
) -> list[ClassificationCategory]:
    """用户细类（可叠加口径草稿）+ 只作兜底的系统分类。"""

    overlay = definitions or {}
    categories: list[ClassificationCategory] = []
    for category in user_categories(session, user_id):
        draft = overlay.get(category.code, {})
        categories.append(
            ClassificationCategory(
                code=category.code,
                label=category.label,
                description=category.description,
                path=category.path,
                definition=draft.get("definition") or None,
                include_examples=draft.get("include_examples") or None,
                exclude_examples=draft.get("exclude_examples") or None,
            )
        )
    categories.extend(system_category_options())
    return categories


def exemplars(
    session: Session,
    user_id: str,
    categories: Sequence[ClassificationCategory],
) -> dict[str, list[dict[str, str]]]:
    """已确认的历史样本。"""

    return category_exemplars(session, user_id, categories)


def rejected_examples(
    session: Session,
    user_id: str,
    categories: Sequence[ClassificationCategory],
) -> dict[str, list[dict[str, str]]]:
    """被用户改掉的模型判断，作为反例。"""

    return category_rejected_examples(session, user_id, categories)
