"""用户网页资料分类模板与规则业务。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Memo, ResourceCategoryRule, ResourceCategoryTemplate
from app.resource_processing import (
    CATEGORY_LABELS,
    ClassificationCategory,
    ClassificationRule,
    clean_metadata_text,
)
from app.schemas import (
    MemoType,
    ResourceCategory,
    ResourceCategoryRuleMatchType,
    ResourceProcessStatus,
)

MAX_CATEGORY_DEPTH = 3
MAX_RESOURCE_CATEGORIES = 8
# 200 条带摘要的样本会拖垮中转模型，按大类各抽一些最近网页。
MAX_LIBRARY_PAGES_FOR_GENERATION = 80
_LIBRARY_PAGE_POOL = 400

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


class CategoryParentError(ValueError):
    """父分类不存在、会成环，或超出三层限制。"""


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
    """返回系统内置的分类模板；它们只作兜底，不参与用户细类的竞争。"""

    return [
        ClassificationCategory(
            code=code,
            label=CATEGORY_LABELS[code],
            description=SYSTEM_CATEGORY_DESCRIPTIONS.get(code),
            is_fallback=True,
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

    templates = list_category_templates(
        session,
        user_id,
        include_inactive=True,
    )
    templates_by_code = {template.code: template for template in templates}
    options: list[dict[str, object]] = [
        {
            "id": None,
            "code": category.code,
            "name": category.label,
            "description": category.description,
            "definition": None,
            "include_examples": None,
            "exclude_examples": None,
            "is_system": True,
            "is_active": True,
            "version": 1,
            "parent_code": None,
            "depth": 1,
            "path": category.label,
        }
        for category in system_category_options()
    ]
    options.extend(
        _option_from_template(template, templates_by_code)
        for template in templates
        if include_inactive or template.is_active
    )
    return _order_category_options(options)


def classification_categories(
    session: Session,
    user_id: str,
) -> list[ClassificationCategory]:
    """返回当前分类任务允许使用的分类集合。

    用户启用的自定义分类在前并携带口径；系统七类在后，只作兜底。
    """

    templates = list_category_templates(session, user_id, include_inactive=True)
    templates_by_code = {template.code: template for template in templates}
    categories = [
        ClassificationCategory(
            code=template.code,
            label=template.name,
            description=template.description,
            path=_path_from_map(templates_by_code, template.code),
            definition=template.definition,
            include_examples=template.include_examples,
            exclude_examples=template.exclude_examples,
        )
        for template in templates
        if template.is_active
    ]
    categories.extend(system_category_options())
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


def get_category_depth(session: Session, user_id: str, category_code: str) -> int:
    """计算分类深度，系统分类和自定义顶级均为 1。"""

    return _depth_from_map(_templates_by_code(session, user_id), category_code)


def category_path(session: Session, user_id: str, category_code: str) -> str:
    """返回从大类到当前分类的显示路径。"""

    return _path_from_map(_templates_by_code(session, user_id), category_code)


def category_template_to_option(
    session: Session,
    user_id: str,
    template: ResourceCategoryTemplate,
) -> dict[str, object]:
    """把用户分类模板转成客户端选项。"""

    templates_by_code = _templates_by_code(session, user_id)
    templates_by_code[template.code] = template
    return _option_from_template(template, templates_by_code)


def serialize_category_templates(
    session: Session,
    user_id: str,
) -> list[dict[str, object]]:
    """导出可随备份还原的自定义分类，不含系统分类。"""

    return [
        {
            "code": template.code,
            "name": template.name,
            "description": template.description,
            "definition": template.definition,
            "include_examples": template.include_examples,
            "exclude_examples": template.exclude_examples,
            "parent_code": template.parent_code,
            "is_active": template.is_active,
        }
        for template in list_category_templates(
            session,
            user_id,
            include_inactive=True,
        )
    ]


def import_category_templates(
    session: Session,
    user_id: str,
    raw_categories: Sequence[Mapping[str, Any]],
) -> int:
    """按备份里的 code 补建缺失的自定义分类，先建父级。"""

    existing = {
        template.code: template
        for template in list_category_templates(
            session,
            user_id,
            include_inactive=True,
        )
    }
    pending: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    for item in raw_categories:
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        if (
            not code
            or not name
            or code in SYSTEM_CATEGORY_CODES
            or code in seen_codes
            or len(code) > 50
            or len(name) > 50
            or not code.replace("_", "").isalnum()
        ):
            continue
        parent = str(item.get("parent_code") or "").strip() or None
        description = item.get("description")
        pending.append(
            {
                "code": code,
                "name": name,
                "description": (
                    str(description).strip()[:300] if description else None
                ),
                "definition": _imported_text(item.get("definition"), 600),
                "include_examples": _imported_text(item.get("include_examples"), 800),
                "exclude_examples": _imported_text(item.get("exclude_examples"), 800),
                "parent_code": parent,
                "is_active": bool(item.get("is_active", True)),
            }
        )
        seen_codes.add(code)

    def imported_depth(code: str) -> int:
        depth = 1
        current: str | None = code
        walked: set[str] = set()
        while current and current not in walked and depth <= MAX_CATEGORY_DEPTH + 1:
            walked.add(current)
            if current in SYSTEM_CATEGORY_CODES:
                return depth
            row = next((item for item in pending if item["code"] == current), None)
            parent_code = (
                str(row["parent_code"]) if row and row["parent_code"] else None
            )
            if row is None:
                template = existing.get(current)
                parent_code = template.parent_code if template is not None else None
            if not parent_code:
                return depth
            current = parent_code
            depth += 1
        return depth

    # 先把深度算完再排序：排序键里读取 pending 会看到正在排序的空列表。
    depths = {
        str(item["code"]): imported_depth(str(item["code"])) for item in pending
    }
    pending.sort(key=lambda item: (depths[str(item["code"])], str(item["code"])))
    available = set(SYSTEM_CATEGORY_CODES) | set(existing)
    created = 0
    for item in pending:
        code = str(item["code"])
        if code in existing:
            continue
        parent_code = (
            str(item["parent_code"]) if item["parent_code"] is not None else None
        )
        if parent_code is not None and parent_code not in available:
            continue
        if imported_depth(code) > MAX_CATEGORY_DEPTH:
            continue
        if _category_name_taken(
            session,
            user_id,
            str(item["name"]),
            parent_code=parent_code,
        ):
            continue
        template = ResourceCategoryTemplate(
            id=str(uuid4()),
            user_id=user_id,
            code=code,
            parent_code=parent_code,
            name=str(item["name"]),
            description=(
                str(item["description"]) if item["description"] is not None else None
            ),
            definition=(
                str(item["definition"]) if item["definition"] is not None else None
            ),
            include_examples=(
                str(item["include_examples"])
                if item["include_examples"] is not None
                else None
            ),
            exclude_examples=(
                str(item["exclude_examples"])
                if item["exclude_examples"] is not None
                else None
            ),
            is_active=bool(item["is_active"]),
            version=1,
        )
        session.add(template)
        existing[code] = template
        available.add(code)
        created += 1
    if created:
        session.flush()
    return created


def category_exemplars(
    session: Session,
    user_id: str,
    categories: Sequence[ClassificationCategory],
    per_category: int = 4,
    max_total: int = 40,
) -> dict[str, list[dict[str, str]]]:
    """取出用户已确认的历史样本，作为分类口径的一部分回喂给模型。

    只有人工指定、用户规则和人工确认过的条目才算已确认；模型自己的旧判断
    不参与，避免把错误结论当成口径。
    """

    codes = [category.code for category in categories if not category.is_fallback]
    if not codes:
        return {}
    confirmed = or_(
        Memo.resource_category_source == "manual",
        Memo.resource_category_source == "user_rule",
        Memo.resource_ai_confirmation.is_not(None),
    )
    rows = session.execute(
        select(
            Memo.resource_category,
            Memo.resource_page_title,
            Memo.title,
            Memo.source_url,
            Memo.resource_site_name,
        )
        .where(
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != "trashed",
            Memo.resource_category.in_(codes),
            confirmed,
        )
        .order_by(Memo.updated_at.desc(), Memo.id.desc())
        .limit(max_total * 8)
    ).all()
    exemplars: dict[str, list[dict[str, str]]] = {}
    total = 0
    for category_code, page_title, title, source_url, site_name in rows:
        if total >= max_total:
            break
        bucket = exemplars.setdefault(str(category_code), [])
        if len(bucket) >= per_category:
            continue
        label = clean_metadata_text(page_title or title, 120)
        if not label:
            continue
        bucket.append(
            {
                "title": label,
                "site": clean_metadata_text(site_name, 80) or "",
                "domain": _url_domain(source_url),
            }
        )
        total += 1
    return exemplars


def category_rejected_examples(
    session: Session,
    user_id: str,
    categories: Sequence[ClassificationCategory],
    per_category: int = 3,
    max_total: int = 20,
) -> dict[str, list[dict[str, str]]]:
    """取出被用户改掉的模型判断，作为该分类的反例回喂给模型。

    只有人工指定或人工确认过的条目才作数：模型当时首选了 A，用户改成了 B，
    那么这一条就是 A 的反例。模型自己的旧结论不会被当成反例。
    """

    codes = {category.code for category in categories}
    if not codes:
        return {}
    labels = {
        category.code: category.path or category.label for category in categories
    }
    rejected_code = Memo.resource_ai_assessment["candidates"][0]["code"].as_string()
    rows = session.execute(
        select(
            rejected_code,
            Memo.resource_category,
            Memo.resource_page_title,
            Memo.title,
            Memo.source_url,
            Memo.resource_site_name,
        )
        .where(
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != "trashed",
            Memo.resource_ai_assessment.is_not(None),
            Memo.resource_category.is_not(None),
            or_(
                Memo.resource_category_source == "manual",
                Memo.resource_ai_confirmation.is_not(None),
            ),
        )
        .order_by(Memo.updated_at.desc(), Memo.id.desc())
        .limit(max_total * 8)
    ).all()
    rejected: dict[str, list[dict[str, str]]] = {}
    total = 0
    for code, final_code, page_title, title, source_url, site_name in rows:
        if total >= max_total:
            break
        if not code or code == final_code or code not in codes:
            continue
        bucket = rejected.setdefault(str(code), [])
        if len(bucket) >= per_category:
            continue
        label = clean_metadata_text(page_title or title, 120)
        if not label:
            continue
        bucket.append(
            {
                "title": label,
                "site": clean_metadata_text(site_name, 80) or "",
                "domain": _url_domain(source_url),
                "actual": labels.get(str(final_code), str(final_code)),
            }
        )
        total += 1
    return rejected


def _url_domain(source_url: str | None) -> str:
    """只保留域名，样本里不回传完整链接。"""

    if not source_url:
        return ""
    return urlsplit(source_url).netloc.lower()


def _primary_page_category(primary: str | None, extras: object) -> str:
    """聚类样本带上已有分类，方便模型把细类挂到对应大类。"""

    if primary:
        return primary
    if isinstance(extras, list) and extras:
        first = extras[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return ""


def library_pages_for_generation(
    session: Session,
    user_id: str,
    limit: int = MAX_LIBRARY_PAGES_FOR_GENERATION,
) -> list[dict[str, str]]:
    """取出最近网页的标题、站点和公开摘要，供聚类生成标签。

    不读取收藏备注或图片；摘要只来自页面元数据。
    确认失效的网页不进入样本。按已有大类交错取样，避免全是同一类。
    """

    rows = session.execute(
        select(
            Memo.resource_page_title,
            Memo.title,
            Memo.resource_site_name,
            Memo.source_url,
            Memo.resource_description,
            Memo.resource_category,
            Memo.resource_categories,
        )
        .where(
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != "trashed",
            Memo.link_health_status != "failed",
        )
        .order_by(Memo.updated_at.desc(), Memo.id.desc())
        .limit(_LIBRARY_PAGE_POOL)
    ).all()
    buckets: dict[str, list[dict[str, str]]] = {}
    for (
        page_title,
        title,
        site_name,
        source_url,
        description,
        primary,
        extras,
    ) in rows:
        label = clean_metadata_text(page_title or title, 120)
        if not label:
            continue
        page: dict[str, str] = {"title": label}
        site = clean_metadata_text(site_name, 80)
        if site:
            page["site"] = site
        domain = _url_domain(source_url)
        if domain:
            page["domain"] = domain
        summary = clean_metadata_text(description, 80)
        if summary:
            page["summary"] = summary
        category = _primary_page_category(primary, extras)
        if category:
            page["category"] = category
        buckets.setdefault(category, []).append(page)
    selected: list[dict[str, str]] = []
    cursors = {key: 0 for key in buckets}
    keys = list(buckets)
    while len(selected) < limit and keys:
        remaining: list[str] = []
        for key in keys:
            index = cursors[key]
            group = buckets[key]
            if index >= len(group):
                continue
            selected.append(group[index])
            cursors[key] = index + 1
            if cursors[key] < len(group):
                remaining.append(key)
            if len(selected) >= limit:
                break
        keys = remaining
    return selected


def _imported_text(value: object, max_length: int) -> str | None:
    """备份还原时校验口径文本长度，超长直接截断。"""

    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned[:max_length] or None


def _templates_by_code(
    session: Session,
    user_id: str,
) -> dict[str, ResourceCategoryTemplate]:
    """一次读出当前用户全部分类，供深度和路径在内存里计算。"""

    return {
        template.code: template
        for template in list_category_templates(
            session,
            user_id,
            include_inactive=True,
        )
    }


def _depth_from_map(
    templates_by_code: Mapping[str, ResourceCategoryTemplate],
    category_code: str,
) -> int:
    """用已加载的模板计算深度，避免按父节点反复查库。"""

    depth = 1
    current: str | None = category_code
    seen: set[str] = set()
    while current and current not in seen and depth <= MAX_CATEGORY_DEPTH + 1:
        seen.add(current)
        if current in SYSTEM_CATEGORY_CODES:
            return depth
        template = templates_by_code.get(current)
        if template is None or not template.parent_code:
            return depth
        current = template.parent_code
        depth += 1
    return depth


def _path_from_map(
    templates_by_code: Mapping[str, ResourceCategoryTemplate],
    category_code: str,
) -> str:
    """用已加载的模板拼接显示路径。"""

    parts: list[str] = []
    current: str | None = category_code
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        system_label = CATEGORY_LABELS.get(current)
        if system_label is not None:
            parts.append(system_label)
            break
        template = templates_by_code.get(current)
        if template is None:
            break
        parts.append(template.name)
        current = template.parent_code
    return " / ".join(reversed(parts))


def _option_from_template(
    template: ResourceCategoryTemplate,
    templates_by_code: Mapping[str, ResourceCategoryTemplate],
) -> dict[str, object]:
    """把模板转成客户端选项，depth/path 只读内存。"""

    return {
        "id": template.id,
        "code": template.code,
        "name": template.name,
        "description": template.description,
        "definition": template.definition,
        "include_examples": template.include_examples,
        "exclude_examples": template.exclude_examples,
        "is_system": False,
        "is_active": template.is_active,
        "version": template.version,
        "parent_code": template.parent_code,
        "depth": _depth_from_map(templates_by_code, template.code),
        "path": _path_from_map(templates_by_code, template.code) or template.name,
    }


def descendant_category_codes(
    session: Session,
    user_id: str,
    category_code: str,
) -> list[str]:
    """返回分类自身及其全部子分类编码。"""

    children: dict[str | None, list[str]] = {}
    for template in list_category_templates(session, user_id, include_inactive=True):
        children.setdefault(template.parent_code, []).append(template.code)
    codes: list[str] = []

    def walk(current: str) -> None:
        codes.append(current)
        for child in children.get(current, []):
            walk(child)

    walk(category_code)
    return codes


def _order_category_options(
    options: list[dict[str, object]],
) -> list[dict[str, object]]:
    """按树前序排列：父分类紧挨着子分类。"""

    by_parent: dict[str | None, list[dict[str, object]]] = {}
    for option in options:
        parent = option.get("parent_code")
        parent_code = parent if isinstance(parent, str) else None
        by_parent.setdefault(parent_code, []).append(option)
    ordered: list[dict[str, object]] = []

    def walk(parent_code: str | None) -> None:
        for option in by_parent.get(parent_code, []):
            ordered.append(option)
            walk(str(option["code"]))

    walk(None)
    return ordered


def _parent_depth(session: Session, user_id: str, parent_code: str | None) -> int:
    """父分类深度；顶级视为 0，子分类深度为父深度 + 1。"""

    if parent_code is None:
        return 0
    if not category_code_exists(session, user_id, parent_code, active_only=False):
        raise CategoryParentError("父分类不存在")
    return get_category_depth(session, user_id, parent_code)


def _ensure_parent_allows_child(
    session: Session,
    user_id: str,
    parent_code: str | None,
    subtree_height: int = 1,
) -> None:
    """子分类深度加上自身子树不能超过三层。"""

    parent_depth = _parent_depth(session, user_id, parent_code)
    if parent_depth + subtree_height > MAX_CATEGORY_DEPTH:
        raise CategoryParentError("分类最多支持三层")


def _subtree_height(session: Session, user_id: str, category_code: str) -> int:
    """当前分类子树高度，叶子为 1。"""

    children = [
        template.code
        for template in list_category_templates(session, user_id, include_inactive=True)
        if template.parent_code == category_code
    ]
    if not children:
        return 1
    return 1 + max(_subtree_height(session, user_id, child) for child in children)


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
    parent_code: str | None = None,
    *,
    definition: str | None = None,
    include_examples: str | None = None,
    exclude_examples: str | None = None,
) -> ResourceCategoryTemplate:
    """创建用户分类模板，可挂在系统或自定义大类下。"""

    cleaned_name = name.strip()
    cleaned_parent = parent_code.strip() if parent_code else None
    _ensure_parent_allows_child(session, user_id, cleaned_parent)
    if _category_name_taken(session, user_id, cleaned_name, parent_code=cleaned_parent):
        raise CategoryNameConflictError("同一层级已有相同分类名称")
    template = ResourceCategoryTemplate(
        id=str(uuid4()),
        user_id=user_id,
        code=f"custom_{uuid4().hex}",
        parent_code=cleaned_parent,
        name=cleaned_name,
        description=description.strip() if description else None,
        definition=definition.strip() if definition else None,
        include_examples=include_examples.strip() if include_examples else None,
        exclude_examples=exclude_examples.strip() if exclude_examples else None,
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
        name = str(changes["name"]).strip()
        if not name:
            raise CategoryNameConflictError("分类名称不能为空")
        parent_for_name = (
            str(changes["parent_code"])
            if "parent_code" in changes and changes["parent_code"] is not None
            else template.parent_code
        )
        if "parent_code" in changes and changes["parent_code"] is None:
            parent_for_name = None
        if _category_name_taken(
            session,
            user_id,
            name,
            ignored_id=template.id,
            parent_code=parent_for_name,
        ):
            raise CategoryNameConflictError("同一层级已有相同分类名称")
        template.name = name
        session.execute(
            update(Memo)
            .where(
                Memo.user_id == user_id,
                Memo.resource_category == template.code,
            )
            .values(
                resource_category_label=template.name,
                version=Memo.version + 1,
                updated_at=datetime.now(UTC),
            ),
        )
    if "description" in changes:
        value = changes["description"]
        template.description = str(value) if value is not None else None
    for name in ("definition", "include_examples", "exclude_examples"):
        if name in changes:
            value = changes[name]
            setattr(template, name, str(value) if value is not None else None)
    if "is_active" in changes and changes["is_active"] is not None:
        template.is_active = bool(changes["is_active"])
    if "parent_code" in changes:
        new_parent = (
            str(changes["parent_code"])
            if changes["parent_code"] is not None
            else None
        )
        if new_parent == template.code:
            raise CategoryParentError("不能把分类挂到自己下面")
        descendants = set(descendant_category_codes(session, user_id, template.code))
        if new_parent in descendants:
            raise CategoryParentError("不能把分类挂到自己的子分类下")
        _ensure_parent_allows_child(
            session,
            user_id,
            new_parent,
            subtree_height=_subtree_height(session, user_id, template.code),
        )
        if _category_name_taken(
            session,
            user_id,
            template.name,
            ignored_id=template.id,
            parent_code=new_parent,
        ):
            raise CategoryNameConflictError("同一层级已有相同分类名称")
        template.parent_code = new_parent
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


def delete_category_template(
    session: Session,
    user_id: str,
    category_id: str,
) -> str:
    """删除用户分类模板，并清掉依赖它的规则与资料分类。"""

    template = get_category_template(session, user_id, category_id)
    category_code = template.code
    now = datetime.now(UTC)
    removed_codes = descendant_category_codes(session, user_id, category_code)
    session.execute(
        delete(ResourceCategoryRule).where(
            ResourceCategoryRule.user_id == user_id,
            ResourceCategoryRule.category_code.in_(removed_codes),
        )
    )
    child_templates = session.scalars(
        select(ResourceCategoryTemplate).where(
            ResourceCategoryTemplate.user_id == user_id,
            ResourceCategoryTemplate.code.in_(removed_codes),
            ResourceCategoryTemplate.id != template.id,
        )
    ).all()
    for child in child_templates:
        session.delete(child)
    _remove_codes_from_memos(session, user_id, set(removed_codes), now)
    session.delete(template)
    session.commit()
    return category_code


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


def _remove_codes_from_memos(
    session: Session,
    user_id: str,
    removed_codes: set[str],
    now: datetime,
) -> None:
    """从资料中去掉已删除分类，主分类被删时改用剩余分类。"""

    memos = session.scalars(
        select(Memo).where(
            Memo.user_id == user_id,
            Memo.type.in_((MemoType.RESOURCE, MemoType.IMAGE)),
        )
    )
    for memo in memos:
        current = list(memo.resource_categories or [])
        if memo.resource_category and memo.resource_category not in current:
            current.insert(0, memo.resource_category)
        if not any(code in removed_codes for code in current):
            continue
        remaining = [code for code in current if code not in removed_codes]
        memo.resource_categories = remaining
        memo.resource_category = remaining[0] if remaining else None
        memo.resource_category_label = (
            category_label(session, user_id, remaining[0]) if remaining else None
        )
        if remaining:
            memo.resource_category_status = ResourceProcessStatus.READY.value
        else:
            memo.resource_category_status = ResourceProcessStatus.PENDING.value
            memo.resource_category_confidence = None
            memo.resource_category_source = None
        memo.version += 1
        memo.updated_at = now


def assign_memo_categories(
    session: Session,
    user_id: str,
    memo: Memo,
    codes: list[str],
    *,
    manual: bool,
) -> None:
    """写入资料的多分类，第一个作为主分类。"""

    if manual:
        # 人工选择后清除旧模型建议，避免把旧候选当作新的人工分类依据。
        memo.resource_ai_assessment = None
        memo.resource_ai_confirmation_pending = False
        memo.resource_ai_confirmation = None
    unique_codes = list(dict.fromkeys(codes))[:MAX_RESOURCE_CATEGORIES]
    for code in unique_codes:
        if not category_code_exists(session, user_id, code, active_only=True):
            raise CategoryCodeNotFoundError("分类不存在或已停用")
    memo.resource_categories = unique_codes
    memo.resource_category = unique_codes[0] if unique_codes else None
    memo.resource_category_label = (
        category_label(session, user_id, unique_codes[0]) if unique_codes else None
    )
    if unique_codes and manual:
        memo.resource_category_status = ResourceProcessStatus.READY
        memo.resource_category_confidence = 1.0
        memo.resource_category_source = "manual"
    elif not unique_codes:
        memo.resource_category_status = ResourceProcessStatus.PENDING
        memo.resource_category_confidence = None
        memo.resource_category_source = None


def _category_name_taken(
    session: Session,
    user_id: str,
    name: str,
    ignored_id: str | None = None,
    parent_code: str | None = None,
) -> bool:
    """同一父分类下名称不能重复；顶级还不能占用系统分类名。"""

    cleaned_name = name.strip()
    if parent_code is None and cleaned_name.casefold() in {
        label.casefold() for label in CATEGORY_LABELS.values()
    }:
        return True
    query = select(ResourceCategoryTemplate.id).where(
        ResourceCategoryTemplate.user_id == user_id,
        func.lower(ResourceCategoryTemplate.name) == cleaned_name.casefold(),
    )
    if parent_code is None:
        query = query.where(ResourceCategoryTemplate.parent_code.is_(None))
    else:
        query = query.where(ResourceCategoryTemplate.parent_code == parent_code)
    if ignored_id is not None:
        query = query.where(ResourceCategoryTemplate.id != ignored_id)
    return session.scalar(query) is not None
