"""一句话记账：用固定规则把“今天早饭花了10元”拆成一笔收支。

不调用大模型，同一句话、同一个“今天”总是得到同一结果，没配模型也能用；
配置了本地模型时（见 ``ledger_llm``），这里是模型失败后的兜底。
识别不出金额、识别到多笔或日期不存在时抛出 ``LedgerParseError``，不写入任何数据。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from pydantic import ValidationError

from app.schemas import (
    LEDGER_DEFAULT_CURRENCY,
    LEDGER_MAX_AMOUNT_CENTS,
    LEDGER_MAX_DATE,
    LEDGER_MIN_DATE,
    LEDGER_NOTE_MAX_LENGTH,
    LedgerEntryCreate,
    LedgerKind,
)

# 与 web/src/ledger.ts 的 LEDGER_PRESET_CATEGORIES 保持一致。
FALLBACK_CATEGORY = "其他"
# 关键词按“最长优先、同样长按表中顺序”匹配；购物放最后，
# 让“买菜”“买药”“买机票”先归到更具体的分类。
EXPENSE_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (category, tuple(words.split()))
    for category, words in (
        (
            "餐饮",
            "餐饮 早饭 早餐 早点 午饭 午餐 中饭 晚饭 晚餐 夜宵 宵夜 吃饭 饭 餐 外卖 "
            "咖啡 奶茶 饮料 零食 水果 小吃 火锅 烧烤 甜品 蛋糕 面包 下午茶 聚餐 食堂 "
            "买菜 菜 喝酒 啤酒 茶 包子 面条 麦当劳 肯德基 星巴克 瑞幸",
        ),
        (
            "交通",
            "交通 打车 出租 滴滴 网约车 地铁 公交 巴士 高铁 火车 动车 机票 飞机 航班 "
            "加油 油费 停车 过路费 高速 单车 车费 车票 路费 船票 充电桩 通勤",
        ),
        (
            "住房",
            "住房 房租 租金 租房 房贷 物业 水费 电费 水电 燃气 煤气 暖气 宽带 话费 "
            "酒店 住宿 民宿",
        ),
        (
            "订阅",
            "订阅 会员 续费 月费 年费 网盘 icloud netflix spotify youtube chatgpt "
            "claude",
        ),
        (
            "医疗",
            "医疗 医院 看病 挂号 门诊 住院 体检 药 诊所 牙医 看牙 补牙 洗牙 疫苗",
        ),
        (
            "娱乐",
            "娱乐 电影 游戏 ktv 唱歌 演唱会 门票 旅游 景点 健身 运动 桌游 剧本杀 密室 "
            "酒吧 按摩 展览 话剧 演出",
        ),
        (
            "购物",
            "购物 买 淘宝 京东 拼多多 超市 商场 便利店 衣服 鞋 裤 化妆品 护肤 日用品 "
            "网购 数码 手机 电脑 耳机 家电 文具 书",
        ),
    )
)
INCOME_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("工资", ("工资", "薪水", "薪资", "月薪", "发薪")),
)
ACCOUNT_KEYWORDS = ("微信", "支付宝", "现金", "信用卡", "银行卡")

# 出现即算收入；“收到”“赚”这类弱信号遇到“花/付/买”等支出动词时让位给支出。
_INCOME_STRONG = re.compile(
    r"工资|薪水|薪资|月薪|发薪|收入|进账|到账|入账|奖金|年终奖|报销|退款|退钱|"
    r"红包收入|收红包|利息|分红|稿费"
)
_INCOME_WEAK = re.compile(r"收到|赚|卖了|卖掉")
_EXPENSE_VERB = re.compile(
    r"花(?!呗)|(?<!支)付(?!宝)|支付(?!宝)|买|消费|支出|缴|交了|充值|充了"
)

# 单独写在句子里、不紧挨数字的币种词；“刀”“欧”太容易误伤，只在金额后面才算。
_SENTENCE_CURRENCIES = (
    ("美元", "USD"),
    ("美金", "USD"),
    ("欧元", "EUR"),
    ("港币", "HKD"),
    ("港元", "HKD"),
    ("日元", "JPY"),
    ("日币", "JPY"),
    ("英镑", "GBP"),
)

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1_000}
_CN_DIGIT_CHARS = "".join(_CN_DIGITS)
_CN_NUMBER_CHARS = _CN_DIGIT_CHARS + "十百千万亿"

# 全角字母、数字和符号转半角；全角逗号保留，免得“10，20”被当成千分位。
_HALF_WIDTH = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F) if code != 0xFF0C}
_HALF_WIDTH.update({0x3000: 0x20, 0xFFE5: ord("¥"), 0xFFE1: ord("£")})

_ARABIC = re.compile(r"(?:\d{1,3}(?:,\d{3})+(?!\d)|\d+)(?:\.\d+)?")
_CHINESE = re.compile(f"[{_CN_NUMBER_CHARS}]+")
_ARABIC_MULTIPLIER = re.compile(r"(?:[亿万千百]|[kKwW](?![A-Za-z]))")
_ARABIC_MULTIPLIERS = {
    "亿": 100_000_000,
    "万": 10_000,
    "w": 10_000,
    "千": 1_000,
    "k": 1_000,
    "百": 100,
}
_CURRENCY_SUFFIX = re.compile(
    r"\s*(?P<unit>块钱|块|元钱|元|圆|毛钱|毛|角钱|角|美元|美金|刀|欧元|欧|港币|港元|"
    r"日元|日币|円|英镑|镑|人民币|(?:rmb|cny|usd|eur|hkd|jpy|gbp)(?![A-Za-z]))",
    re.IGNORECASE,
)
_CURRENCY_PREFIX = re.compile(
    r"(?:(?<![A-Za-z])(?P<code>HK\$|US\$|rmb|cny|usd|eur|hkd|jpy|gbp)|(?P<symbol>[¥$€£]))\s*$",
    re.IGNORECASE,
)
_UNIT_CURRENCIES = {
    "块钱": "CNY",
    "块": "CNY",
    "元钱": "CNY",
    "元": "CNY",
    "圆": "CNY",
    "毛钱": "CNY",
    "毛": "CNY",
    "角钱": "CNY",
    "角": "CNY",
    "人民币": "CNY",
    "rmb": "CNY",
    "cny": "CNY",
    "美元": "USD",
    "美金": "USD",
    "刀": "USD",
    "usd": "USD",
    "欧元": "EUR",
    "欧": "EUR",
    "eur": "EUR",
    "港币": "HKD",
    "港元": "HKD",
    "hkd": "HKD",
    "日元": "JPY",
    "日币": "JPY",
    "円": "JPY",
    "jpy": "JPY",
    "英镑": "GBP",
    "镑": "GBP",
    "gbp": "GBP",
}
_PREFIX_CURRENCIES = {
    "hk$": "HKD",
    "us$": "USD",
    "rmb": "CNY",
    "cny": "CNY",
    "usd": "USD",
    "eur": "EUR",
    "hkd": "HKD",
    "jpy": "JPY",
    "gbp": "GBP",
    "¥": "CNY",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}
_JIAO_UNITS = {"毛钱", "毛", "角钱", "角"}
# “三块五”“10块5毛”“3元5角”：块/元后面紧跟一位数字当作几毛。
_JIAO_AFTER_YUAN = re.compile(
    rf"(?P<digit>[0-9{_CN_DIGIT_CHARS}])(?![0-9.{_CN_NUMBER_CHARS}])(?P<unit>[毛角]钱?)?"
)
# “10块”后面接这些才算钱；“一块去”“两块蛋糕”里的“块”不当成元。
_YUAN_FOLLOW = re.compile(r"$|[\s,，。.!！?？;；:：、)）\]】|]|的|多|左右|整")
# 数字后面接量词时是数量、时间或序号，不是金额。
_MEASURE = re.compile(
    r"\s*(?:个|杯|份|次|斤|两|件|张|瓶|盒|袋|包|碗|位|人|天|晚|夜|本|支|只|条|双|台|部|辆|"
    r"公里|千米|米|km|kg|g|小时|分钟|分|秒|周|星期|月|年|号|日|点|岁|楼|层|站|路|集|期|"
    r"节|顿|桌|箱|罐|根|片|颗|粒|折|%|克|升|度|间|套|趟|局|场|单|笔|口|把|副|枚|盘|串|"
    r"步|样|种|些|下|起|会|直|半|共)",
    re.IGNORECASE,
)
# 不带单位的中文数字只在这些词后面才当成金额，避免把“一起”“十一”当成钱。
_MONEY_VERB = re.compile(
    r"(?:花了|花费|花|付了|付款|支付|付|消费|一共|总共|共|合计|收入|收到|赚了|进账|到账|"
    r"工资|奖金|报销|退款|用了|充了|充值|交了|缴了)\s*$"
)

_RELATIVE_DATE = re.compile(r"大前天|前天|昨天|昨日|昨儿|今天|今日|今儿")
_RELATIVE_OFFSETS = {
    "大前天": -3,
    "前天": -2,
    "昨天": -1,
    "昨日": -1,
    "昨儿": -1,
    "今天": 0,
    "今日": 0,
    "今儿": 0,
}
_DAY_NUMBER = r"\d{1,2}|[一二三四五六七八九十]{1,3}"
_FULL_DATE = re.compile(
    rf"(?<!\d)(?P<year>\d{{4}})\s*(?:年\s*(?P<month>{_DAY_NUMBER})\s*月\s*"
    rf"(?P<day>{_DAY_NUMBER})\s*[日号]?|(?P<sep>[-/.])(?P<month2>\d{{1,2}})(?P=sep)"
    rf"(?P<day2>\d{{1,2}})(?!\d))"
)
_MONTH_DAY = re.compile(
    rf"(?<!\d)(?P<month>{_DAY_NUMBER})\s*月\s*(?P<day>{_DAY_NUMBER})\s*[日号]"
)
_CLOCK_TIME = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)")
# 识别金额前把日期、时间换成占位符，免得“3月5号”里的数字被当成钱。
_MASK = "|"


class LedgerParseError(ValueError):
    """这句话识别不出一笔完整的收支；消息是给用户看的中文提示。"""


@dataclass(frozen=True)
class _Amount:
    value: Decimal
    currency: str | None
    strong: bool


def normalize_sentence(text: str) -> str:
    """全角字母、数字和符号转半角，后面的识别都基于这个结果。"""

    return text.translate(_HALF_WIDTH)


def _chinese_to_int(text: str) -> int | None:
    """中文数字转整数，支持“两”“一百零五”和口语“一百二”“三千五”“一万二”。"""

    result = wan = section = 0
    digit: int | None = None
    previous_unit = 0
    after_zero = False
    for char in text:
        if char in _CN_DIGITS:
            if digit not in (None, 0):
                return None  # “一二”这类连写不是一个数
            digit = _CN_DIGITS[char]
            after_zero = after_zero or digit == 0
            continue
        if char == "亿":
            value = wan + section + (digit or 0)
            if value == 0:
                return None
            result += value * 100_000_000
            wan = section = 0
            digit, previous_unit, after_zero = None, 100_000_000, False
            continue
        if char == "万":
            value = section + (digit or 0)
            if value == 0:
                return None
            wan += value * 10_000
            section = 0
            digit, previous_unit, after_zero = None, 10_000, False
            continue
        unit = _CN_SMALL_UNITS[char]
        if digit is None:
            # 只有“十”可以省略前面的“一”，且只能出现在开头，如“十五”。
            if unit != 10 or section:
                return None
            digit = 1
        if previous_unit and previous_unit < 10_000 and unit >= previous_unit:
            return None  # 单位必须从大到小，如“十百”不是数
        section += digit * unit
        digit, previous_unit, after_zero = None, unit, False
    if digit:
        # 末尾单独一个数字：“一百二”是 120，“一百零二”是 102。
        multiplier = 1 if after_zero or previous_unit < 100 else previous_unit // 10
        section += digit * multiplier
    return result + wan + section


def _digit_value(char: str) -> int:
    return int(char) if char.isascii() else _CN_DIGITS[char]


def find_dates(text: str, today: date) -> tuple[date | None, list[tuple[int, int]]]:
    """找出句中的日期，返回第一个日期和所有日期所在位置。

    ``text`` 需先经过 ``normalize_sentence``；日期不存在时抛 ``LedgerParseError``。
    """

    found: list[tuple[int, int, date]] = []
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(
            start < used_end and used_start < end for used_start, used_end in taken
        )

    def number(value: str) -> int:
        parsed = int(value) if value.isdigit() else _chinese_to_int(value)
        return parsed if parsed is not None else 0

    def build(year: int, month: int, day: int, label: str) -> date:
        try:
            return date(year, month, day)
        except ValueError as error:
            raise LedgerParseError(f"日期“{label}”不存在，请检查后重试") from error

    for match in _FULL_DATE.finditer(text):
        month = match.group("month") or match.group("month2")
        day = match.group("day") or match.group("day2")
        resolved = build(
            int(match.group("year")), number(month), number(day), match.group().strip()
        )
        found.append((match.start(), match.end(), resolved))
        taken.append(match.span())
    for match in _MONTH_DAY.finditer(text):
        if overlaps(*match.span()):
            continue
        month, day = number(match.group("month")), number(match.group("day"))
        label = match.group().strip()
        # 没写年份：默认今年；算出来晚于今天就是去年。
        try:
            resolved = date(today.year, month, day)
        except ValueError:
            resolved = None
        if resolved is None or resolved > today:
            resolved = build(today.year - 1, month, day, label)
        found.append((match.start(), match.end(), resolved))
        taken.append(match.span())
    for match in _RELATIVE_DATE.finditer(text):
        if overlaps(*match.span()):
            continue
        offset = _RELATIVE_OFFSETS[match.group()]
        found.append((match.start(), match.end(), today + timedelta(days=offset)))
        taken.append(match.span())
    for match in _CLOCK_TIME.finditer(text):
        if not overlaps(*match.span()):
            taken.append(match.span())
    found.sort(key=lambda item: item[0])
    return (found[0][2] if found else None), taken


def _mask(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = _MASK * (end - start)
    return "".join(chars)


def _find_amounts(text: str) -> list[_Amount]:
    """逐个数字看前后文：带币种或单位的是“明确金额”，光秃秃的数字是“可能金额”。"""

    amounts: list[_Amount] = []
    position = 0
    while position < len(text):
        arabic = _ARABIC.match(text, position)
        chinese = None if arabic else _CHINESE.match(text, position)
        match = arabic or chinese
        if match is None:
            position += 1
            continue
        start, end = match.span()
        if arabic:
            value = Decimal(match.group().replace(",", ""))
            multiplier = _ARABIC_MULTIPLIER.match(text, end)
            if multiplier:
                value *= _ARABIC_MULTIPLIERS[multiplier.group().lower()]
                end = multiplier.end()
        else:
            parsed = _chinese_to_int(match.group())
            if parsed is None:
                position = end
                continue
            value = Decimal(parsed)

        prefix = _CURRENCY_PREFIX.search(text, 0, start)
        currency = None
        if prefix:
            key = (prefix.group("code") or prefix.group("symbol")).lower()
            currency = _PREFIX_CURRENCIES[key]
        suffix = _CURRENCY_SUFFIX.match(text, end)
        strong = prefix is not None
        if suffix:
            unit = suffix.group("unit").lower()
            end = suffix.end()
            if unit in _JIAO_UNITS:
                value /= 10
                strong = True
            elif unit in {"块", "元", "圆"}:
                jiao = _JIAO_AFTER_YUAN.match(text, end)
                if jiao and (
                    jiao.group("unit")
                    or (unit == "块" and not _MEASURE.match(text, jiao.end()))
                ):
                    value += Decimal(_digit_value(jiao.group("digit"))) / 10
                    end = jiao.end()
                    strong = True
                elif unit != "块" or _YUAN_FOLLOW.match(text, end):
                    strong = True
                # 否则是“10块买了个包”“一块去”“两块蛋糕”：块后面接别的字，
                # 只当作不带单位的数字，交给下面的规则判断。
            else:
                strong = True
            if strong:
                currency = currency or _UNIT_CURRENCIES[unit]

        if not strong and not _is_bare_amount(text, start, end, bool(chinese)):
            position = end
            continue
        amounts.append(_Amount(value=value, currency=currency, strong=strong))
        position = end
    return amounts


def _is_bare_amount(text: str, start: int, end: int, chinese: bool) -> bool:
    """不带单位的数字：后面接量词、挨着英文字母或写着“第”时不算金额。"""

    if _MEASURE.match(text, end):
        return False
    before = text[:start].rstrip()
    after = text[end : end + 1]
    if chinese:
        # 中文数字只在“花了”“收入”等词后面才算，避免“一起”“十一”被当成钱。
        return _MONEY_VERB.search(before) is not None
    if before.endswith(("第", "#")) or (
        before[-1:].isascii() and before[-1:].isalpha()
    ):
        return False
    return not (after.isascii() and after.isalpha())


def _to_cents(amount: _Amount) -> int:
    cents = amount.value * 100
    if cents != cents.to_integral_value():
        raise LedgerParseError("金额最多两位小数")
    cents_int = int(cents)
    if cents_int <= 0:
        raise LedgerParseError("金额需要大于 0")
    if cents_int > LEDGER_MAX_AMOUNT_CENTS:
        raise LedgerParseError("单笔金额不能超过 10 亿")
    return cents_int


def _detect_kind(text: str) -> LedgerKind:
    if _INCOME_STRONG.search(text):
        return "income"
    if _INCOME_WEAK.search(text) and not _EXPENSE_VERB.search(text):
        return "income"
    return "expense"


def _detect_currency(text: str, amount: _Amount) -> str:
    if amount.currency:
        return amount.currency
    positions = [
        (index, code)
        for word, code in _SENTENCE_CURRENCIES
        if (index := text.find(word)) >= 0
    ]
    return min(positions)[1] if positions else LEDGER_DEFAULT_CURRENCY


def detect_category(
    text: str, kind: LedgerKind, known_categories: Iterable[tuple[str, str]]
) -> str:
    """按用过的分类和关键词表选分类，都没有命中时归到“其他”。"""

    folded = text.casefold()
    # 用户自己用过的分类直接写在句子里时优先，长的先匹配。
    custom = sorted(
        {
            category
            for category_kind, category in known_categories
            if category_kind == kind
        },
        key=lambda value: (-len(value), value),
    )
    for category in custom:
        if category.casefold() in folded:
            return category
    table = INCOME_CATEGORY_KEYWORDS if kind == "income" else EXPENSE_CATEGORY_KEYWORDS
    best: tuple[int, int, str] | None = None
    for order, (category, keywords) in enumerate(table):
        for keyword in keywords:
            if keyword in folded:
                candidate = (-len(keyword), order, category)
                if best is None or candidate < best:
                    best = candidate
    return best[2] if best else FALLBACK_CATEGORY


def detect_account(text: str) -> str | None:
    """句中最先出现的常见账户名，如微信、支付宝。"""

    positions = [
        (index, account)
        for account in ACCOUNT_KEYWORDS
        if (index := text.find(account)) >= 0
    ]
    return min(positions)[1] if positions else None


def parse_ledger_sentence(
    text: str,
    today: date,
    known_categories: Iterable[tuple[str, str]] = (),
) -> LedgerEntryCreate:
    """把一句话解析成一笔收支。

    ``today`` 由客户端按本地时区给出；``known_categories`` 是该账号用过的
    ``(kind, category)``，句中直接写到时优先用作分类。
    """

    note = text.strip()
    if not note:
        raise LedgerParseError("请输入一句话，如：今天早饭花了10元")
    if len(note) > LEDGER_NOTE_MAX_LENGTH:
        raise LedgerParseError(f"一句话最多 {LEDGER_NOTE_MAX_LENGTH} 个字")
    normalized = normalize_sentence(note)

    occurred_on, date_spans = find_dates(normalized, today)
    occurred_on = occurred_on or today
    if not LEDGER_MIN_DATE <= occurred_on <= LEDGER_MAX_DATE:
        raise LedgerParseError("日期超出可记录范围")

    amounts = _find_amounts(_mask(normalized, date_spans))
    strong = [amount for amount in amounts if amount.strong]
    candidates = strong or amounts
    if not candidates:
        raise LedgerParseError("没有识别到金额，请写明多少钱，如：今天早饭花了10元")
    if len(candidates) > 1:
        raise LedgerParseError("一句话只能记一笔，请把每一笔分开输入")
    amount = candidates[0]
    cents = _to_cents(amount)

    kind = _detect_kind(normalized)
    try:
        return LedgerEntryCreate(
            kind=kind,
            amount_cents=cents,
            currency=_detect_currency(normalized, amount),
            occurred_on=occurred_on,
            category=detect_category(normalized, kind, known_categories),
            account=detect_account(normalized),
            note=note,
        )
    except ValidationError as error:  # 理论上不会发生，兜底成中文提示
        raise LedgerParseError("这句话没能记成一笔，请换个说法或手动记一笔") from error


__all__ = [
    "EXPENSE_CATEGORY_KEYWORDS",
    "FALLBACK_CATEGORY",
    "INCOME_CATEGORY_KEYWORDS",
    "LedgerParseError",
    "detect_account",
    "detect_category",
    "find_dates",
    "normalize_sentence",
    "parse_ledger_sentence",
]
