"""条目全文检索：SQLite FTS5 trigram 索引与查询条件。

原先每个关键词要对 27 个字段做 ``ILIKE '%x%'``（其中几个还要把 JSON 列
cast 成字符串），条目一多就会整表扫描，结果也只能按更新时间排列。

这里把所有可搜索文本汇总到一张 FTS5 表，分成三列：

- ``title``：标题，排序权重最高；
- ``tags``：手动标签、自动标签、图片标签（从 JSON 解码后的原文）；
- ``content``：正文、网址、摘要、释义、转写、OCR 等其余文本。

trigram 分词器按三个字符切分，中文无需分词即可子串匹配。长度不足三个字符
的关键词无法命中 trigram 索引，退回到 FTS 表上的 ``LIKE``，只扫一张表的
三列，仍比原来的 27 个字段便宜。

索引由数据库触发器维护：ORM 写入、批量 ``UPDATE`` 和导入都会自动同步，
不需要在业务代码里逐处调用。FTS 行通过 ``memo_search_doc`` 映射到条目 ID，
因为 ``memo`` 表的隐式 rowid 在 ``VACUUM``（包括备份用的 ``VACUUM INTO``）
后可能被重新编号，不能直接拿来关联。
"""

from __future__ import annotations

import logging

from sqlalchemy import (
    ColumnElement,
    Connection,
    and_,
    case,
    column,
    func,
    literal_column,
    or_,
    table,
    text,
)

logger = logging.getLogger(__name__)

# trigram 至少需要三个字符才能走索引。
TRIGRAM_MIN_LENGTH = 3
# bm25 列权重：标题 > 标签 > 其他文本。
BM25_WEIGHTS = (10.0, 4.0, 1.0)

_TEXT_COLUMNS = (
    "body",
    "source_url",
    "source_title",
    "resource_page_title",
    "resource_description",
    "resource_ai_summary",
    "resource_site_name",
    "resource_category",
    "resource_category_label",
    "resource_kind",
    "resource_reading_status",
    "resource_import_folder",
    "word_phonetic",
    "word_meaning",
    "word_example",
    "transcript",
    "image_ocr_text",
)
_CONTENT_JSON_COLUMNS = ("resource_categories", "collections")
_TAG_JSON_COLUMNS = ("tags", "resource_auto_tags", "image_auto_tags")
# 触发器只在这些列变化时重建索引行，打开次数、同步状态等更新不受影响。
_WATCHED_COLUMNS = (
    "title",
    *_TEXT_COLUMNS,
    *_CONTENT_JSON_COLUMNS,
    *_TAG_JSON_COLUMNS,
)

memo_search_doc = table("memo_search_doc", column("rowid"), column("memo_id"))
memo_search = table(
    "memo_search",
    column("rowid"),
    column("title"),
    column("tags"),
    column("content"),
)

# 由 ``ensure_memo_search_index`` 在 SQLite 上成功建好索引后打开；
# 其他数据库或不支持 trigram 的旧版 SQLite 保持关闭，查询退回 ILIKE。
_fts_enabled = False


def fts_enabled() -> bool:
    """当前进程的数据库是否可以使用 FTS 检索。"""

    return _fts_enabled


def _json_text(alias: str, name: str) -> str:
    # json_valid 兜底，避免历史脏数据让触发器报错、进而挡住正常写入。
    return (
        f"CASE WHEN json_valid({alias}.{name}) THEN "
        f"(SELECT group_concat(value, ' ') FROM json_each({alias}.{name})) END"
    )


def _joined(parts: list[str]) -> str:
    return " || ' ' || ".join(f"coalesce({part}, '')" for part in parts)


def _row_values(alias: str) -> str:
    title = f"coalesce({alias}.title, '')"
    tags = _joined([_json_text(alias, name) for name in _TAG_JSON_COLUMNS])
    content = _joined(
        [f"{alias}.{name}" for name in _TEXT_COLUMNS]
        + [_json_text(alias, name) for name in _CONTENT_JSON_COLUMNS],
    )
    return f"{title}, {tags}, {content}"


def _doc_rowid(alias: str) -> str:
    return f"(SELECT rowid FROM memo_search_doc WHERE memo_id = {alias}.id)"


def _index_statements(alias: str) -> list[str]:
    return [
        f"INSERT OR IGNORE INTO memo_search_doc (memo_id) VALUES ({alias}.id);",
        "INSERT INTO memo_search (rowid, title, tags, content) "
        f"VALUES ({_doc_rowid(alias)}, {_row_values(alias)});",
    ]


def _unindex_statements(alias: str) -> list[str]:
    return [f"DELETE FROM memo_search WHERE rowid = {_doc_rowid(alias)};"]


def _schema_statements() -> list[str]:
    watched = ", ".join(_WATCHED_COLUMNS)
    insert_body = "\n".join(_index_statements("new"))
    update_body = "\n".join(_unindex_statements("old") + _index_statements("new"))
    delete_body = "\n".join(
        _unindex_statements("old")
        + ["DELETE FROM memo_search_doc WHERE memo_id = old.id;"],
    )
    return [
        "CREATE TABLE IF NOT EXISTS memo_search_doc ("
        "rowid INTEGER PRIMARY KEY, memo_id VARCHAR(36) NOT NULL UNIQUE)",
        "CREATE VIRTUAL TABLE IF NOT EXISTS memo_search USING fts5("
        "title, tags, content, tokenize = 'trigram')",
        "DROP TRIGGER IF EXISTS memo_search_ai",
        "DROP TRIGGER IF EXISTS memo_search_au",
        "DROP TRIGGER IF EXISTS memo_search_ad",
        f"CREATE TRIGGER memo_search_ai AFTER INSERT ON memo BEGIN\n{insert_body}\nEND",
        f"CREATE TRIGGER memo_search_au AFTER UPDATE OF {watched} ON memo "
        f"BEGIN\n{update_body}\nEND",
        f"CREATE TRIGGER memo_search_ad AFTER DELETE ON memo BEGIN\n{delete_body}\nEND",
    ]


def rebuild_memo_search_index(connection: Connection) -> None:
    """按 memo 表全量重建检索索引。"""

    connection.execute(text("DELETE FROM memo_search"))
    connection.execute(text("DELETE FROM memo_search_doc"))
    connection.execute(
        text("INSERT INTO memo_search_doc (memo_id) SELECT id FROM memo"),
    )
    connection.execute(
        text(
            "INSERT INTO memo_search (rowid, title, tags, content) "
            f"SELECT d.rowid, {_row_values('m')} "
            "FROM memo m JOIN memo_search_doc d ON d.memo_id = m.id",
        ),
    )


def ensure_memo_search_index(connection: Connection) -> bool:
    """建好 FTS 表与触发器；索引行数与条目数不一致时全量重建。

    返回是否可以使用 FTS。旧版 SQLite（< 3.34）没有 trigram 分词器，
    此时记录日志并退回 ILIKE，不影响启动。
    """

    global _fts_enabled
    try:
        for statement in _schema_statements():
            connection.execute(text(statement))
    except Exception:  # noqa: BLE001 - 任何建表失败都只降级，不阻断启动
        logger.warning("SQLite FTS5 trigram 不可用，搜索退回 ILIKE", exc_info=True)
        _fts_enabled = False
        return False
    memo_count = connection.execute(text("SELECT count(*) FROM memo")).scalar_one()
    indexed_count = connection.execute(
        text("SELECT count(*) FROM memo_search_doc"),
    ).scalar_one()
    if memo_count != indexed_count:
        rebuild_memo_search_index(connection)
    _fts_enabled = True
    return True


def fts_match_expression(tokens: list[str]) -> str | None:
    """把长关键词拼成 FTS5 MATCH 表达式；关键词之间为「与」。"""

    phrases = [
        '"' + token.replace('"', '""') + '"'
        for token in tokens
        if len(token) >= TRIGRAM_MIN_LENGTH
    ]
    return " ".join(phrases) if phrases else None


def short_token_conditions(
    tokens: list[str],
    escape_like_pattern,
) -> list[ColumnElement[bool]]:
    """不足三个字符的关键词在 FTS 表三列上做 LIKE。"""

    conditions: list[ColumnElement[bool]] = []
    for token in tokens:
        if len(token) >= TRIGRAM_MIN_LENGTH:
            continue
        pattern = f"%{escape_like_pattern(token)}%"
        conditions.append(
            or_(
                memo_search.c.title.like(pattern, escape="\\"),
                memo_search.c.tags.like(pattern, escape="\\"),
                memo_search.c.content.like(pattern, escape="\\"),
            ),
        )
    return conditions


def search_condition(tokens: list[str], escape_like_pattern) -> ColumnElement[bool]:
    """组合 MATCH 与短词 LIKE，作为关联 FTS 表后的过滤条件。"""

    conditions = short_token_conditions(tokens, escape_like_pattern)
    match = fts_match_expression(tokens)
    if match is not None:
        conditions.insert(0, literal_column("memo_search").op("MATCH")(match))
    return and_(*conditions)


def relevance_order(tokens: list[str], escape_like_pattern) -> list[ColumnElement]:
    """相关度排序：有长关键词用 bm25，否则把标题命中排在前面。"""

    if fts_match_expression(tokens) is not None:
        return [func.bm25(literal_column("memo_search"), *BM25_WEIGHTS).asc()]
    pattern = f"%{escape_like_pattern(tokens[0])}%"
    return [
        case((memo_search.c.title.like(pattern, escape="\\"), 0), else_=1).asc(),
    ]
