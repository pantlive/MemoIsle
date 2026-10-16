"""把审阅过的分类口径草稿写回分类模板。

会补齐新增的可空字段，只更新草稿里出现的分类，不动任何网页条目，
写完不会自动重跑分类。
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from _classification_cli import resolve_account  # noqa: E402
from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.models import ResourceCategoryTemplate  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

MAX_DEFINITION_CHARS = 600
MAX_EXAMPLE_CHARS = 800


def main() -> None:
    """入口：读取草稿 → 写回模板口径 → 打印结果。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", help="draft_category_definitions.py 输出的 JSON")
    parser.add_argument("--user-id", default=None, help="默认取资料最多的账号")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要写入的内容，不修改数据库",
    )
    args = parser.parse_args()

    payload = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    drafts = {
        str(code): draft for code, draft in (payload.get("categories") or {}).items()
    }
    if not drafts:
        raise SystemExit("草稿里没有分类口径")

    settings = Settings.from_environment()
    database = Database(settings.database_url)
    database.create_schema()
    updated = 0
    with Session(database.engine) as session:
        user_id, _resolved = resolve_account(session, settings, args.user_id)
        templates = {
            template.code: template
            for template in session.scalars(
                select(ResourceCategoryTemplate).where(
                    ResourceCategoryTemplate.user_id == user_id,
                )
            )
        }
        for code, draft in drafts.items():
            template = templates.get(code)
            if template is None:
                print(f"跳过（库里没有这个分类）：{code}")
                continue
            definition = str(draft.get("definition") or "").strip()[
                :MAX_DEFINITION_CHARS
            ]
            include_examples = str(draft.get("include_examples") or "").strip()[
                :MAX_EXAMPLE_CHARS
            ]
            exclude_examples = str(draft.get("exclude_examples") or "").strip()[
                :MAX_EXAMPLE_CHARS
            ]
            changed = (
                template.definition != (definition or None)
                or template.include_examples != (include_examples or None)
                or template.exclude_examples != (exclude_examples or None)
            )
            if not changed:
                print(f"未变化：{template.name}")
                continue
            print(f"写入：{template.name}（口径 {len(definition)} 字）")
            if args.dry_run:
                continue
            template.definition = definition or None
            template.include_examples = include_examples or None
            template.exclude_examples = exclude_examples or None
            template.version += 1
            template.updated_at = datetime.now(UTC)
            updated += 1
        if args.dry_run:
            session.rollback()
            print("dry-run：未写入任何内容")
            return
        session.commit()
    print(f"完成：更新 {updated} 个分类的口径")


if __name__ == "__main__":
    main()
