"""单词词形归并与词典补全测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.config import Settings
from app.word_service import (
    WordDictionaryEntry,
    WordDictionarySense,
    WordDictionaryUnavailableError,
    _parse_dictionary_payload,
    _parse_youdao_jsonapi_payload,
    _parse_youdao_suggest_payload,
    lookup_word_dictionary,
    normalize_word_lemma,
)
from fastapi.testclient import TestClient


def test_normalize_word_lemma_merges_common_inflections() -> None:
    """常见英文屈折变化应归并到同一词元。"""

    assert normalize_word_lemma("Running") == "run"
    assert normalize_word_lemma("ran") == "run"
    assert normalize_word_lemma("RUN") == "run"
    assert normalize_word_lemma("Studies") == "study"
    assert normalize_word_lemma("boxes") == "box"
    assert normalize_word_lemma("went") == "go"


def test_normalize_word_lemma_handles_irregular_and_spelling_variants() -> None:
    """常见不规则、-ing、-ed 和比较级词形应避免误归并。"""

    expected = {
        "being": "be",
        "does": "do",
        "goes": "go",
        "fixing": "fix",
        "loved": "love",
        "studying": "study",
        "studied": "study",
        "dying": "die",
        "making": "make",
        "writing": "write",
        "bigger": "big",
        "biggest": "big",
        "happier": "happy",
        "largest": "large",
        "loves": "love",
        "buses": "bus",
        "movies": "movie",
        "water": "water",
        "news": "news",
        "means": "means",
    }
    assert {
        word: normalize_word_lemma(word)
        for word in expected
    } == expected


def test_parse_dictionary_payload_extracts_word_details() -> None:
    """词典返回应提取释义、音标、例句和英美音源。"""

    payload = [
        {
            "word": "run",
            "phonetic": "/rʌn/",
            "phonetics": [
                {"text": "/rʌn/", "audio": "https://example.com/run-uk.mp3"},
                {"text": "/rʌn/", "audio": "https://example.com/run-us.mp3"},
            ],
            "meanings": [
                {
                    "partOfSpeech": "verb",
                    "definitions": [
                        {
                            "definition": "Move fast on foot.",
                            "example": "She runs every morning.",
                        }
                    ],
                }
            ],
        }
    ]
    entry = _parse_dictionary_payload(payload)
    assert entry == WordDictionaryEntry(
        phonetic="/rʌn/",
        us_audio_url="https://example.com/run-us.mp3",
        uk_audio_url="https://example.com/run-uk.mp3",
        meaning="verb: Move fast on foot.",
        example="She runs every morning.",
    )


def test_word_dictionary_does_not_inherit_broken_proxy_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认查词客户端不应继承会导致公共词典超时的系统代理。"""

    client_options: dict[str, object] = {}

    class FakeResponse:
        """提供词典请求所需的最小响应对象。"""

        def raise_for_status(self) -> None:
            """模拟成功的 HTTP 响应。"""

        def json(self) -> list[dict[str, object]]:
            """返回可被解析的最小词典结果。"""

            return [{"word": "run", "phonetics": [], "meanings": []}]

    class FakeClient:
        """记录 HTTP 客户端配置，避免测试真的访问网络。"""

        def __init__(self, **kwargs: object) -> None:
            client_options.update(kwargs)

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, _url: str, **_kwargs: object) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("app.word_service.httpx.Client", FakeClient)
    settings = Settings(
        database_url="sqlite+pysqlite:///dictionary-test.db",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        audio_directory=Path("audio"),
    )

    lookup_word_dictionary("run", settings)

    assert client_options["trust_env"] is False


def test_parse_youdao_payload_extracts_chinese_senses() -> None:
    """有道英中词典应抽出中文释义、词性和双语例句。"""

    payload = {
        "ec": {
            "word": [
                {
                    "usphone": "ˌserənˈdɪpəti",
                    "ukphone": "ˌserənˈdɪpəti",
                    "trs": [
                        {
                            "tr": [
                                {
                                    "l": {
                                        "i": [
                                            "n. 意外发现美好事物的运气，机缘巧合",
                                        ],
                                    },
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "blng_sents_part": {
            "sentence-pair": [
                {
                    "sentence": "Some of the best effects were serendipity.",
                    "sentence-translation": "最珍贵的几件物品是机缘巧合之下意外所得。",
                },
            ],
        },
    }
    entry = _parse_youdao_jsonapi_payload(payload, "serendipity")
    assert entry.phonetic == "/ˌserənˈdɪpəti/"
    assert entry.senses[0].part_of_speech == "名词"
    assert entry.senses[0].definition == "意外发现美好事物的运气，机缘巧合"
    assert "机缘巧合" in (entry.meaning or "")
    assert entry.example is not None
    assert "意外所得" in entry.example
    assert entry.senses[0].example is not None
    assert "意外所得" in entry.senses[0].example


def test_parse_youdao_suggest_payload_keeps_exact_entry() -> None:
    """联想接口只采用当前词形的中文释义。"""

    payload = {
        "data": {
            "entries": [
                {
                    "entry": "serendipity",
                    "explain": "n. 意外发现美好事物的运气，机缘巧合",
                },
                {
                    "entry": "serendipitous",
                    "explain": "adj. 侥幸的，凑巧的",
                },
            ],
        },
    }
    entry = _parse_youdao_suggest_payload(payload, "serendipity")
    assert [sense.definition for sense in entry.senses] == [
        "意外发现美好事物的运气，机缘巧合",
    ]
    assert entry.senses[0].part_of_speech == "名词"


def test_parse_youdao_suggest_payload_rejects_prefix_entry() -> None:
    """联想接口不得把 apple 当成 app 的释义。"""

    payload = {
        "data": {
            "entries": [
                {"entry": "apple", "explain": "n. 苹果"},
                {"entry": "application", "explain": "n. 应用，申请"},
            ],
        },
    }
    with pytest.raises(WordDictionaryUnavailableError):
        _parse_youdao_suggest_payload(payload, "app")


def test_lookup_prefers_chinese_senses_over_english() -> None:
    """查词预览应优先使用中文释义。"""

    class FakeResponse:
        """按请求地址返回中英或英英词典数据。"""

        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            """模拟成功响应。"""

        def json(self) -> object:
            return self._payload

    class FakeClient:
        """根据 URL 选择中英或英英结果。"""

        def get(self, url: str, **_kwargs: object) -> FakeResponse:
            if "youdao.com/jsonapi" in url:
                return FakeResponse(
                    {
                        "ec": {
                            "word": [
                                {
                                    "usphone": "rʌn",
                                    "trs": [
                                        {"tr": [{"l": {"i": ["v. 跑，奔跑"]}}]},
                                        {"tr": [{"l": {"i": ["n. 跑步，赛跑"]}}]},
                                    ],
                                },
                            ],
                        },
                    },
                )
            return FakeResponse(
                [
                    {
                        "word": "run",
                        "phonetic": "/rʌn/",
                        "phonetics": [
                            {
                                "text": "/rʌn/",
                                "audio": "https://example.com/run-us.mp3",
                            },
                        ],
                        "meanings": [
                            {
                                "partOfSpeech": "verb",
                                "definitions": [
                                    {
                                        "definition": "Move fast on foot.",
                                        "example": "She runs every morning.",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            )

    settings = Settings(
        database_url="sqlite+pysqlite:///dictionary-test.db",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        audio_directory=Path("audio"),
    )
    entry = lookup_word_dictionary("run", settings, client=FakeClient())
    assert [sense.definition for sense in entry.senses] == ["跑，奔跑", "跑步，赛跑"]
    assert entry.senses[0].part_of_speech == "动词"
    assert entry.phonetic == "/rʌn/"
    assert entry.us_audio_url == "https://example.com/run-us.mp3"
    assert entry.example == "She runs every morning."


def test_word_dictionary_enrichment_and_inflection_duplicate(
    client,
    monkeypatch,
) -> None:
    """单词可补全词典信息，不同词形默认视为重复。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "Running",
            "body": "I was running in the park.",
        },
    )
    assert created.status_code == 201
    word = created.json()

    duplicate = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "ran",
            "body": "He ran fast.",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["current"]["id"] == word["id"]

    def fake_lookup(*_args: object, **_kwargs: object) -> WordDictionaryEntry:
        """返回固定词典数据，避免测试依赖外网。"""

        return WordDictionaryEntry(
            phonetic="/rʌn/",
            us_audio_url="https://example.com/run-us.mp3",
            uk_audio_url="https://example.com/run-uk.mp3",
            meaning="verb: Move fast on foot.",
            example="She runs every morning.",
        )

    monkeypatch.setattr("app.word_service.lookup_word_dictionary", fake_lookup)
    enriched = client.post(f"/api/v1/words/{word['id']}/dictionary")
    assert enriched.status_code == 200
    enriched_word = enriched.json()
    assert enriched_word["word_phonetic"] == "/rʌn/"
    assert enriched_word["word_us_audio_url"] == "https://example.com/run-us.mp3"
    assert enriched_word["word_uk_audio_url"] == "https://example.com/run-uk.mp3"
    assert enriched_word["word_meaning"] == "verb: Move fast on foot."
    assert enriched_word["word_example"] == "She runs every morning."


def test_word_lookup_returns_selectable_senses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """查词接口应返回词元、发音和可逐条选择的释义。"""

    def fake_lookup(*_args: object, **_kwargs: object) -> WordDictionaryEntry:
        """返回固定查词结果，避免测试依赖外网。"""

        return WordDictionaryEntry(
            phonetic="/rʌn/",
            us_audio_url="https://example.com/run-us.mp3",
            uk_audio_url="https://example.com/run-uk.mp3",
            meaning="verb: Move fast on foot.\nnoun: A trip or period of running.",
            example="She runs every morning.",
            senses=(
                WordDictionarySense(
                    part_of_speech="verb",
                    definition="Move fast on foot.",
                    example="She runs every morning.",
                ),
                WordDictionarySense(
                    part_of_speech="noun",
                    definition="A trip or period of running.",
                    example=None,
                ),
            ),
        )

    monkeypatch.setattr("app.word_service.lookup_word_dictionary", fake_lookup)
    response = client.post("/api/v1/words/lookup", json={"word": "Running"})

    assert response.status_code == 200
    assert response.json() == {
        "word": "Running",
        "lemma": "run",
        "phonetic": "/rʌn/",
        "us_audio_url": "https://example.com/run-us.mp3",
        "uk_audio_url": "https://example.com/run-uk.mp3",
        "senses": [
            {
                "index": 0,
                "part_of_speech": "verb",
                "definition": "Move fast on foot.",
                "example": "She runs every morning.",
            },
            {
                "index": 1,
                "part_of_speech": "noun",
                "definition": "A trip or period of running.",
                "example": None,
            },
        ],
        "source_name": None,
        "source_url": None,
    }


def test_word_dictionary_does_not_append_to_manual_meaning(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """后台补全不能把未选择的词典释义追加到用户手工内容。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": "run",
            "body": "用户自己的理解",
            "word_meaning": "用户自己的理解",
            "word_example": "用户自己的例句",
        },
    )
    assert created.status_code == 201

    def fake_lookup(*_args: object, **_kwargs: object) -> WordDictionaryEntry:
        """返回包含其他释义的词典结果。"""

        return WordDictionaryEntry(
            phonetic="/rʌn/",
            us_audio_url=None,
            uk_audio_url=None,
            meaning="verb: Move fast on foot.\nnoun: A trip.",
            example="A dictionary example.",
        )

    monkeypatch.setattr("app.word_service.lookup_word_dictionary", fake_lookup)
    enriched = client.post(f"/api/v1/words/{created.json()['id']}/dictionary")

    assert enriched.status_code == 200
    assert enriched.json()["word_meaning"] == "用户自己的理解"
    assert enriched.json()["word_example"] == "用户自己的例句"
