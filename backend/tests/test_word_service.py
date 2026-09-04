"""单词词形归并与词典补全测试。"""

from __future__ import annotations

from uuid import uuid4

from app.word_service import (
    WordDictionaryEntry,
    _parse_dictionary_payload,
    normalize_word_lemma,
)


def test_normalize_word_lemma_merges_common_inflections() -> None:
    """常见英文屈折变化应归并到同一词元。"""

    assert normalize_word_lemma("Running") == "run"
    assert normalize_word_lemma("ran") == "run"
    assert normalize_word_lemma("RUN") == "run"
    assert normalize_word_lemma("Studies") == "study"
    assert normalize_word_lemma("boxes") == "box"
    assert normalize_word_lemma("went") == "go"


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
