package com.memoisle.app.network

import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files
import java.nio.file.Path
import org.json.JSONArray
import org.json.JSONObject

class ApiException(
    val statusCode: Int,
    responseBody: String,
) : RuntimeException("API 请求失败（$statusCode）：$responseBody")

class MemoApiClient(baseUrl: String) {
    private val normalizedBaseUrl = baseUrl.trimEnd('/') + "/"

    fun listMemos(status: String? = null): List<Memo> {
        val query = if (status == null) {
            "memos?limit=200"
        } else {
            "memos?limit=200&status=$status"
        }
        val response = execute("GET", query)
        val items = response.getJSONArray("items")
        return buildList {
            for (index in 0 until items.length()) {
                add(items.getJSONObject(index).toMemo())
            }
        }
    }

    fun createMemo(memo: Memo): Memo {
        val body = JSONObject().apply {
            put("client_id", memo.clientId)
            put("type", memo.type)
            put("title", memo.title)
            put("body", memo.body)
            memo.sourceUrl?.let { put("source_url", it) }
            memo.sourceTitle?.let { put("source_title", it) }
            memo.wordPhonetic?.let { put("word_phonetic", it) }
            memo.wordMeaning?.let { put("word_meaning", it) }
            memo.wordExample?.let { put("word_example", it) }
            put("tags", JSONArray(memo.tags))
            put("collections", JSONArray(memo.collections))
            memo.resourceKind?.let { put("resource_kind", it) }
            memo.resourceReadingStatus?.let { put("resource_reading_status", it) }
            put("starred", memo.starred)
        }
        return execute("POST", "memos", body).toMemo()
    }

    fun updateMemo(memo: Memo): Memo {
        val remoteId = requireNotNull(memo.id) { "同步后的条目必须包含服务端标识" }
        val body = JSONObject().apply {
            put("expected_version", memo.version)
            put("title", memo.title)
            put("body", memo.body)
            memo.sourceUrl?.let { put("source_url", it) }
            memo.sourceTitle?.let { put("source_title", it) }
            memo.wordPhonetic?.let { put("word_phonetic", it) }
            memo.wordMeaning?.let { put("word_meaning", it) }
            memo.wordExample?.let { put("word_example", it) }
            memo.resourceKind?.let { put("resource_kind", it) }
            memo.resourceReadingStatus?.let { put("resource_reading_status", it) }
            put("collections", JSONArray(memo.collections))
            put("starred", memo.starred)
            put("status", memo.status)
        }
        return execute("PATCH", "memos/$remoteId", body).toMemo()
    }

    fun reviewWord(memo: Memo, feedback: String): Memo {
        val remoteId = requireNotNull(memo.id) { "复习前必须先完成单词同步" }
        val body = JSONObject().apply {
            put("expected_version", memo.version)
            put("feedback", feedback)
        }
        return execute("POST", "words/$remoteId/reviews", body).toMemo()
    }

    fun uploadAudio(memo: Memo, audioPath: Path, durationMs: Int): Memo {
        val remoteId = requireNotNull(memo.id) { "上传录音前必须先完成灵感同步" }
        val connection = URL(
            normalizedBaseUrl + "memos/$remoteId/audio?expected_version=${memo.version}",
        ).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 10_000
            connection.readTimeout = 30_000
            connection.doOutput = true
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Content-Type", "audio/mp4")
            connection.setRequestProperty("X-Audio-Duration-Ms", durationMs.toString())
            val audioSize = Files.size(audioPath)
            require(audioSize <= Int.MAX_VALUE) { "录音文件过大" }
            connection.setFixedLengthStreamingMode(audioSize.toInt())
            connection.outputStream.use { output ->
                Files.newInputStream(audioPath).use { input -> input.copyTo(output) }
            }
            val statusCode = connection.responseCode
            val stream = if (statusCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }
            val responseBody = stream?.bufferedReader(Charsets.UTF_8)
                ?.use { it.readText() }
                .orEmpty()
            if (statusCode !in 200..299) {
                throw ApiException(statusCode, responseBody)
            }
            JSONObject(responseBody).toMemo()
        } finally {
            connection.disconnect()
        }
    }

    fun audioUrl(memoId: String): String = normalizedBaseUrl + "memos/$memoId/audio"

    private fun execute(method: String, path: String, body: JSONObject? = null): JSONObject {
        val connection = URL(normalizedBaseUrl + path).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = method
            connection.connectTimeout = 8_000
            connection.readTimeout = 12_000
            connection.setRequestProperty("Accept", "application/json")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.bufferedWriter(Charsets.UTF_8).use { writer ->
                    writer.write(body.toString())
                }
            }

            val statusCode = connection.responseCode
            val stream = if (statusCode in 200..299) {
                connection.inputStream
            } else {
                connection.errorStream
            }
            val responseBody = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (statusCode !in 200..299) {
                throw ApiException(statusCode, responseBody)
            }
            JSONObject(responseBody)
        } finally {
            connection.disconnect()
        }
    }
}

private fun JSONObject.toMemo(): Memo {
    val tagsArray = getJSONArray("tags")
    val tags = buildList {
        for (index in 0 until tagsArray.length()) {
            add(tagsArray.getString(index))
        }
    }
    val autoTagsArray = getJSONArray("resource_auto_tags")
    val resourceAutoTags = buildList {
        for (index in 0 until autoTagsArray.length()) {
            add(autoTagsArray.getString(index))
        }
    }
    val collectionsArray = getJSONArray("collections")
    val collections = buildList {
        for (index in 0 until collectionsArray.length()) {
            add(collectionsArray.getString(index))
        }
    }
    return Memo(
        id = getString("id"),
        clientId = getString("client_id"),
        type = getString("type"),
        title = getString("title"),
        body = getString("body"),
        sourceUrl = if (isNull("source_url")) null else getString("source_url"),
        sourceTitle = if (isNull("source_title")) null else getString("source_title"),
        resourceDescription = if (isNull("resource_description")) {
            null
        } else {
            getString("resource_description")
        },
        resourceSiteName = if (isNull("resource_site_name")) {
            null
        } else {
            getString("resource_site_name")
        },
        resourceImageUrl = if (isNull("resource_image_url")) {
            null
        } else {
            getString("resource_image_url")
        },
        resourceCategory = if (isNull("resource_category")) {
            null
        } else {
            getString("resource_category")
        },
        resourceCategoryLabel = if (isNull("resource_category_label")) {
            null
        } else {
            getString("resource_category_label")
        },
        resourceKind = if (isNull("resource_kind")) null else getString("resource_kind"),
        resourceReadingStatus = if (isNull("resource_reading_status")) {
            null
        } else {
            getString("resource_reading_status")
        },
        resourceCategoryStatus = getString("resource_category_status"),
        resourceAutoTags = resourceAutoTags,
        resourceImportFolder = if (isNull("resource_import_folder")) {
            null
        } else {
            getString("resource_import_folder")
        },
        linkHealthStatus = getString("link_health_status"),
        linkHealthHttpStatus = if (isNull("link_health_http_status")) {
            null
        } else {
            getInt("link_health_http_status")
        },
        linkHealthError = if (isNull("link_health_error")) {
            null
        } else {
            getString("link_health_error")
        },
        linkLastCheckedAt = if (isNull("link_last_checked_at")) {
            null
        } else {
            getString("link_last_checked_at")
        },
        linkLastSuccessAt = if (isNull("link_last_success_at")) {
            null
        } else {
            getString("link_last_success_at")
        },
        linkEffectiveUrl = if (isNull("link_effective_url")) {
            null
        } else {
            getString("link_effective_url")
        },
        wordPhonetic = if (isNull("word_phonetic")) null else getString("word_phonetic"),
        wordMeaning = if (isNull("word_meaning")) null else getString("word_meaning"),
        wordExample = if (isNull("word_example")) null else getString("word_example"),
        familiarity = getInt("familiarity"),
        reviewCount = getInt("review_count"),
        lastReviewAt = if (isNull("last_review_at")) null else getString("last_review_at"),
        nextReviewAt = if (isNull("next_review_at")) null else getString("next_review_at"),
        audioMimeType = if (isNull("audio_mime_type")) null else getString("audio_mime_type"),
        audioSizeBytes = if (isNull("audio_size_bytes")) null else getInt("audio_size_bytes"),
        audioDurationMs = if (isNull("audio_duration_ms")) null else getInt("audio_duration_ms"),
        transcript = if (isNull("transcript")) null else getString("transcript"),
        transcriptStatus = getString("transcript_status"),
        localAudioPath = null,
        tags = tags,
        collections = collections,
        starred = optBoolean("starred", false),
        status = getString("status"),
        version = getInt("version"),
        createdAt = getString("created_at"),
        updatedAt = getString("updated_at"),
        syncState = SyncState.SYNCED,
    )
}
