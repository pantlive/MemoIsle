"""抽样对比：用新的分类口径判定真实资料，和现有分类摆在一起看。

只读取数据库，不修改任何条目；会调用账号配置的 DeepSeek，费用按条计。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import httpx  # noqa: E402
from _classification_cli import (  # noqa: E402
    classification_options,
    resolve_account,
)
from _classification_cli import exemplars as load_exemplars  # noqa: E402
from _classification_cli import (
    rejected_examples as load_rejects,
)
from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.models import Memo  # noqa: E402
from app.resource_classification_judge import judge_resource_category  # noqa: E402
from app.resource_classification_quality import (  # noqa: E402
    UncertainClassificationError,
)
from app.resource_processing import judge_category  # noqa: E402
from app.resource_service import fallback_metadata  # noqa: E402
from app.schemas import MemoType  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


class UsageTrackingClient(httpx.Client):
    """记录调用次数与 token 用量，方便估算全量重跑成本。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def post(self, *args: object, **kwargs: object) -> httpx.Response:
        response = super().post(*args, **kwargs)
        self.calls += 1
        try:
            usage = response.json().get("usage") or {}
        except ValueError:
            usage = {}
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        return response


def load_definitions(path: str | None) -> dict[str, dict[str, str]]:
    """可选的分类口径草稿，用于在不写库的情况下试跑。"""

    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        str(code): {key: str(value or "") for key, value in draft.items()}
        for code, draft in (payload.get("categories") or {}).items()
    }


def pick_sample(session: Session, user_id: str, limit: int) -> list[Memo]:
    """人工确认过的条目优先入选，其余补最近新增的资料。"""

    base = select(Memo).where(
        Memo.user_id == user_id,
        Memo.type == MemoType.RESOURCE,
        Memo.status != "trashed",
        Memo.source_url.is_not(None),
        Memo.ebook_provider.is_(None),
    )
    manual = list(
        session.scalars(
            base.where(Memo.resource_category_source == "manual").order_by(
                Memo.updated_at.desc()
            )
        )
    )
    recent = list(
        session.scalars(
            base.order_by(Memo.created_at.desc(), Memo.id.desc()).limit(limit * 3)
        )
    )
    chosen: list[Memo] = []
    seen: set[str] = set()
    for memo in [*manual, *recent]:
        if memo.id in seen:
            continue
        seen.add(memo.id)
        chosen.append(memo)
        if len(chosen) >= limit:
            break
    return chosen


def without_self(
    samples: dict[str, list[dict[str, str]]],
    title: str | None,
) -> dict[str, list[dict[str, str]]]:
    """判定某条资料时，不把它自己的历史标注当成样本。"""

    if not title:
        return samples
    cleaned = " ".join(title.split())
    return {
        code: [item for item in items if item.get("title") != cleaned]
        for code, items in samples.items()
    }


def label_for(categories: list, code: str | None) -> str:
    """分类显示名，优先用路径。"""

    for category in categories:
        if category.code == code:
            return category.path or category.label
    return code or "未分类"


def judge_one(
    memo: Memo,
    categories: list,
    samples: dict[str, list[dict[str, str]]],
    rejects: dict[str, list[dict[str, str]]],
    resolved: Settings,
    client: UsageTrackingClient,
) -> dict[str, object]:
    """判定单条资料，返回可打印、可落盘的一行结果。"""

    metadata = fallback_metadata(memo)
    title = metadata.page_title or memo.title or metadata.final_url
    primary = [item for item in categories if not item.is_fallback]
    fallback = [item for item in categories if item.is_fallback]
    try:
        judged = judge_resource_category(
            url=metadata.final_url,
            page_title=metadata.page_title,
            description=metadata.description,
            site_name=metadata.site_name,
            text_excerpt=metadata.text_excerpt,
            categories=[judge_category(item) for item in primary],
            fallback_categories=[judge_category(item) for item in fallback],
            exemplars=without_self(samples, metadata.page_title),
            rejected=rejects,
            api_key=resolved.deepseek_api_key or "",
            base_url=resolved.deepseek_base_url,
            model=resolved.deepseek_model,
            min_confidence=resolved.classification_min_confidence,
            timeout_seconds=resolved.deepseek_timeout_seconds,
            client=client,
        )
    except UncertainClassificationError as error:
        return {
            "title": title,
            "current": label_for(categories, memo.resource_category),
            "current_source": memo.resource_category_source,
            "new": None,
            "confidence": error.assessment.get("confidence"),
            "fallback_used": None,
            "reason": error.assessment.get("reason"),
            "reason_code": error.assessment["reason_code"],
            "candidates": [
                item["label"] for item in error.assessment.get("candidates", [])
            ],
        }
    return {
        "title": title,
        "current": label_for(categories, memo.resource_category),
        "current_source": memo.resource_category_source,
        "new": label_for(categories, judged.category),
        "new_code": judged.category,
        "confidence": judged.confidence,
        "fallback_used": judged.fallback_used,
        "reason": judged.assessment.get("reason"),
        "reason_code": judged.assessment["reason_code"],
    }


def print_row(index: int, row: dict[str, object]) -> None:
    """打印一条对照。"""

    print(f"\n{index}. {str(row['title'])[:70]}")
    print(f"   现在：{row['current']}（{row['current_source']}）")
    if row["new"] is None:
        candidates = row.get("candidates") or []
        suffix = (
            " 候选：" + "、".join(str(item) for item in candidates)
            if candidates
            else ""
        )
        score = (
            f" · {float(row['confidence']):.2f}"
            if row.get("confidence") is not None
            else ""
        )
        print(f"   新判定：未确定（{row['reason_code']}{score}）{suffix}")
    else:
        marker = "兜底" if row["fallback_used"] else "细类"
        print(f"   新判定：{row['new']}（{marker} · {float(row['confidence']):.2f}）")
    if row.get("reason"):
        print(f"   依据：{row['reason']}")


def summarize(rows: list[dict[str, object]], client: UsageTrackingClient) -> None:
    """打印汇总，供判断口径是否值得写回。"""

    moved = sum(1 for row in rows if row["new"] and row["new"] != row["current"])
    custom = sum(1 for row in rows if row["new"] and not row["fallback_used"])
    fallback = sum(1 for row in rows if row["fallback_used"])
    uncertain = sum(1 for row in rows if row["new"] is None)
    manual_rows = [row for row in rows if row["current_source"] == "manual"]
    manual_match = sum(1 for row in manual_rows if row["new"] == row["current"])
    print("\n===== 汇总 =====")
    print(
        f"样本 {len(rows)} 条 · 与现有分类不同 {moved} 条 · "
        f"落入自定义细类 {custom} 条"
    )
    print(f"使用系统兜底 {fallback} 条 · 未确定 {uncertain} 条")
    if manual_rows:
        print(f"与你手工标注一致 {manual_match}/{len(manual_rows)} 条")
    print(
        f"模型调用 {client.calls} 次 · 输入 {client.prompt_tokens} tokens · "
        f"输出 {client.completion_tokens} tokens"
    )


def main() -> None:
    """入口：抽样 → 判定 → 打印对照表和汇总。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="抽样条数，默认 30")
    parser.add_argument("--user-id", default=None, help="默认取资料最多的账号")
    parser.add_argument(
        "--definitions",
        default=None,
        help="口径草稿 JSON（draft_category_definitions.py 的输出）",
    )
    parser.add_argument("--output", default=None, help="明细写入路径")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="覆盖判定阈值，用于比较自动分类比例",
    )
    args = parser.parse_args()

    settings = Settings.from_environment()
    database = Database(settings.database_url)
    definitions = load_definitions(args.definitions)
    with Session(database.engine) as session:
        user_id, resolved = resolve_account(session, settings, args.user_id)
        if args.min_confidence is not None:
            resolved = replace(
                resolved,
                classification_min_confidence=args.min_confidence,
            )
        if not resolved.deepseek_api_key or not resolved.deepseek_model:
            raise SystemExit("请先在设置 → 模型服务中配置并启用 DeepSeek")
        categories = classification_options(session, user_id, definitions)
        samples = load_exemplars(session, user_id, categories)
        rejects = load_rejects(session, user_id, categories)
        sample = pick_sample(session, user_id, args.limit)
        primary = [item for item in categories if not item.is_fallback]
        scoped = sum(1 for item in primary if item.definition)
        print(
            f"模型 {resolved.deepseek_model} · 阈值 "
            f"{resolved.classification_min_confidence:g} · "
            f"自定义分类 {len(primary)} 个 · "
            f"已确认样本 {sum(len(v) for v in samples.values())} 条 · "
            f"反例 {sum(len(v) for v in rejects.values())} 条"
        )
        print(
            "口径来源："
            + (f"草稿文件 {args.definitions}" if definitions else "无")
            + f"（{scoped}/{len(primary)} 个分类带口径）"
        )
        rows: list[dict[str, object]] = []
        client = UsageTrackingClient()
        for index, memo in enumerate(sample, start=1):
            row = judge_one(memo, categories, samples, rejects, resolved, client)
            rows.append(row)
            print_row(index, row)

    summarize(rows, client)
    if args.output:
        output = Path(args.output)
        output.write_text(
            json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"明细已写入 {output}")


if __name__ == "__main__":
    main()
