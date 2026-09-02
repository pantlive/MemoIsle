"""用户网页资料分类模板与规则业务。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ResourceCategoryRule, ResourceCategoryTemplate
from app.resource_processing import (
    CATEGORY_LABELS,
    ClassificationCategory,
    ClassificationRule,
)
from app.schemas import ResourceCategory, ResourceCategoryRuleMatchType

SYSTEM_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    ResourceCategory.LEARNING.value: "课程、教程、文档和其他学习内容",
    ResourceCategory.ARTICLE.value: "文章、博客和新闻阅读",
    ResourceCategory.MEDIA.value: "视频、音频、播客和直播内容",
    ResourceCategory.TOOL.value: "软件、网站、服务和开发工具",
    ResourceCategory.BOOK_PAPER.value: "书籍、论文和研究资料",
    ResourceCategory.PRODUCT.value: "商品、购物和值得购买的东西",
    ResourceCategory.OTHER.value: "暂时无法归入其他分类的网页",
}
SYSTEM_CATEGORY_CODES = frozenset(CATEGORY_LABELS)


class CategoryTemplateNotFoundError(LookupError):
    """用户分类模板不存在。"""


class CategoryRuleNotFoundError(LookupError):
    """用户分类规则不存在。"""


class CategoryNameConflictError(ValueError):
    """分类名称已经被当前用户使用。"""


class CategoryCodeNotFoundError(ValueError):
    """分类编码不存在或已停用。"""


class CategoryVersionConflictError(RuntimeError):
    """分类模板或规则已经被其他请求修改。"""

    def __init__(
        self,
        message: str,
        current: ResourceCategoryTemplate | ResourceCategoryRule,
    ) -> None:
        super().__init__(message)
        self.current = current


def system_category_options() -> list[ClassificationCategory]:
    """返回系统内置的分类模板。"""

    return [
        ClassificationCategory(
            code=code,
            label=CATEGORY_LABELS[code],
            description=SYSTEM_CATEGORY_DESCRIPTIONS.get(code),
        )
        for code in CATEGORY_LABELS
    ]


def list_category_templates(
    session: Session,
    user_id: str,
    include_inactive: bool = True,
) -> list[ResourceCategoryTemplate]:
    """读取当前用户的自定义分类模板。"""

    query = (
        select(ResourceCategoryTemplate)
        .where(ResourceCategoryTemplate.user_id == user_id)
        .order_by(
            ResourceCategoryTemplate.created_at.asc(),
            ResourceCategoryTemplate.id.asc(),
        )
    )
    if not include_inactive:
        query = query.where(ResourceCategoryTemplate.is_active.is_(True))
    return list(session.scalars(query).all())


def list_resource_category_options(
    session: Session,
    user_id: str,
    include_inactive: bool = True,
) -> list[dict[str, object]]:
    """组合系统分类和用户分类，供客户端展示。"""

    options: list[dict[str, object]] = [
        {
            "id": None,
            "code": category.code,
            "name": category.label,
            "description": category.description,
            "is_system": True,
            "is_active": True,
            "version": 1,
        }
        for category in system_category_options()
    ]
    options.extend(
        {
            "id": template.id,
            "code": template.code,
            "name": template.name,
            "description": template.description,
            "is_system": False,
            "is_active": template.is_active,
            "version": template.version,
        }
        for template in list_category_templates(
            session,
            user_id,
            include_inactive=include_inactive,
        )
    )
    return options


def classification_categories(
    session: Session,
    user_id: str,
) -> list[ClassificationCategory]:
    """返回当前分类任务允许使用的分类集合。"""

    categories = system_category_options()
    categories.extend(
        ClassificationCategory(
            code=template.code,
            label=template.name,
            description=template.description,
        )
        for template in list_category_templates(
            session,
            user_id,
            include_inactive=False,
        )
    )
    return categories


def category_label(
    session: Session,
    user_id: str,
    category_code: str,
) -> str | None:
    """读取系统或用户分类的显示名称。"""

    system_label = CATEGORY_LABELS.get(category_code)
    if system_label is not None:
        return system_label
    template = session.scalar(
        select(ResourceCategoryTemplate).where(
            ResourceCategoryTemplate.user_id == user_id,
            ResourceCategoryTemplate.code == category_code,
        )
    )
    return template.name if template is not None else None


def category_code_exists(
    session: Session,
    user_id: str,
    category_code: str,
    active_only: bool = True,
) -> bool:
    """判断分类编码是否属于当前用户。"""

    if category_code in SYSTEM_CATEGORY_CODES:
        return True
    query = select(ResourceCategoryTemplate.id).where(
        ResourceCategoryTemplate.user_id == user_id,
        ResourceCategoryTemplate.code == category_code,
    )
    if active_only:
        query = query.where(ResourceCategoryTemplate.is_active.is_(True))
    return session.scalar(query) is not None


def classification_rules(
    session: Session,
    user_id: str,
) -> list[ClassificationRule]:
    """读取已启用且目标分类有效的用户规则。"""

    labels = {
        option["code"]: str(option["name"])
        for option in list_resource_category_options(
            session,
            user_id,
            include_inactive=False,
        )
    }
    rules = session.scalars(
        select(ResourceCategoryRule)
        .where(
            ResourceCategoryRule.user_id == user_id,
            ResourceCategoryRule.enabled.is_(True),
        )
        .order_by(
            ResourceCategoryRule.priority.asc(),
            ResourceCategoryRule.created_at.asc(),
            ResourceCategoryRule.id.asc(),
        )
    )
    return [
        ClassificationRule(
            category_code=rule.category_code,
            category_label=labels[rule.category_code],
            match_type=rule.match_type,
            pattern=rule.pattern,
        )
        for rule in rules
        if rule.category_code in labels
    ]


def list_category_rules(
    session: Session,
    user_id: str,
) -> list[ResourceCategoryRule]:
    """按优先级读取当前用户的分类规则。"""

    query = (
        select(ResourceCategoryRule)
        .where(ResourceCategoryRule.user_id == user_id)
        .order_by(
            ResourceCategoryRule.priority.asc(),
            ResourceCategoryRule.created_at.asc(),
            ResourceCategoryRule.id.asc(),
        )
    )
    return list(session.scalars(query).all())


def create_category_template(
    session: Session,
    user_id: str,
    name: str,
    description: str | None,
) -> ResourceCategoryTemplate:
    """创建用户分类模板。"""

    cleaned_name = name.strip()
    if _category_name_taken(session, user_id, cleaned_name):
        raise CategoryNameConflictError("分类名称已经存在")
    template = ResourceCategoryTemplate(
        id=str(uuid4()),
        user_id=user_id,
        code=f"custom_{uuid4().hex}",
        name=cleaned_name,
        description=description.strip() if description else None,
        is_active=True,
        version=1,
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def update_category_template(
    session: Session,
    user_id: str,
    category_id: str,
    expected_version: int,
    changes: Mapping[str, object],
) -> ResourceCategoryTemplate:
    """更新用户分类模板并检查版本。"""

    template = get_category_template(session, user_id, category_id)
    if template.version != expected_version:
        raise CategoryVersionConflictError("分类模板版本冲突", template)
    if "name" in changes and changes["name"] is not None:
        name = str(changes["name"])
        if _category_name_taken(session, user_id, name, template.id):
            raise CategoryNameConflictError("分类名称已经存在")
        template.name = name
    if "description" in changes:
        value = changes["description"]
        template.description = str(value) if value is not None else None
    if "is_active" in changes and changes["is_active"] is not None:
        template.is_active = bool(changes["is_active"])
    template.version += 1
    template.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(template)
    return template


def get_category_template(
    session: Session,
    user_id: str,
    category_id: str,
) -> ResourceCategoryTemplate:
    """按用户读取分类模板。"""

    template = session.scalar(
        select(ResourceCategoryTemplate).where(
            ResourceCategoryTemplate.id == category_id,
            ResourceCategoryTemplate.user_id == user_id,
        )
    )
    if template is None:
        raise CategoryTemplateNotFoundError
    return template


def create_category_rule(
    session: Session,
    user_id: str,
    name: str | None,
    category_code: str,
    match_type: ResourceCategoryRuleMatchType,
    pattern: str,
    priority: int,
    enabled: bool,
) -> ResourceCategoryRule:
    """创建用户网页分类规则。"""

    ensure_active_category(session, user_id, category_code)
    cleaned_pattern = pattern.strip()
    rule = ResourceCategoryRule(
        id=str(uuid4()),
        user_id=user_id,
        name=(name or f"{match_type.value} · {cleaned_pattern}")[:100],
        category_code=category_code,
        match_type=match_type.value,
        pattern=cleaned_pattern,
        priority=priority,
        enabled=enabled,
        version=1,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def update_category_rule(
    session: Session,
    user_id: str,
    rule_id: str,
    expected_version: int,
    changes: Mapping[str, object],
) -> ResourceCategoryRule:
    """更新用户网页分类规则并检查版本。"""

    rule = get_category_rule(session, user_id, rule_id)
    if rule.version != expected_version:
        raise CategoryVersionConflictError("分类规则版本冲突", rule)
    category_code = str(changes.get("category_code", rule.category_code))
    enabled = bool(changes.get("enabled", rule.enabled))
    if enabled:
        ensure_active_category(session, user_id, category_code)
    rule.category_code = category_code
    if "name" in changes and changes["name"] is not None:
        rule.name = str(changes["name"])[:100]
    if "match_type" in changes and changes["match_type"] is not None:
        match_type = changes["match_type"]
        rule.match_type = (
            match_type.value
            if isinstance(match_type, ResourceCategoryRuleMatchType)
            else str(match_type)
        )
    if "pattern" in changes and changes["pattern"] is not None:
        rule.pattern = str(changes["pattern"])
    if "priority" in changes and changes["priority"] is not None:
        rule.priority = int(changes["priority"])
    if "enabled" in changes and changes["enabled"] is not None:
        rule.enabled = enabled
    rule.version += 1
    rule.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(rule)
    return rule


def get_category_rule(
    session: Session,
    user_id: str,
    rule_id: str,
) -> ResourceCategoryRule:
    """按用户读取分类规则。"""

    rule = session.scalar(
        select(ResourceCategoryRule).where(
            ResourceCategoryRule.id == rule_id,
            ResourceCategoryRule.user_id == user_id,
        )
    )
    if rule is None:
        raise CategoryRuleNotFoundError
    return rule


def delete_category_rule(
    session: Session,
    user_id: str,
    rule_id: str,
) -> None:
    """删除当前用户的一条分类规则。"""

    rule = get_category_rule(session, user_id, rule_id)
    session.delete(rule)
    session.commit()


def ensure_active_category(
    session: Session,
    user_id: str,
    category_code: str,
) -> None:
    """确保规则目标是当前用户可用的分类。"""

    if not category_code_exists(session, user_id, category_code, active_only=True):
        raise CategoryCodeNotFoundError("目标分类不存在或已停用")


def _category_name_taken(
    session: Session,
    user_id: str,
    name: str,
    ignored_id: str | None = None,
) -> bool:
    """检查系统或用户分类是否占用名称。"""

    cleaned_name = name.strip()
    if cleaned_name.casefold() in {
        label.casefold() for label in CATEGORY_LABELS.values()
    }:
        return True
    query = select(ResourceCategoryTemplate.id).where(
        ResourceCategoryTemplate.user_id == user_id,
        func.lower(ResourceCategoryTemplate.name) == cleaned_name.casefold(),
    )
    if ignored_id is not None:
        query = query.where(ResourceCategoryTemplate.id != ignored_id)
    return session.scalar(query) is not None
