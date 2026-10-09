"""英语单词词典补全与词形归并服务。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Database
from app.models import Memo, MemoStatus, MemoType

IRREGULAR_LEMMAS = {
    "am": "be",
    "are": "be",
    "being": "be",
    "been": "be",
    "broke": "break",
    "broken": "break",
    "became": "become",
    "began": "begin",
    "begun": "begin",
    "blew": "blow",
    "blown": "blow",
    "came": "come",
    "chose": "choose",
    "chosen": "choose",
    "cut": "cut",
    "dealt": "deal",
    "did": "do",
    "does": "do",
    "done": "do",
    "drew": "draw",
    "drawn": "draw",
    "driven": "drive",
    "drove": "drive",
    "dying": "die",
    "drunk": "drink",
    "fought": "fight",
    "forgave": "forgive",
    "forgiven": "forgive",
    "got": "get",
    "gotten": "get",
    "hid": "hide",
    "hidden": "hide",
    "hit": "hit",
    "hurt": "hurt",
    "is": "be",
    "lying": "lie",
    "laid": "lay",
    "led": "lead",
    "lent": "lend",
    "let": "let",
    "lit": "light",
    "meant": "mean",
    "mistook": "mistake",
    "mistaken": "mistake",
    "put": "put",
    "quit": "quit",
    "saw": "see",
    "shook": "shake",
    "shaken": "shake",
    "showed": "show",
    "shown": "show",
    "shut": "shut",
    "slid": "slide",
    "spun": "spin",
    "stole": "steal",
    "stolen": "steal",
    "struck": "strike",
    "swam": "swim",
    "swum": "swim",
    "swept": "sweep",
    "swung": "swing",
    "tore": "tear",
    "torn": "tear",
    "tied": "tie",
    "tying": "tie",
    "woke": "wake",
    "woken": "wake",
    "withdrew": "withdraw",
    "withdrawn": "withdraw",
    "withstood": "withstand",
    "worse": "bad",
    "worst": "bad",
    "was": "be",
    "were": "be",
    "has": "have",
    "had": "have",
    "he": "he",
    "she": "she",
    "it": "it",
    "men": "man",
    "women": "woman",
    "mice": "mouse",
    "geese": "goose",
    "teeth": "tooth",
    "feet": "foot",
    "people": "person",
    "children": "child",
    "leaves": "leave",
    "wolves": "wolf",
    "knives": "knife",
    "wives": "wife",
    "lives": "live",
    "shelves": "shelf",
    "selves": "self",
    "halves": "half",
    "calves": "calf",
    "loaves": "loaf",
    "thieves": "thief",
    "elves": "elf",
    "movies": "movie",
    "cookies": "cookie",
    "brownies": "brownie",
    "smoothies": "smoothie",
    "selfies": "selfie",
    "zombies": "zombie",
    "pies": "pie",
    "ties": "tie",
    "lies": "lie",
    "dies": "die",
    "news": "news",
    "always": "always",
    "means": "means",
    "mathematics": "mathematics",
    "physics": "physics",
    "politics": "politics",
    "economics": "economics",
    "ethics": "ethics",
    "species": "species",
    "series": "series",
    "shoes": "shoe",
    "toes": "toe",
    "canoes": "canoe",
    "buses": "bus",
    "gases": "gas",
    "analyses": "analysis",
    "crises": "crisis",
    "heroes": "hero",
    "potatoes": "potato",
    "tomatoes": "tomato",
    "echoes": "echo",
    "goes": "go",
    "ran": "run",
    "better": "good",
    "best": "good",
    "brought": "bring",
    "built": "build",
    "bought": "buy",
    "caught": "catch",
    "drank": "drink",
    "ate": "eat",
    "eaten": "eat",
    "fell": "fall",
    "fallen": "fall",
    "felt": "feel",
    "found": "find",
    "flew": "fly",
    "flown": "fly",
    "forgot": "forget",
    "forgotten": "forget",
    "gave": "give",
    "given": "give",
    "went": "go",
    "gone": "go",
    "grew": "grow",
    "grown": "grow",
    "heard": "hear",
    "held": "hold",
    "kept": "keep",
    "knew": "know",
    "known": "know",
    "left": "leave",
    "lost": "lose",
    "made": "make",
    "met": "meet",
    "paid": "pay",
    "read": "read",
    "rode": "ride",
    "ridden": "ride",
    "rose": "rise",
    "risen": "rise",
    "said": "say",
    "seen": "see",
    "sold": "sell",
    "sent": "send",
    "sang": "sing",
    "sung": "sing",
    "sat": "sit",
    "slept": "sleep",
    "spoke": "speak",
    "spoken": "speak",
    "spent": "spend",
    "stood": "stand",
    "took": "take",
    "taken": "take",
    "taught": "teach",
    "told": "tell",
    "thought": "think",
    "threw": "throw",
    "thrown": "throw",
    "understood": "understand",
    "wore": "wear",
    "worn": "wear",
    "won": "win",
    "wrote": "write",
    "written": "write",
}

ING_E_STEMS = {
    "achiev": "achieve",
    "believ": "believe",
    "choos": "choose",
    "clos": "close",
    "com": "come",
    "danc": "dance",
    "decid": "decide",
    "driv": "drive",
    "forc": "force",
    "giv": "give",
    "hav": "have",
    "lik": "like",
    "liv": "live",
    "lov": "love",
    "mak": "make",
    "mov": "move",
    "notic": "notice",
    "practic": "practice",
    "produc": "produce",
    "reduc": "reduce",
    "receiv": "receive",
    "rid": "ride",
    "ris": "rise",
    "sav": "save",
    "tak": "take",
    "us": "use",
    "writ": "write",
}
ED_E_STEMS = {
    "achiev": "achieve",
    "believ": "believe",
    "choos": "choose",
    "clos": "close",
    "com": "come",
    "creat": "create",
    "danc": "dance",
    "decid": "decide",
    "driv": "drive",
    "forc": "force",
    "giv": "give",
    "hav": "have",
    "lik": "like",
    "liv": "live",
    "lov": "love",
    "mak": "make",
    "mov": "move",
    "notic": "notice",
    "practic": "practice",
    "produc": "produce",
    "reduc": "reduce",
    "receiv": "receive",
    "rid": "ride",
    "ris": "rise",
    "sav": "save",
    "tak": "take",
    "us": "use",
    "writ": "write",
}
COMPARATIVE_E_STEMS = {
    "larg": "large",
    "lat": "late",
    "nic": "nice",
    "saf": "safe",
    "simpl": "simple",
    "wid": "wide",
}
COMMON_ADJECTIVE_LEMMAS = {
    "bad",
    "big",
    "bright",
    "busy",
    "cheap",
    "clean",
    "clear",
    "cold",
    "dark",
    "deep",
    "early",
    "easy",
    "fast",
    "far",
    "good",
    "happy",
    "hard",
    "heavy",
    "high",
    "hot",
    "kind",
    "large",
    "late",
    "light",
    "little",
    "long",
    "loud",
    "low",
    "narrow",
    "new",
    "nice",
    "old",
    "poor",
    "quick",
    "quiet",
    "rich",
    "safe",
    "short",
    "simple",
    "slow",
    "small",
    "soft",
    "strong",
    "warm",
    "weak",
    "wide",
    "young",
}


class WordDictionaryUnavailableError(RuntimeError):
    """词典服务不可用或没有收录当前单词。"""


DICTIONARY_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "MemoIsle/0.1 (personal dictionary lookup)",
}
YOUDAO_VOICE_URL = "https://dict.youdao.com/dictvoice"
POS_LABELS = {
    "n": "名词",
    "v": "动词",
    "vt": "动词",
    "vi": "动词",
    "adj": "形容词",
    "adv": "副词",
    "prep": "介词",
    "conj": "连词",
    "pron": "代词",
    "int": "感叹词",
    "num": "数词",
    "art": "冠词",
    "aux": "助动词",
    "pl": "复数",
    "abbr": "缩写",
    "det": "限定词",
    "modal": "情态动词",
}
POS_PREFIX_RE = re.compile(
    r"^(?P<pos>vt|vi|adj|adv|prep|conj|pron|int|num|art|aux|abbr|det|modal|pl|n|v)\.\s*",
    re.IGNORECASE,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class WordDictionarySense:
    """词典返回的单个词性、释义和例句。"""

    part_of_speech: str | None
    definition: str
    example: str | None


@dataclass(frozen=True, slots=True)
class WordDictionaryEntry:
    """词典服务返回的单词补全数据。"""

    phonetic: str | None
    us_audio_url: str | None
    uk_audio_url: str | None
    meaning: str | None
    example: str | None
    # 保留旧构造方式兼容已有 Provider 和测试，查词预览使用该结构化列表。
    senses: tuple[WordDictionarySense, ...] = field(
        compare=False,
        default_factory=tuple,
    )
    source_name: str | None = field(compare=False, default=None)
    source_url: str | None = field(compare=False, default=None)


def normalize_word_lemma(value: str) -> str:
    """把英文词形归并为可比较的词元，覆盖常见屈折变化。"""

    folded = unicodedata.normalize("NFKC", value).casefold().strip()
    token = " ".join(folded.split())
    if not token or " " in token:
        return re.sub(r"[^a-z0-9' -]", "", token).strip()
    token = re.sub(r"[^a-z0-9' -]", "", token)
    if not token:
        return ""
    if token in IRREGULAR_LEMMAS:
        return IRREGULAR_LEMMAS[token]
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("ves") and len(token) > 4:
        # 未列入特殊词表时优先保留 -ve，避免 loves 被误判为 lof。
        return token[:-1]
    if token.endswith(("ches", "shes", "sses", "xes", "zes")) and len(token) > 4:
        return token[:-2]
    if token.endswith("oes") and len(token) > 4:
        return token[:-2]
    if token.endswith("ses") and len(token) > 4:
        return token[:-1]
    if (
        token.endswith("s")
        and not token.endswith(("ss", "us", "is"))
        and len(token) > 3
    ):
        return token[:-1]
    if token.endswith("ying") and len(token) > 5:
        # studying、playing 等词去掉 -ing 后本身已经是词元。
        return token[:-3]
    if token.endswith("ing") and len(token) > 5:
        stem = token[:-3]
        if stem in ING_E_STEMS:
            return ING_E_STEMS[stem]
        if stem.endswith("e"):
            return stem
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "lsz":
            return stem[:-1]
        return stem
    if token.endswith("ied") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        if stem in ED_E_STEMS:
            return ED_E_STEMS[stem]
        if stem.endswith("e"):
            return stem
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "lsz":
            return stem[:-1]
        return stem
    if token.endswith("iest") and len(token) > 5:
        candidate = f"{token[:-4]}y"
        if candidate in COMMON_ADJECTIVE_LEMMAS:
            return candidate
    if token.endswith("ier") and len(token) > 4:
        candidate = f"{token[:-3]}y"
        if candidate in COMMON_ADJECTIVE_LEMMAS:
            return candidate
    if token.endswith("est") and len(token) > 5:
        candidate = token[:-3]
        if candidate.endswith(candidate[-1:] * 2):
            candidate = candidate[:-1]
        if candidate in COMMON_ADJECTIVE_LEMMAS:
            return candidate
        if candidate in COMPARATIVE_E_STEMS:
            return COMPARATIVE_E_STEMS[candidate]
    if token.endswith("er") and len(token) > 4:
        candidate = token[:-2]
        if candidate.endswith(candidate[-1:] * 2):
            candidate = candidate[:-1]
        if candidate in COMMON_ADJECTIVE_LEMMAS:
            return candidate
        if candidate in COMPARATIVE_E_STEMS:
            return COMPARATIVE_E_STEMS[candidate]
    return token


def _audio_url(url: Any) -> str | None:
    """仅返回合法 HTTP(S) 音频地址。"""

    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    return url[:2048]


def _wrap_phonetic(value: str | None) -> str | None:
    """把音标规范成 /.../ 形式。"""

    if not value or not value.strip():
        return None
    text = value.strip()
    if not text.startswith("/"):
        text = f"/{text.strip('/')}/"
    return text[:120]


def _strip_html(value: str) -> str:
    """去掉词典例句中的简单 HTML 标记。"""

    return HTML_TAG_RE.sub("", value).replace("&nbsp;", " ").strip()


def _flatten_youdao_text(value: Any) -> str:
    """把有道嵌套文本节点收成一行。"""

    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(_flatten_youdao_text(item) for item in value).strip()
    if isinstance(value, dict):
        if isinstance(value.get("#text"), str):
            return value["#text"].strip()
        if "i" in value:
            return _flatten_youdao_text(value["i"])
        if isinstance(value.get("l"), dict):
            return _flatten_youdao_text(value["l"])
    return ""


def _pos_label(raw_pos: str | None) -> str | None:
    """把词典词性缩写转成中文标签。"""

    if not raw_pos:
        return None
    return POS_LABELS.get(raw_pos.casefold().strip("."), raw_pos.strip())


def _split_pos_and_glosses(text: str) -> tuple[str | None, list[str]]:
    """从“n. 苹果；苹果树”中拆出词性和中文义项。"""

    cleaned = text.strip()
    if not cleaned or "人名" in cleaned or cleaned.startswith("【"):
        return None, []
    match = POS_PREFIX_RE.match(cleaned)
    pos = match.group("pos").lower() if match else None
    rest = cleaned[match.end() :] if match else cleaned
    parts = [
        part.strip(" ，,")
        for part in re.split(r"[；;]", rest)
        if part.strip(" ，,")
    ]
    return pos, parts


def _youdao_voice_url(word: str, voice_type: int) -> str:
    """构造有道在线发音地址。"""

    return f"{YOUDAO_VOICE_URL}?audio={quote(word)}&type={voice_type}"


def _parse_youdao_jsonapi_payload(
    payload: Any,
    word: str,
) -> WordDictionaryEntry:
    """解析有道 jsonapi 的英中释义、音标和双语例句。"""

    if not isinstance(payload, dict):
        raise WordDictionaryUnavailableError("中英词典返回格式无效")
    ec_words = payload.get("ec", {}).get("word") if isinstance(
        payload.get("ec"),
        dict,
    ) else None
    senses: list[WordDictionarySense] = []
    definitions: list[str] = []
    phonetic: str | None = None
    if isinstance(ec_words, list):
        for entry in ec_words:
            if not isinstance(entry, dict):
                continue
            if phonetic is None:
                phonetic = _wrap_phonetic(
                    next(
                        (
                            item
                            for item in (entry.get("usphone"), entry.get("ukphone"))
                            if isinstance(item, str) and item.strip()
                        ),
                        None,
                    ),
                )
            trs = entry.get("trs")
            if not isinstance(trs, list):
                continue
            for item in trs:
                if not isinstance(item, dict):
                    continue
                translations = item.get("tr")
                if not isinstance(translations, list):
                    continue
                for translation in translations:
                    text = _flatten_youdao_text(translation)
                    pos, glosses = _split_pos_and_glosses(text)
                    for gloss in glosses:
                        label = _pos_label(pos)
                        definitions.append(
                            f"{label}: {gloss}" if label else gloss,
                        )
                        senses.append(
                            WordDictionarySense(
                                part_of_speech=label,
                                definition=gloss[:5000],
                                example=None,
                            ),
                        )
                        if len(senses) >= 8:
                            break
                    if len(senses) >= 8:
                        break
                if len(senses) >= 8:
                    break
            if len(senses) >= 8:
                break
    if not senses:
        raise WordDictionaryUnavailableError("中英词典没有返回释义")

    example: str | None = None
    sentence_pairs = (
        payload.get("blng_sents_part", {}).get("sentence-pair")
        if isinstance(payload.get("blng_sents_part"), dict)
        else None
    )
    if isinstance(sentence_pairs, list) and sentence_pairs:
        pair = sentence_pairs[0]
        if isinstance(pair, dict):
            english = _strip_html(
                next(
                    (
                        item
                        for item in (
                            pair.get("sentence-eng"),
                            pair.get("sentence"),
                        )
                        if isinstance(item, str) and item.strip()
                    ),
                    "",
                ),
            )
            chinese = _strip_html(
                pair["sentence-translation"]
                if isinstance(pair.get("sentence-translation"), str)
                else "",
            )
            if english and chinese:
                example = f"{english} / {chinese}"
            elif english or chinese:
                example = english or chinese
    if example is None:
        collins = payload.get("collins")
        entries = collins.get("collins_entries") if isinstance(collins, dict) else None
        first_entry = entries[0] if isinstance(entries, list) and entries else None
        nested = (
            first_entry.get("entries") if isinstance(first_entry, dict) else None
        )
        sent_items = nested.get("entry") if isinstance(nested, dict) else None
        first_sent = (
            sent_items[0] if isinstance(sent_items, list) and sent_items else None
        )
        tran_entry = (
            first_sent.get("tran_entry") if isinstance(first_sent, dict) else None
        )
        first_tran = (
            tran_entry[0] if isinstance(tran_entry, list) and tran_entry else None
        )
        exam_sents = (
            first_tran.get("exam_sents") if isinstance(first_tran, dict) else None
        )
        exam = exam_sents.get("sent") if isinstance(exam_sents, dict) else None
        first_exam = exam[0] if isinstance(exam, list) and exam else None
        if isinstance(first_exam, dict):
            english = first_exam.get("eng_sent")
            chinese = first_exam.get("chn_sent")
            if isinstance(english, str) and isinstance(chinese, str):
                example = f"{english.strip()} / {chinese.strip()}"

    if example and senses and senses[0].example is None:
        first = senses[0]
        senses[0] = WordDictionarySense(
            part_of_speech=first.part_of_speech,
            definition=first.definition,
            example=example[:5000],
        )

    return WordDictionaryEntry(
        phonetic=phonetic,
        us_audio_url=_youdao_voice_url(word, 2),
        uk_audio_url=_youdao_voice_url(word, 1),
        meaning="\n".join(definitions)[:5000] or None,
        example=example[:5000] if example else None,
        senses=tuple(senses),
        source_name="有道词典",
        source_url="https://dict.youdao.com",
    )


def _parse_youdao_suggest_payload(
    payload: Any,
    word: str,
) -> WordDictionaryEntry:
    """解析有道联想接口中的精确中文释义。"""

    if not isinstance(payload, dict):
        raise WordDictionaryUnavailableError("中英词典返回格式无效")
    data = payload.get("data")
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise WordDictionaryUnavailableError("中英词典没有返回释义")
    lemma = word.casefold()
    senses: list[WordDictionarySense] = []
    definitions: list[str] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        entry = item.get("entry")
        explain = item.get("explain")
        if not isinstance(entry, str) or not isinstance(explain, str):
            continue
        if entry.casefold() != lemma:
            continue
        pos, glosses = _split_pos_and_glosses(explain)
        for gloss in glosses:
            label = _pos_label(pos)
            definitions.append(f"{label}: {gloss}" if label else gloss)
            senses.append(
                WordDictionarySense(
                    part_of_speech=label,
                    definition=gloss[:5000],
                    example=None,
                ),
            )
            if len(senses) >= 8:
                break
        if entry.casefold() == lemma or len(senses) >= 8:
            break
    if not senses:
        raise WordDictionaryUnavailableError("中英词典没有返回释义")
    return WordDictionaryEntry(
        phonetic=None,
        us_audio_url=_youdao_voice_url(word, 2),
        uk_audio_url=_youdao_voice_url(word, 1),
        meaning="\n".join(definitions)[:5000] or None,
        example=None,
        senses=tuple(senses),
        source_name="有道词典",
        source_url="https://dict.youdao.com",
    )


def _merge_dictionary_entries(
    bilingual: WordDictionaryEntry | None,
    english: WordDictionaryEntry | None,
) -> WordDictionaryEntry:
    """中文释义优先，英文词典补音标、音频和例句。"""

    if bilingual is None and english is None:
        raise WordDictionaryUnavailableError("词典没有收录当前单词")
    if bilingual is None:
        return english  # type: ignore[return-value]
    if english is None:
        return bilingual
    return WordDictionaryEntry(
        phonetic=bilingual.phonetic or english.phonetic,
        us_audio_url=english.us_audio_url or bilingual.us_audio_url,
        uk_audio_url=english.uk_audio_url or bilingual.uk_audio_url,
        meaning=bilingual.meaning or english.meaning,
        example=bilingual.example or english.example,
        senses=bilingual.senses or english.senses,
        source_name=bilingual.source_name or english.source_name,
        source_url=bilingual.source_url or english.source_url,
    )


def _parse_freedictionary_payload(payload: Any) -> WordDictionaryEntry:
    """解析 FreeDictionaryAPI.com 返回的结构化数据。"""

    if not isinstance(payload, dict):
        raise WordDictionaryUnavailableError("词典返回格式无效")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise WordDictionaryUnavailableError("词典没有收录当前单词")

    phonetic: str | None = None
    definitions: list[str] = []
    senses: list[WordDictionarySense] = []
    example: str | None = None
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        if phonetic is None:
            pronunciations = raw_entry.get("pronunciations")
            if isinstance(pronunciations, list):
                phonetic = next(
                    (
                        pronunciation.get("text").strip()
                        for pronunciation in pronunciations
                        if isinstance(pronunciation, dict)
                        and pronunciation.get("type") == "ipa"
                        and isinstance(pronunciation.get("text"), str)
                        and pronunciation.get("text").strip()
                    ),
                    None,
                )
        part_of_speech = raw_entry.get("partOfSpeech")
        normalized_part_of_speech = (
            part_of_speech.strip()
            if isinstance(part_of_speech, str) and part_of_speech.strip()
            else None
        )
        raw_senses = raw_entry.get("senses")
        if not isinstance(raw_senses, list):
            continue
        for raw_sense in raw_senses:
            if not isinstance(raw_sense, dict):
                continue
            definition = raw_sense.get("definition")
            if not isinstance(definition, str) or not definition.strip():
                continue
            cleaned_definition = definition.strip()
            raw_examples = raw_sense.get("examples")
            sense_example = (
                next(
                    (
                        item.strip()
                        for item in raw_examples
                        if isinstance(item, str) and item.strip()
                    ),
                    None,
                )
                if isinstance(raw_examples, list)
                else None
            )
            definitions.append(
                f"{normalized_part_of_speech}: {cleaned_definition}"
                if normalized_part_of_speech
                else cleaned_definition,
            )
            senses.append(
                WordDictionarySense(
                    part_of_speech=normalized_part_of_speech,
                    definition=cleaned_definition[:5000],
                    example=sense_example[:5000] if sense_example else None,
                ),
            )
            if example is None and sense_example:
                example = sense_example
            if len(senses) >= 4:
                break
        if len(senses) >= 4:
            break

    if not senses:
        raise WordDictionaryUnavailableError("词典没有返回释义")
    source = payload.get("source")
    source_url = (
        source.get("url")
        if isinstance(source, dict) and isinstance(source.get("url"), str)
        else None
    )
    return WordDictionaryEntry(
        phonetic=phonetic[:120] if phonetic else None,
        us_audio_url=None,
        uk_audio_url=None,
        meaning="\n".join(definitions)[:5000] or None,
        example=example[:5000] if example else None,
        senses=tuple(senses),
        source_name="FreeDictionaryAPI.com",
        source_url=source_url,
    )


def _parse_dictionary_payload(payload: Any) -> WordDictionaryEntry:
    """解析主词典和旧版备用词典的返回数据。"""

    if isinstance(payload, dict):
        return _parse_freedictionary_payload(payload)

    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise WordDictionaryUnavailableError("词典返回格式无效")
    entry = payload[0]
    phonetics = entry.get("phonetics")
    phonetics = phonetics if isinstance(phonetics, list) else []
    phonetic = next(
        (
            item.get("text")
            for item in phonetics
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ),
        entry.get("phonetic") if isinstance(entry.get("phonetic"), str) else None,
    )
    audio_urls = [
        url
        for item in phonetics
        if isinstance(item, dict)
        for url in [_audio_url(item.get("audio"))]
        if url is not None
    ]
    us_audio_url = next(
        (url for url in audio_urls if re.search(r"[-/_](us|ga)[._-]", url, re.I)),
        None,
    )
    uk_audio_url = next(
        (url for url in audio_urls if re.search(r"[-/_](uk|gb|rp)[._-]", url, re.I)),
        None,
    )

    definitions: list[str] = []
    senses: list[WordDictionarySense] = []
    example: str | None = None
    meanings = entry.get("meanings")
    if isinstance(meanings, list):
        for meaning in meanings:
            if not isinstance(meaning, dict):
                continue
            part_of_speech = meaning.get("partOfSpeech")
            definition_items = meaning.get("definitions")
            if not isinstance(definition_items, list):
                continue
            for definition_item in definition_items:
                if not isinstance(definition_item, dict):
                    continue
                definition = definition_item.get("definition")
                if isinstance(definition, str) and definition.strip():
                    prefix = (
                        f"{part_of_speech}: "
                        if isinstance(part_of_speech, str) and part_of_speech.strip()
                        else ""
                    )
                    cleaned_definition = definition.strip()
                    definition_example = (
                        definition_item.get("example")
                        if isinstance(definition_item.get("example"), str)
                        else None
                    )
                    definitions.append(f"{prefix}{cleaned_definition}")
                    senses.append(
                        WordDictionarySense(
                            part_of_speech=(
                                part_of_speech.strip()
                                if isinstance(part_of_speech, str)
                                and part_of_speech.strip()
                                else None
                            ),
                            definition=cleaned_definition,
                            example=(
                                definition_example[:5000]
                                if definition_example is not None
                                else None
                            ),
                        )
                    )
                    if example is None and isinstance(
                        definition_item.get("example"),
                        str,
                    ):
                        example = definition_item["example"]
                if len(definitions) >= 4:
                    break
            if len(definitions) >= 4:
                break
    return WordDictionaryEntry(
        phonetic=phonetic[:120] if isinstance(phonetic, str) else None,
        us_audio_url=us_audio_url,
        uk_audio_url=uk_audio_url,
        meaning="\n".join(definitions)[:5000] or None,
        example=example[:5000] if isinstance(example, str) else None,
        senses=tuple(senses),
    )


def _request_json(
    url: str,
    settings: Settings,
    client: httpx.Client,
) -> Any:
    """请求词典 JSON，统一超时、代理和错误处理。"""

    try:
        response = client.get(
            url,
            headers=DICTIONARY_HEADERS,
            timeout=settings.word_dictionary_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise WordDictionaryUnavailableError("词典服务暂时不可用") from error


def _lookup_english_dictionary(
    word: str,
    settings: Settings,
    client: httpx.Client,
) -> WordDictionaryEntry:
    """查询英英词典，主服务失败时尝试备用服务。"""

    urls = [
        f"{settings.word_dictionary_base_url.rstrip('/')}/{quote(word)}",
    ]
    fallback_base_url = settings.word_dictionary_fallback_base_url.strip()
    if fallback_base_url:
        fallback_url = f"{fallback_base_url.rstrip('/')}/{quote(word)}"
        if fallback_url not in urls:
            urls.append(fallback_url)

    last_error: WordDictionaryUnavailableError | None = None
    for url in urls:
        try:
            return _parse_dictionary_payload(_request_json(url, settings, client))
        except WordDictionaryUnavailableError as error:
            last_error = error
    raise last_error or WordDictionaryUnavailableError("词典服务暂时不可用")


def _lookup_bilingual_dictionary(
    word: str,
    settings: Settings,
    client: httpx.Client,
) -> WordDictionaryEntry:
    """查询中英词典，优先返回中文释义。"""

    jsonapi_url = (
        f"{settings.word_bilingual_dictionary_url.rstrip('/')}?q={quote(word)}"
    )
    try:
        return _parse_youdao_jsonapi_payload(
            _request_json(jsonapi_url, settings, client),
            word,
        )
    except WordDictionaryUnavailableError:
        suggest_url = (
            f"{settings.word_bilingual_suggest_url.rstrip('/')}"
            f"?num=8&ver=3.0&doctype=json&le=en&q={quote(word)}"
        )
        return _parse_youdao_suggest_payload(
            _request_json(suggest_url, settings, client),
            word,
        )


def lookup_word_dictionary(
    word: str,
    settings: Settings,
    client: httpx.Client | None = None,
) -> WordDictionaryEntry:
    """查询词典并返回中文释义、音标和音频地址。"""

    def lookup_with(http_client: httpx.Client) -> WordDictionaryEntry:
        bilingual: WordDictionaryEntry | None = None
        english: WordDictionaryEntry | None = None
        if settings.word_bilingual_enabled:
            try:
                bilingual = _lookup_bilingual_dictionary(word, settings, http_client)
            except WordDictionaryUnavailableError:
                bilingual = None
        if bilingual is None or bilingual.phonetic is None or bilingual.example is None:
            try:
                english = _lookup_english_dictionary(word, settings, http_client)
            except WordDictionaryUnavailableError:
                english = None
        return _merge_dictionary_entries(bilingual, english)

    if client is not None:
        return lookup_with(client)
    with httpx.Client(
        timeout=settings.word_dictionary_timeout_seconds,
        follow_redirects=True,
        # 词典是公共 HTTPS 服务，默认不继承可能失效的系统代理。
        trust_env=settings.word_dictionary_trust_env,
    ) as http_client:
        return lookup_with(http_client)


def lookup_word_preview(
    word: str,
    settings: Settings,
    client: httpx.Client | None = None,
) -> WordDictionaryEntry:
    """查询用于预览的词典数据，集中保留 Provider 调用边界。"""

    return lookup_word_dictionary(word, settings, client=client)


def enrich_word(
    session: Session,
    user_id: str,
    memo_id: str,
    settings: Settings,
    client: httpx.Client | None = None,
) -> Memo:
    """用词典数据补全缺失字段，不覆盖或追加用户已选的释义。"""

    memo = session.scalar(
        select(Memo).where(
            Memo.id == memo_id,
            Memo.user_id == user_id,
            Memo.type == MemoType.WORD,
            Memo.status != MemoStatus.TRASHED,
        ),
    )
    if memo is None:
        raise WordDictionaryUnavailableError("单词不存在")

    dictionary = lookup_word_dictionary(
        memo.normalized_lemma or normalize_word_lemma(memo.title),
        settings,
        client=client,
    )
    if not (memo.word_phonetic or "").strip() and dictionary.phonetic:
        memo.word_phonetic = dictionary.phonetic
    if not memo.word_us_audio_url and dictionary.us_audio_url:
        memo.word_us_audio_url = dictionary.us_audio_url
    if not memo.word_uk_audio_url and dictionary.uk_audio_url:
        memo.word_uk_audio_url = dictionary.uk_audio_url
    # 用户在查词预览中选择的释义必须保持原样，后台只负责填充空字段。
    if not (memo.word_meaning or "").strip() and dictionary.meaning:
        memo.word_meaning = dictionary.meaning
    if not (memo.word_example or "").strip() and dictionary.example:
        memo.word_example = dictionary.example
    if not memo.body.strip():
        memo.body = memo.word_meaning or memo.body
    memo.version += 1
    memo.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(memo)
    return memo


def enrich_word_in_background(
    database_url: str,
    user_id: str,
    memo_id: str,
    settings: Settings,
) -> None:
    """使用独立数据库会话执行单词补全任务。"""

    database = Database(database_url)
    try:
        with database.session_factory() as session:
            try:
                enrich_word(session, user_id, memo_id, settings)
            except WordDictionaryUnavailableError:
                return
    finally:
        database.dispose()
