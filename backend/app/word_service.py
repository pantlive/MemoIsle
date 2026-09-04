"""英语单词词典补全与词形归并服务。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
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
    "ran": "run",
    "better": "good",
    "best": "good",
    "brought": "bring",
    "built": "build",
    "bought": "buy",
    "caught": "catch",
    "children": "child",
    "did": "do",
    "done": "do",
    "drank": "drink",
    "driven": "drive",
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
    "had": "have",
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
    "saw": "see",
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


class WordDictionaryUnavailableError(RuntimeError):
    """词典服务不可用或没有收录当前单词。"""


@dataclass(frozen=True, slots=True)
class WordDictionaryEntry:
    """词典服务返回的单词补全数据。"""

    phonetic: str | None
    us_audio_url: str | None
    uk_audio_url: str | None
    meaning: str | None
    example: str | None


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
        return f"{token[:-3]}f"
    if token.endswith(("ches", "shes", "sses", "xes", "zes")) and len(token) > 4:
        return token[:-2]
    if token.endswith("ses") and len(token) > 4:
        return token[:-1]
    if (
        token.endswith("s")
        and not token.endswith(("ss", "us", "is"))
        and len(token) > 3
    ):
        return token[:-1]
    if token.endswith("ing") and len(token) > 5:
        stem = token[:-3]
        if stem.endswith("i"):
            return f"{stem[:-1]}y"
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "lsz":
            return stem[:-1]
        if stem.endswith(("ck", "ll", "ss", "sh", "ch", "tch")):
            return stem
        return f"{stem}e"
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        if stem.endswith("i"):
            return f"{stem[:-1]}y"
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "lsz":
            return stem[:-1]
        return stem
    if token.endswith("est") and len(token) > 5:
        return token[:-3]
    if token.endswith("er") and len(token) > 4:
        return token[:-2]
    return token


def _audio_url(url: Any) -> str | None:
    """仅返回合法 HTTP(S) 音频地址。"""

    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    return url[:2048]


def _parse_dictionary_payload(payload: Any) -> WordDictionaryEntry:
    """解析 Free Dictionary API 的最小数据结构。"""

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
                    definitions.append(f"{prefix}{definition.strip()}")
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
    )


def lookup_word_dictionary(
    word: str,
    settings: Settings,
    client: httpx.Client | None = None,
) -> WordDictionaryEntry:
    """查询词典并返回释义、音标和音频地址。"""

    url = f"{settings.word_dictionary_base_url.rstrip('/')}/{quote(word)}"
    try:
        if client is None:
            with httpx.Client(
                timeout=settings.word_dictionary_timeout_seconds,
                follow_redirects=True,
            ) as http_client:
                response = http_client.get(url)
        else:
            response = client.get(url)
        response.raise_for_status()
        return _parse_dictionary_payload(response.json())
    except (httpx.HTTPError, ValueError, TypeError) as error:
        raise WordDictionaryUnavailableError("词典服务暂时不可用") from error


def _append_unique(existing: str | None, incoming: str | None) -> str | None:
    """把词典文本补充到已有字段，避免重复段落。"""

    addition = (incoming or "").strip()
    if not addition:
        return existing
    current = (existing or "").strip()
    if not current:
        return addition
    if addition.casefold() in current.casefold():
        return current
    return f"{current}\n{addition}"


def enrich_word(
    session: Session,
    user_id: str,
    memo_id: str,
    settings: Settings,
    client: httpx.Client | None = None,
) -> Memo:
    """用词典数据补全缺失的音标、释义、例句和音频。"""

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
    memo.word_meaning = _append_unique(memo.word_meaning, dictionary.meaning)
    memo.word_example = _append_unique(memo.word_example, dictionary.example)
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
