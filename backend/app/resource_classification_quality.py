"""分类质量证据的白名单解析，不保存上游原始响应或自由文本。"""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from math import isfinite
from typing import Literal, NotRequired, TypedDict

MAX_PUBLIC_EXCERPT_CHARS = 3000
MAX_REASON_CHARS = 200

# 网页字段、目录名和样本都可能被上游塞入指令，判定文本一律压缩并限长。
_CONTROL_CHARS = dict.fromkeys(
    [value for value in range(32) if chr(value) not in "\n\t"] + [127],
)


class ClassificationConfirmation(TypedDict):
    """人工确认独立于模型置信度，不把人工操作记作模型成功。"""

    action: Literal["adopt", "keep", "assign"]
    confirmed_at: str
    category_code: str | None
    category_label: str | None


class ClassificationCandidate(TypedDict):
    """来自当前账号模板的候选类别，概率与置信度分别展示。"""

    code: str
    label: str
    probability: float | None


class ClassificationAssessment(TypedDict):
    """可安全保存和展示的单次模型判断。"""

    status: Literal["classified", "uncertain"]
    reason_code: str
    confidence: float | None
    threshold: float
    candidates: list[ClassificationCandidate]
    input_source: Literal["metadata", "public_excerpt", "image_ocr"]
    input_excerpt: str | None
    model: str
    attempted_at: str
    # 模型写下的判定依据（已压缩限长），以及本次是否动用了系统兜底类。
    reason: NotRequired[str]
    fallback_used: NotRequired[bool]
    # 对话模型列出的全部成立标签；Jev 定案后仍保留，供界面展示。
    proposed_categories: NotRequired[list[ClassificationCandidate]]


class UncertainClassificationError(ValueError):
    """保留候选证据，但不允许覆盖现有分类。"""

    def __init__(self, assessment: ClassificationAssessment) -> None:
        super().__init__("uncertain_or_invalid_jev_category")
        self.assessment = assessment


def valid_probability(value: object) -> bool:
    """拒绝布尔、非有限值和超出零到一范围的数值。"""

    return type(value) in (int, float) and 0 <= value <= 1 and isfinite(value)


def empty_assessment(
    reason_code: str,
    threshold: float,
    model: str,
    has_excerpt: bool,
    excerpt: str | None = None,
) -> ClassificationAssessment:
    """使用固定原因编码，绝不保留原始异常消息。"""

    return {
        "status": "uncertain",
        "reason_code": reason_code,
        "confidence": None,
        "threshold": threshold,
        "candidates": [],
        "input_source": "public_excerpt" if has_excerpt else "metadata",
        "input_excerpt": " ".join(excerpt.split())[:MAX_PUBLIC_EXCERPT_CHARS]
        if excerpt
        else None,
        "model": model,
        "attempted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def sanitize_reason(value: object) -> str | None:
    """把模型写的依据压成单行短文本，拒绝控制字符和超长内容。"""

    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.translate(_CONTROL_CHARS).split())
    return cleaned[:MAX_REASON_CHARS] or None


def completion_content(payload: object) -> str | None:
    """读取 OpenAI 兼容响应的首个消息正文。"""

    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def listed_categories(
    codes: Sequence[str],
    labels: Mapping[str, str],
    *,
    limit: int | None = None,
) -> list[ClassificationCandidate]:
    """把白名单内的分类编码写成可展示的标签列表。"""

    items: list[ClassificationCandidate] = []
    seen: set[str] = set()
    for code in codes:
        if not isinstance(code, str) or code not in labels or code in seen:
            continue
        seen.add(code)
        items.append({"code": code, "label": labels[code], "probability": None})
        if limit is not None and len(items) >= limit:
            break
    return items


def parse_alternatives(
    value: object,
    category_labels: Mapping[str, str],
    selected: str | None,
    limit: int = 3,
) -> list[ClassificationCandidate]:
    """只保留白名单内的候选类别，忽略模型自造的分类。"""

    if not isinstance(value, list):
        return []
    candidates: list[ClassificationCandidate] = []
    seen: set[str] = set()
    for item in value:
        code = item.get("code") if isinstance(item, dict) else None
        if (
            not isinstance(code, str)
            or code not in category_labels
            or code == selected
            or code in seen
        ):
            continue
        seen.add(code)
        candidates.append(
            {"code": code, "label": category_labels[code], "probability": None}
        )
        if len(candidates) >= limit:
            break
    return candidates


def parse_model_assessment(
    payload: object,
    category_labels: Mapping[str, str],
    threshold: float,
    model: str,
    has_excerpt: bool,
    excerpt: str | None = None,
) -> tuple[str, ClassificationAssessment]:
    """解析对话模型的分类 JSON：类别、置信度、依据和候选。"""

    assessment = empty_assessment(
        "invalid_response", threshold, model, has_excerpt, excerpt
    )
    content = completion_content(payload)
    if content is None:
        raise UncertainClassificationError(assessment)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        raise UncertainClassificationError(assessment) from None
    if not isinstance(parsed, dict):
        raise UncertainClassificationError(assessment)
    reason = sanitize_reason(parsed.get("reason"))
    if reason is not None:
        assessment["reason"] = reason
    selected = parsed.get("category")
    confidence = parsed.get("confidence")
    if not valid_probability(confidence):
        raise UncertainClassificationError(assessment)
    assessment["confidence"] = float(confidence)
    alternatives = parse_alternatives(
        parsed.get("alternatives"),
        category_labels,
        selected if isinstance(selected, str) else None,
    )
    if not isinstance(selected, str) or selected not in category_labels:
        assessment["reason_code"] = "unknown_category"
        assessment["candidates"] = alternatives
        raise UncertainClassificationError(assessment)
    assessment["candidates"] = [
        {"code": selected, "label": category_labels[selected], "probability": None},
        *alternatives,
    ][:3]
    if confidence < threshold:
        assessment["reason_code"] = "low_confidence"
        raise UncertainClassificationError(assessment)
    assessment["status"] = "classified"
    assessment["reason_code"] = "accepted"
    return selected, assessment


def parse_jev_assessment(
    payload: object,
    category_labels: Mapping[str, str],
    threshold: float,
    model: str,
    has_excerpt: bool,
    excerpt: str | None = None,
) -> tuple[str, ClassificationAssessment]:
    """校验类别、置信度和候选分布；低置信度返回结构化失败证据。"""

    assessment = empty_assessment(
        "invalid_response", threshold, model, has_excerpt, excerpt
    )
    answers = payload.get("answers") if isinstance(payload, dict) else None
    answer = answers.get("category") if isinstance(answers, dict) else None
    if not isinstance(answer, dict):
        raise UncertainClassificationError(assessment)
    selected = answer.get("choice")
    confidence = answer.get("confidence")
    if not valid_probability(confidence):
        raise UncertainClassificationError(assessment)
    assessment["confidence"] = float(confidence)
    if not isinstance(selected, str) or selected not in category_labels:
        assessment["reason_code"] = "unknown_category"
        raise UncertainClassificationError(assessment)

    probabilities = answer.get("probabilities")
    if probabilities is not None:
        # 允许中转省略分布；提供分布时必须与选中类别相符且均为有效数值。
        if (
            not isinstance(probabilities, dict)
            or selected not in probabilities
            or any(not valid_probability(value) for value in probabilities.values())
            or probabilities[selected] < max(probabilities.values(), default=0)
            or abs(sum(probabilities.values()) - 1) > 0.05
        ):
            raise UncertainClassificationError(assessment)
        assessment["candidates"] = [
            {"code": code, "label": category_labels[code], "probability": float(value)}
            for code, value in sorted(
                probabilities.items(), key=lambda item: item[1], reverse=True
            )
            if code in category_labels
        ][:3]
    else:
        assessment["candidates"] = [
            {
                "code": selected,
                "label": category_labels[selected],
                "probability": None,
            }
        ]
    if confidence < threshold:
        assessment["reason_code"] = "low_confidence"
        raise UncertainClassificationError(assessment)
    assessment["status"] = "classified"
    assessment["reason_code"] = "accepted"
    return selected, assessment
