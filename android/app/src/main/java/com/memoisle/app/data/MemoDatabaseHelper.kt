package com.memoisle.app.data

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray

class MemoDatabaseHelper(context: Context) :
    SQLiteOpenHelper(context, DATABASE_NAME, null, DATABASE_VERSION) {

    override fun onCreate(database: SQLiteDatabase) {
        database.execSQL(
            """
            CREATE TABLE memo (
                client_id TEXT PRIMARY KEY,
                remote_id TEXT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                source_url TEXT,
                source_title TEXT,
                resource_description TEXT,
                resource_site_name TEXT,
                resource_image_url TEXT,
                resource_category TEXT,
                resource_kind TEXT,
                resource_reading_status TEXT,
                resource_category_status TEXT NOT NULL DEFAULT 'none',
                resource_auto_tags_json TEXT NOT NULL DEFAULT '[]',
                resource_import_folder TEXT,
                link_health_status TEXT NOT NULL DEFAULT 'unchecked',
                link_health_http_status INTEGER,
                link_health_error TEXT,
                link_last_checked_at TEXT,
                link_last_success_at TEXT,
                link_effective_url TEXT,
                word_phonetic TEXT,
                word_meaning TEXT,
                word_example TEXT,
                familiarity INTEGER NOT NULL,
                review_count INTEGER NOT NULL,
                last_review_at TEXT,
                next_review_at TEXT,
                audio_mime_type TEXT,
                audio_size_bytes INTEGER,
                audio_duration_ms INTEGER,
                transcript TEXT,
                transcript_status TEXT NOT NULL,
                local_audio_path TEXT,
                tags_json TEXT NOT NULL,
                collections_json TEXT NOT NULL DEFAULT '[]',
                starred INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sync_state TEXT NOT NULL
            )
            """.trimIndent(),
        )
        database.execSQL("CREATE INDEX index_memo_updated ON memo(updated_at DESC)")
    }

    override fun onUpgrade(database: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) {
            // 保留已有灵感，并为资料类型补充来源字段。
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN type TEXT NOT NULL DEFAULT 'idea'",
            )
            database.execSQL("ALTER TABLE memo ADD COLUMN source_url TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN source_title TEXT")
        }
        if (oldVersion < 3) {
            // 单词字段均为可空或带默认值，迁移不会影响已有资料与灵感。
            database.execSQL("ALTER TABLE memo ADD COLUMN word_phonetic TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN word_meaning TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN word_example TEXT")
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN familiarity INTEGER NOT NULL DEFAULT 0",
            )
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN review_count INTEGER NOT NULL DEFAULT 0",
            )
            database.execSQL("ALTER TABLE memo ADD COLUMN last_review_at TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN next_review_at TEXT")
        }
        if (oldVersion < 4) {
            // 录音文件路径只保存在本机，服务端仅同步音频元数据。
            database.execSQL("ALTER TABLE memo ADD COLUMN audio_mime_type TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN audio_size_bytes INTEGER")
            database.execSQL("ALTER TABLE memo ADD COLUMN audio_duration_ms INTEGER")
            database.execSQL("ALTER TABLE memo ADD COLUMN transcript TEXT")
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN transcript_status TEXT NOT NULL DEFAULT 'none'",
            )
            database.execSQL("ALTER TABLE memo ADD COLUMN local_audio_path TEXT")
        }
        if (oldVersion < 5) {
            // Android 只读展示 Web 自动整理和巡检后的资料字段。
            database.execSQL("ALTER TABLE memo ADD COLUMN resource_description TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN resource_site_name TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN resource_category TEXT")
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN resource_category_status TEXT " +
                    "NOT NULL DEFAULT 'none'",
            )
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN resource_auto_tags_json TEXT " +
                    "NOT NULL DEFAULT '[]'",
            )
            database.execSQL("ALTER TABLE memo ADD COLUMN resource_import_folder TEXT")
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN link_health_status TEXT " +
                    "NOT NULL DEFAULT 'unchecked'",
            )
            database.execSQL("ALTER TABLE memo ADD COLUMN link_health_http_status INTEGER")
            database.execSQL("ALTER TABLE memo ADD COLUMN link_health_error TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN link_last_checked_at TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN link_last_success_at TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN link_effective_url TEXT")
        }
        if (oldVersion < 6) {
            // 为已有资料补充网页封面地址。
            database.execSQL("ALTER TABLE memo ADD COLUMN resource_image_url TEXT")
        }
        if (oldVersion < 7) {
            // 为已有资料补充资源形态、阅读进度、收藏夹和星标字段。
            database.execSQL("ALTER TABLE memo ADD COLUMN resource_kind TEXT")
            database.execSQL("ALTER TABLE memo ADD COLUMN resource_reading_status TEXT")
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN collections_json TEXT " +
                    "NOT NULL DEFAULT '[]'",
            )
            database.execSQL(
                "ALTER TABLE memo ADD COLUMN starred INTEGER NOT NULL DEFAULT 0",
            )
        }
    }

    @Synchronized
    fun upsert(memo: Memo) {
        insertMemo(writableDatabase, memo)
    }

    @Synchronized
    fun reconcileCreatedMemo(localClientId: String, remoteMemo: Memo) {
        val database = writableDatabase
        database.beginTransaction()
        try {
            if (localClientId != remoteMemo.clientId) {
                // URL 去重可能返回服务端已有资料，先移除本地临时行以免重复。
                database.delete(
                    TABLE_MEMO,
                    "$COLUMN_CLIENT_ID = ?",
                    arrayOf(localClientId),
                )
            }
            insertMemo(database, remoteMemo)
            database.setTransactionSuccessful()
        } finally {
            database.endTransaction()
        }
    }

    private fun insertMemo(database: SQLiteDatabase, memo: Memo) {
        database.insertWithOnConflict(
            TABLE_MEMO,
            null,
            memoContentValues(memo),
            SQLiteDatabase.CONFLICT_REPLACE,
        )
    }

    private fun memoContentValues(memo: Memo): ContentValues =
        ContentValues().apply {
            put(COLUMN_CLIENT_ID, memo.clientId)
            put(COLUMN_REMOTE_ID, memo.id)
            put(COLUMN_TYPE, memo.type)
            put(COLUMN_TITLE, memo.title)
            put(COLUMN_BODY, memo.body)
            put(COLUMN_SOURCE_URL, memo.sourceUrl)
            put(COLUMN_SOURCE_TITLE, memo.sourceTitle)
            put(COLUMN_RESOURCE_DESCRIPTION, memo.resourceDescription)
            put(COLUMN_RESOURCE_SITE_NAME, memo.resourceSiteName)
            put(COLUMN_RESOURCE_IMAGE_URL, memo.resourceImageUrl)
            put(COLUMN_RESOURCE_CATEGORY, memo.resourceCategory)
            put(COLUMN_RESOURCE_KIND, memo.resourceKind)
            put(COLUMN_RESOURCE_READING_STATUS, memo.resourceReadingStatus)
            put(COLUMN_RESOURCE_CATEGORY_STATUS, memo.resourceCategoryStatus)
            put(COLUMN_RESOURCE_AUTO_TAGS, JSONArray(memo.resourceAutoTags).toString())
            put(COLUMN_RESOURCE_IMPORT_FOLDER, memo.resourceImportFolder)
            put(COLUMN_LINK_HEALTH_STATUS, memo.linkHealthStatus)
            put(COLUMN_LINK_HEALTH_HTTP_STATUS, memo.linkHealthHttpStatus)
            put(COLUMN_LINK_HEALTH_ERROR, memo.linkHealthError)
            put(COLUMN_LINK_LAST_CHECKED_AT, memo.linkLastCheckedAt)
            put(COLUMN_LINK_LAST_SUCCESS_AT, memo.linkLastSuccessAt)
            put(COLUMN_LINK_EFFECTIVE_URL, memo.linkEffectiveUrl)
            put(COLUMN_WORD_PHONETIC, memo.wordPhonetic)
            put(COLUMN_WORD_MEANING, memo.wordMeaning)
            put(COLUMN_WORD_EXAMPLE, memo.wordExample)
            put(COLUMN_FAMILIARITY, memo.familiarity)
            put(COLUMN_REVIEW_COUNT, memo.reviewCount)
            put(COLUMN_LAST_REVIEW_AT, memo.lastReviewAt)
            put(COLUMN_NEXT_REVIEW_AT, memo.nextReviewAt)
            put(COLUMN_AUDIO_MIME_TYPE, memo.audioMimeType)
            put(COLUMN_AUDIO_SIZE_BYTES, memo.audioSizeBytes)
            put(COLUMN_AUDIO_DURATION_MS, memo.audioDurationMs)
            put(COLUMN_TRANSCRIPT, memo.transcript)
            put(COLUMN_TRANSCRIPT_STATUS, memo.transcriptStatus)
            put(COLUMN_LOCAL_AUDIO_PATH, memo.localAudioPath)
            put(COLUMN_TAGS, JSONArray(memo.tags).toString())
            put(COLUMN_COLLECTIONS, JSONArray(memo.collections).toString())
            put(COLUMN_STARRED, if (memo.starred) 1 else 0)
            put(COLUMN_STATUS, memo.status)
            put(COLUMN_VERSION, memo.version)
            put(COLUMN_CREATED_AT, memo.createdAt)
            put(COLUMN_UPDATED_AT, memo.updatedAt)
            put(COLUMN_SYNC_STATE, memo.syncState.name)
        }

    @Synchronized
    fun updateSyncState(clientId: String, syncState: SyncState) {
        val values = ContentValues().apply {
            put(COLUMN_SYNC_STATE, syncState.name)
        }
        writableDatabase.update(
            TABLE_MEMO,
            values,
            "$COLUMN_CLIENT_ID = ?",
            arrayOf(clientId),
        )
    }

    @Synchronized
    fun loadMemos(): List<Memo> = queryMemos(selection = null, arguments = null)

    @Synchronized
    fun loadPending(): List<Memo> = queryMemos(
        selection = "$COLUMN_SYNC_STATE != ?",
        arguments = arrayOf(SyncState.SYNCED.name),
    )

    private fun queryMemos(selection: String?, arguments: Array<String>?): List<Memo> {
        return readableDatabase.query(
            TABLE_MEMO,
            ALL_COLUMNS,
            selection,
            arguments,
            null,
            null,
            "$COLUMN_UPDATED_AT DESC",
        ).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    add(cursor.toMemo())
                }
            }
        }
    }

    private fun Cursor.toMemo(): Memo {
        val tagsJson = getString(getColumnIndexOrThrow(COLUMN_TAGS))
        val tagsArray = JSONArray(tagsJson)
        val tags = buildList {
            for (index in 0 until tagsArray.length()) {
                add(tagsArray.getString(index))
            }
        }
        val remoteIdIndex = getColumnIndexOrThrow(COLUMN_REMOTE_ID)
        val sourceUrlIndex = getColumnIndexOrThrow(COLUMN_SOURCE_URL)
        val sourceTitleIndex = getColumnIndexOrThrow(COLUMN_SOURCE_TITLE)
        val resourceDescriptionIndex = getColumnIndexOrThrow(COLUMN_RESOURCE_DESCRIPTION)
        val resourceSiteNameIndex = getColumnIndexOrThrow(COLUMN_RESOURCE_SITE_NAME)
        val resourceImageUrlIndex = getColumnIndexOrThrow(COLUMN_RESOURCE_IMAGE_URL)
        val resourceCategoryIndex = getColumnIndexOrThrow(COLUMN_RESOURCE_CATEGORY)
        val resourceKindIndex = getColumnIndexOrThrow(COLUMN_RESOURCE_KIND)
        val resourceReadingStatusIndex = getColumnIndexOrThrow(COLUMN_RESOURCE_READING_STATUS)
        val resourceImportFolderIndex = getColumnIndexOrThrow(COLUMN_RESOURCE_IMPORT_FOLDER)
        val linkHealthHttpStatusIndex = getColumnIndexOrThrow(COLUMN_LINK_HEALTH_HTTP_STATUS)
        val linkHealthErrorIndex = getColumnIndexOrThrow(COLUMN_LINK_HEALTH_ERROR)
        val linkLastCheckedIndex = getColumnIndexOrThrow(COLUMN_LINK_LAST_CHECKED_AT)
        val linkLastSuccessIndex = getColumnIndexOrThrow(COLUMN_LINK_LAST_SUCCESS_AT)
        val linkEffectiveUrlIndex = getColumnIndexOrThrow(COLUMN_LINK_EFFECTIVE_URL)
        val resourceAutoTags = JSONArray(
            getString(getColumnIndexOrThrow(COLUMN_RESOURCE_AUTO_TAGS)),
        ).let { values ->
            buildList {
                for (index in 0 until values.length()) {
                    add(values.getString(index))
                }
            }
        }
        val wordPhoneticIndex = getColumnIndexOrThrow(COLUMN_WORD_PHONETIC)
        val wordMeaningIndex = getColumnIndexOrThrow(COLUMN_WORD_MEANING)
        val wordExampleIndex = getColumnIndexOrThrow(COLUMN_WORD_EXAMPLE)
        val lastReviewIndex = getColumnIndexOrThrow(COLUMN_LAST_REVIEW_AT)
        val nextReviewIndex = getColumnIndexOrThrow(COLUMN_NEXT_REVIEW_AT)
        val audioMimeTypeIndex = getColumnIndexOrThrow(COLUMN_AUDIO_MIME_TYPE)
        val audioSizeIndex = getColumnIndexOrThrow(COLUMN_AUDIO_SIZE_BYTES)
        val audioDurationIndex = getColumnIndexOrThrow(COLUMN_AUDIO_DURATION_MS)
        val transcriptIndex = getColumnIndexOrThrow(COLUMN_TRANSCRIPT)
        val localAudioPathIndex = getColumnIndexOrThrow(COLUMN_LOCAL_AUDIO_PATH)
        val syncStateName = getString(getColumnIndexOrThrow(COLUMN_SYNC_STATE))
        val collectionsArray = JSONArray(
            getString(getColumnIndexOrThrow(COLUMN_COLLECTIONS)),
        )
        val collections = buildList {
            for (index in 0 until collectionsArray.length()) {
                add(collectionsArray.getString(index))
            }
        }
        return Memo(
            id = if (isNull(remoteIdIndex)) null else getString(remoteIdIndex),
            clientId = getString(getColumnIndexOrThrow(COLUMN_CLIENT_ID)),
            type = getString(getColumnIndexOrThrow(COLUMN_TYPE)),
            title = getString(getColumnIndexOrThrow(COLUMN_TITLE)),
            body = getString(getColumnIndexOrThrow(COLUMN_BODY)),
            sourceUrl = if (isNull(sourceUrlIndex)) null else getString(sourceUrlIndex),
            sourceTitle = if (isNull(sourceTitleIndex)) null else getString(sourceTitleIndex),
            resourceDescription = if (isNull(resourceDescriptionIndex)) {
                null
            } else {
                getString(resourceDescriptionIndex)
            },
            resourceSiteName = if (isNull(resourceSiteNameIndex)) {
                null
            } else {
                getString(resourceSiteNameIndex)
            },
            resourceImageUrl = if (isNull(resourceImageUrlIndex)) {
                null
            } else {
                getString(resourceImageUrlIndex)
            },
            resourceCategory = if (isNull(resourceCategoryIndex)) {
                null
            } else {
                getString(resourceCategoryIndex)
            },
            resourceKind = if (isNull(resourceKindIndex)) null else getString(resourceKindIndex),
            resourceReadingStatus = if (isNull(resourceReadingStatusIndex)) {
                null
            } else {
                getString(resourceReadingStatusIndex)
            },
            resourceCategoryStatus = getString(
                getColumnIndexOrThrow(COLUMN_RESOURCE_CATEGORY_STATUS),
            ),
            resourceAutoTags = resourceAutoTags,
            resourceImportFolder = if (isNull(resourceImportFolderIndex)) {
                null
            } else {
                getString(resourceImportFolderIndex)
            },
            linkHealthStatus = getString(getColumnIndexOrThrow(COLUMN_LINK_HEALTH_STATUS)),
            linkHealthHttpStatus = if (isNull(linkHealthHttpStatusIndex)) {
                null
            } else {
                getInt(linkHealthHttpStatusIndex)
            },
            linkHealthError = if (isNull(linkHealthErrorIndex)) {
                null
            } else {
                getString(linkHealthErrorIndex)
            },
            linkLastCheckedAt = if (isNull(linkLastCheckedIndex)) {
                null
            } else {
                getString(linkLastCheckedIndex)
            },
            linkLastSuccessAt = if (isNull(linkLastSuccessIndex)) {
                null
            } else {
                getString(linkLastSuccessIndex)
            },
            linkEffectiveUrl = if (isNull(linkEffectiveUrlIndex)) {
                null
            } else {
                getString(linkEffectiveUrlIndex)
            },
            wordPhonetic = if (isNull(wordPhoneticIndex)) null else getString(wordPhoneticIndex),
            wordMeaning = if (isNull(wordMeaningIndex)) null else getString(wordMeaningIndex),
            wordExample = if (isNull(wordExampleIndex)) null else getString(wordExampleIndex),
            familiarity = getInt(getColumnIndexOrThrow(COLUMN_FAMILIARITY)),
            reviewCount = getInt(getColumnIndexOrThrow(COLUMN_REVIEW_COUNT)),
            lastReviewAt = if (isNull(lastReviewIndex)) null else getString(lastReviewIndex),
            nextReviewAt = if (isNull(nextReviewIndex)) null else getString(nextReviewIndex),
            audioMimeType = if (isNull(audioMimeTypeIndex)) null else getString(audioMimeTypeIndex),
            audioSizeBytes = if (isNull(audioSizeIndex)) null else getInt(audioSizeIndex),
            audioDurationMs = if (isNull(audioDurationIndex)) null else getInt(audioDurationIndex),
            transcript = if (isNull(transcriptIndex)) null else getString(transcriptIndex),
            transcriptStatus = getString(getColumnIndexOrThrow(COLUMN_TRANSCRIPT_STATUS)),
            localAudioPath = if (isNull(localAudioPathIndex)) {
                null
            } else {
                getString(localAudioPathIndex)
            },
            tags = tags,
            collections = collections,
            starred = getInt(getColumnIndexOrThrow(COLUMN_STARRED)) != 0,
            status = getString(getColumnIndexOrThrow(COLUMN_STATUS)),
            version = getInt(getColumnIndexOrThrow(COLUMN_VERSION)),
            createdAt = getString(getColumnIndexOrThrow(COLUMN_CREATED_AT)),
            updatedAt = getString(getColumnIndexOrThrow(COLUMN_UPDATED_AT)),
            syncState = runCatching { SyncState.valueOf(syncStateName) }
                .getOrDefault(SyncState.FAILED),
        )
    }

    private companion object {
        const val DATABASE_NAME = "memoisle.db"
        const val DATABASE_VERSION = 7
        const val TABLE_MEMO = "memo"
        const val COLUMN_CLIENT_ID = "client_id"
        const val COLUMN_REMOTE_ID = "remote_id"
        const val COLUMN_TYPE = "type"
        const val COLUMN_TITLE = "title"
        const val COLUMN_BODY = "body"
        const val COLUMN_SOURCE_URL = "source_url"
        const val COLUMN_SOURCE_TITLE = "source_title"
        const val COLUMN_RESOURCE_DESCRIPTION = "resource_description"
        const val COLUMN_RESOURCE_SITE_NAME = "resource_site_name"
        const val COLUMN_RESOURCE_IMAGE_URL = "resource_image_url"
        const val COLUMN_RESOURCE_CATEGORY = "resource_category"
        const val COLUMN_RESOURCE_KIND = "resource_kind"
        const val COLUMN_RESOURCE_READING_STATUS = "resource_reading_status"
        const val COLUMN_RESOURCE_CATEGORY_STATUS = "resource_category_status"
        const val COLUMN_RESOURCE_AUTO_TAGS = "resource_auto_tags_json"
        const val COLUMN_RESOURCE_IMPORT_FOLDER = "resource_import_folder"
        const val COLUMN_LINK_HEALTH_STATUS = "link_health_status"
        const val COLUMN_LINK_HEALTH_HTTP_STATUS = "link_health_http_status"
        const val COLUMN_LINK_HEALTH_ERROR = "link_health_error"
        const val COLUMN_LINK_LAST_CHECKED_AT = "link_last_checked_at"
        const val COLUMN_LINK_LAST_SUCCESS_AT = "link_last_success_at"
        const val COLUMN_LINK_EFFECTIVE_URL = "link_effective_url"
        const val COLUMN_WORD_PHONETIC = "word_phonetic"
        const val COLUMN_WORD_MEANING = "word_meaning"
        const val COLUMN_WORD_EXAMPLE = "word_example"
        const val COLUMN_FAMILIARITY = "familiarity"
        const val COLUMN_REVIEW_COUNT = "review_count"
        const val COLUMN_LAST_REVIEW_AT = "last_review_at"
        const val COLUMN_NEXT_REVIEW_AT = "next_review_at"
        const val COLUMN_AUDIO_MIME_TYPE = "audio_mime_type"
        const val COLUMN_AUDIO_SIZE_BYTES = "audio_size_bytes"
        const val COLUMN_AUDIO_DURATION_MS = "audio_duration_ms"
        const val COLUMN_TRANSCRIPT = "transcript"
        const val COLUMN_TRANSCRIPT_STATUS = "transcript_status"
        const val COLUMN_LOCAL_AUDIO_PATH = "local_audio_path"
        const val COLUMN_TAGS = "tags_json"
        const val COLUMN_COLLECTIONS = "collections_json"
        const val COLUMN_STARRED = "starred"
        const val COLUMN_STATUS = "status"
        const val COLUMN_VERSION = "version"
        const val COLUMN_CREATED_AT = "created_at"
        const val COLUMN_UPDATED_AT = "updated_at"
        const val COLUMN_SYNC_STATE = "sync_state"
        val ALL_COLUMNS = arrayOf(
            COLUMN_CLIENT_ID,
            COLUMN_REMOTE_ID,
            COLUMN_TYPE,
            COLUMN_TITLE,
            COLUMN_BODY,
            COLUMN_SOURCE_URL,
            COLUMN_SOURCE_TITLE,
            COLUMN_RESOURCE_DESCRIPTION,
            COLUMN_RESOURCE_SITE_NAME,
            COLUMN_RESOURCE_IMAGE_URL,
            COLUMN_RESOURCE_CATEGORY,
            COLUMN_RESOURCE_KIND,
            COLUMN_RESOURCE_READING_STATUS,
            COLUMN_RESOURCE_CATEGORY_STATUS,
            COLUMN_RESOURCE_AUTO_TAGS,
            COLUMN_RESOURCE_IMPORT_FOLDER,
            COLUMN_LINK_HEALTH_STATUS,
            COLUMN_LINK_HEALTH_HTTP_STATUS,
            COLUMN_LINK_HEALTH_ERROR,
            COLUMN_LINK_LAST_CHECKED_AT,
            COLUMN_LINK_LAST_SUCCESS_AT,
            COLUMN_LINK_EFFECTIVE_URL,
            COLUMN_WORD_PHONETIC,
            COLUMN_WORD_MEANING,
            COLUMN_WORD_EXAMPLE,
            COLUMN_FAMILIARITY,
            COLUMN_REVIEW_COUNT,
            COLUMN_LAST_REVIEW_AT,
            COLUMN_NEXT_REVIEW_AT,
            COLUMN_AUDIO_MIME_TYPE,
            COLUMN_AUDIO_SIZE_BYTES,
            COLUMN_AUDIO_DURATION_MS,
            COLUMN_TRANSCRIPT,
            COLUMN_TRANSCRIPT_STATUS,
            COLUMN_LOCAL_AUDIO_PATH,
            COLUMN_TAGS,
            COLUMN_COLLECTIONS,
            COLUMN_STARRED,
            COLUMN_STATUS,
            COLUMN_VERSION,
            COLUMN_CREATED_AT,
            COLUMN_UPDATED_AT,
            COLUMN_SYNC_STATE,
        )
    }
}
