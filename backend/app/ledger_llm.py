"""一句话记账的本地大模型识别（Ollama、LM Studio、vLLM 等 OpenAI 兼容接口）。

只在配置了 ``MEMOISLE_LEDGER_LLM_BASE_URL`` 和 ``MEMOISLE_LEDGER_LLM_MODEL`` 时启用，
与会议总结的 ``MEMOISLE_LLM_*`` 分开，避免记账内容被发到云端模型。

模型只负责把一句话拆成字段，结果逐项校验：
- 金额必须换算成正的整数分，且不超过单笔上限；
- 句中写了规则认得出的日期（今天、昨天、3月5号等）时以规则为准，
  模型给的日期越界或晚于明天时改用今天；
- 分类只能是预设分类或该账号用过的分类，否则改用规则选的分类；
- 账户必须在原句里出现，否则改用规则识别的账户；备注固定为原句。

任何一步不合格都抛 ``LedgerLlmUnavailableError``，由调用方退回规则解析。
日志只记录状态码或异常类型，不记录句子原文和密钥。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.ledger_parser import (
    EXPENSE_CATEGORY_KEYWORDS,
    FALLBACK_CATEGORY,
    INCOME_CATEGORY_KEYWORDS,
    LedgerParseError,
    detect_account,
    detect_category,
    find_dates,
    normalize_sentence,
)
from app.schemas import (
    LEDGER_ACCOUNT_MAX_LENGTH,
    LEDGER_DEFAULT_CURRENCY,
    LEDGER_MAX_AMOUNT_CENTS,
    LEDGER_MAX_DATE,
    LEDGER_MIN_DATE,
    LEDGER_NOTE_MAX_LENGTH,
    LedgerEntryCreate,
    LedgerKind,
)

logger = logging.getLogger(__name__)

MAX_TOKENS = 256
# 每个方向最多把这么多个用过的分类告诉模型，控制提示长度。
MAX_KNOWN_CATEGORIES = 50
_WEEKDAYS = "一二三四五六日"
_FENCE = re.compile(r"```[A-Za-z0-9_-]*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_KIND_ALIASES: dict[str, LedgerKind] = {
    "expense": "expense",
    "支出": "expense",
    "income": "income",
    "收入": "income",
}

_EXAMPLE_REPLY = json.dumps(
    {
        "kind": "expense",
        "amount": 25,
        "currency": "CNY",
        "occurred_on": "2026-03-09",
        "category": "交通",
        "account": "微信",
    },
    ensure_ascii=False,
)
_SYSTEM_PROMPT = "\n".join(
    (
        "你是记账助手，把用户的一句话识别成一笔收支。",
        "只输出一个 JSON 对象，不要输出解释、Markdown 或其他文字。字段：",
        '- kind：支出写 "expense"，收入写 "income"',
        "- amount：金额，单位是元的数字，最多两位小数，如 10 或 12.5",
        '- currency：三位大写币种代码，如 CNY、USD、HKD；没写币种时用 "CNY"',
        "- occurred_on：发生日期，格式 YYYY-MM-DD；按给出的“今天”换算"
        "“昨天”“前天”“上周五”等，没写日期就用今天",
        "- category：分类，只能从给出的同方向分类里原样选一个，都不合适时选“其他”",
        "- account：句中明确写到的付款或收款账户，如微信、支付宝、现金、信用卡；"
        "没写就是 null",
        '一句话里有多笔金额，或者没有金额时，只输出 {"error": "原因"}。',
        "",
        "示例：今天是 2026-03-10，一句话“昨天微信打车25块”，输出",
        _EXAMPLE_REPLY,
    )
)


class LedgerLlmUnavailableError(RuntimeError):
    """模型未配置、连不上、超时、拒答或回复不合格；只在服务端内部使用，不展示给用户。"""


def ledger_llm_enabled(settings: Settings) -> bool:
    """配置了接口地址和模型名才启用。"""

    return bool(settings.ledger_llm_base_url and settings.ledger_llm_model.strip())


def _preset_categories(kind: LedgerKind) -> list[str]:
    table = INCOME_CATEGORY_KEYWORDS if kind == "income" else EXPENSE_CATEGORY_KEYWORDS
    return [category for category, _ in table] + [FALLBACK_CATEGORY]


def allowed_categories(
    kind: LedgerKind, known_categories: Iterable[tuple[str, str]]
) -> list[str]:
    """预设分类加上该账号在这个方向用过的分类（按调用方给的顺序，常用的在前）。"""

    categories = _preset_categories(kind)
    used = 0
    for category_kind, category in known_categories:
        if used >= MAX_KNOWN_CATEGORIES:
            break
        if category_kind == kind and category not in categories:
            categories.append(category)
            used += 1
    return categories


def _user_prompt(note: str, today: date, allowed: dict[LedgerKind, list[str]]) -> str:
    return (
        f"今天是 {today.isoformat()}（星期{_WEEKDAYS[today.weekday()]}）。\n"
        f"支出分类：{'、'.join(allowed['expense'])}\n"
        f"收入分类：{'、'.join(allowed['income'])}\n"
        f"一句话：{note}"
    )


def _create_client(settings: Settings) -> httpx.Client:
    # 直连本地模型，不读 HTTP(S)_PROXY：免得记账内容经代理转发，或本机地址被代理拦下。
    return httpx.Client(timeout=settings.ledger_llm_timeout_seconds, trust_env=False)


def _ask_model(prompt: str, settings: Settings, client: httpx.Client | None) -> str:
    """调用 /chat/completions 并返回回复正文。"""

    headers = {"Content-Type": "application/json"}
    if settings.ledger_llm_api_key:
        headers["Authorization"] = f"Bearer {settings.ledger_llm_api_key}"
    base_url = (settings.ledger_llm_base_url or "").rstrip("/")
    owned_client = client is None
    request_client = client or _create_client(settings)
    try:
        response = request_client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            # 不传 response_format：部分本地服务不支持，靠提示词约束只输出 JSON。
            json={
                "model": settings.ledger_llm_model.strip(),
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": MAX_TOKENS,
                "stream": False,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as error:
        raise LedgerLlmUnavailableError(
            f"HTTP {error.response.status_code}"
        ) from error
    except httpx.HTTPError as error:
        raise LedgerLlmUnavailableError(type(error).__name__) from error
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise LedgerLlmUnavailableError("回复不是 chat/completions 格式") from error
    finally:
        # 只关闭本函数创建的客户端，外部注入的由调用方管理。
        if owned_client:
            request_client.close()
    if not isinstance(content, str) or not content.strip():
        raise LedgerLlmUnavailableError("回复为空")
    return content


def extract_json_object(reply: str) -> dict[str, object]:
    """去掉思考过程和代码围栏后，取回复里第一个 JSON 对象。"""

    text = reply
    if "</think>" in text:
        # 有的服务会吞掉开头的 <think>，只留结尾标签；答案总在最后一个结尾标签之后。
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        # 思考过程没写完就被截断，后面不会有答案。
        text = text.split("<think>", 1)[0]
    text = _FENCE.sub("", text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise LedgerLlmUnavailableError("回复里没有 JSON 对象")


def _amount_cents(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise LedgerLlmUnavailableError("金额不是数字")
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation as error:
        raise LedgerLlmUnavailableError("金额不是数字") from error
    if not amount.is_finite():
        raise LedgerLlmUnavailableError("金额不是数字")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise LedgerLlmUnavailableError("金额超过两位小数")
    cents_int = int(cents)
    if not 0 < cents_int <= LEDGER_MAX_AMOUNT_CENTS:
        raise LedgerLlmUnavailableError("金额超出范围")
    return cents_int


def _resolve_date(value: object, normalized: str, today: date) -> date:
    try:
        rule_date, _ = find_dates(normalized, today)
    except LedgerParseError as error:
        # 句中写了不存在的日期，交给规则给出明确提示，不让模型猜。
        raise LedgerLlmUnavailableError("句中日期不存在") from error
    if rule_date is not None:
        return rule_date
    if isinstance(value, str) and _DATE.fullmatch(value.strip()):
        try:
            model_date = date.fromisoformat(value.strip())
        except ValueError:
            model_date = None
        latest = min(today + timedelta(days=1), LEDGER_MAX_DATE)
        if model_date is not None and LEDGER_MIN_DATE <= model_date <= latest:
            return model_date
    return today


def _resolve_category(
    value: object,
    kind: LedgerKind,
    normalized: str,
    allowed: list[str],
    known_categories: list[tuple[str, str]],
) -> str:
    if isinstance(value, str):
        folded = value.strip().casefold()
        for category in allowed:
            if category.casefold() == folded:
                return category
    return detect_category(normalized, kind, known_categories)


def _resolve_account(value: object, normalized: str) -> str | None:
    if isinstance(value, str):
        account = normalize_sentence(value.strip())
        if (
            account
            and len(account) <= LEDGER_ACCOUNT_MAX_LENGTH
            and account.casefold() in normalized.casefold()
        ):
            return account
    return detect_account(normalized)


def _build_entry(
    data: dict[str, object],
    note: str,
    today: date,
    known_categories: list[tuple[str, str]],
    allowed: dict[LedgerKind, list[str]],
) -> LedgerEntryCreate:
    if data.get("error"):
        raise LedgerLlmUnavailableError("模型判断这句话记不成一笔")
    kind_value = data.get("kind")
    kind = (
        _KIND_ALIASES.get(kind_value.strip().lower())
        if isinstance(kind_value, str)
        else None
    )
    if kind is None:
        raise LedgerLlmUnavailableError("收支方向无效")
    cents = _amount_cents(data.get("amount"))
    normalized = normalize_sentence(note)
    currency = data.get("currency") or LEDGER_DEFAULT_CURRENCY
    try:
        return LedgerEntryCreate(
            kind=kind,
            amount_cents=cents,
            currency=currency,
            occurred_on=_resolve_date(data.get("occurred_on"), normalized, today),
            category=_resolve_category(
                data.get("category"), kind, normalized, allowed[kind], known_categories
            ),
            account=_resolve_account(data.get("account"), normalized),
            note=note,
        )
    except ValidationError as error:
        raise LedgerLlmUnavailableError("字段校验未通过") from error


def parse_with_llm(
    text: str,
    today: date,
    known_categories: Iterable[tuple[str, str]],
    settings: Settings,
    client: httpx.Client | None = None,
) -> LedgerEntryCreate:
    """让本地模型把一句话识别成一笔收支。

    模型不可用或结果不合格时抛 ``LedgerLlmUnavailableError``，由调用方退回规则。
    ``known_categories`` 是该账号用过的 ``(kind, category)``，常用的在前。
    """

    if not ledger_llm_enabled(settings):
        raise LedgerLlmUnavailableError("未配置本地模型")
    note = text.strip()
    if not note or len(note) > LEDGER_NOTE_MAX_LENGTH:
        raise LedgerLlmUnavailableError("句子为空或过长")
    known = list(known_categories)
    allowed: dict[LedgerKind, list[str]] = {
        "expense": allowed_categories("expense", known),
        "income": allowed_categories("income", known),
    }
    try:
        reply = _ask_model(_user_prompt(note, today, allowed), settings, client)
        return _build_entry(extract_json_object(reply), note, today, known, allowed)
    except LedgerLlmUnavailableError as error:
        # 原因都是固定短语、状态码或异常类型，不含句子原文和密钥。
        logger.warning("本地模型识别记账失败（%s），改用规则识别", error)
        raise


__all__ = [
    "LedgerLlmUnavailableError",
    "allowed_categories",
    "extract_json_object",
    "ledger_llm_enabled",
    "parse_with_llm",
]
