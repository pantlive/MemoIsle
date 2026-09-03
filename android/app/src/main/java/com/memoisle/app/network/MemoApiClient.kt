package com.memoisle.app.network

import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_WORD
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import org.json.JSONArray
import org.json.JSONObject

class DuplicateLemmaException(
    val existing: Memo,
) : RuntimeException("已收藏相同词形")

class ApiException(
    val statusCode: Int,
    responseBody: String,
) : RuntimeException("API 请求失败（$statusCode）：$responseBody") {
    val code: String?
    val current: Memo?

    init {
        val detail = runCatching { JSONObject(responseBody).optJSONObject("detail") }.getOrNull()
        code = detail?.optString("code")?.takeIf { it.isNotBlank() }
        current = runCatching { detail?.optJSONObject("current")?.toMemo() }.getOrNull()
    }
}

data class AuthProviderInfo(
    val provider: String,
    val label: String,
    val enabled: Boolean,
)

data class AuthProvidersResponse(
    val providers: List<AuthProviderInfo>,
    val devLoginAvailable: Boolean,
    val emailLoginEnabled: Boolean,
)

data class AuthUser(
    val id: String,
    val email: String?,
    val displayName: String,
)

data class AuthSession(
    val accessToken: String,
    val user: AuthUser,
)

class MemoApiClient(baseUrl: String) {
    private val normalizedBaseUrl = baseUrl.trimEnd('/') + "/"
    var accessToken: String? = null

    fun authorizationUrl(provider: String, redirectTo: String): String {
        val encodedRedirect = URLEncoder.encode(redirectTo, Charsets.UTF_8.name())
        return normalizedBaseUrl + "auth/$provider/authorize?redirect_to=$encodedRedirect"
    }

    fun getAuthProviders(): AuthProvidersResponse {
        val response = execute("GET", "auth/providers")
        val providerArray = response.getJSONArray("providers")
        val providers = buildList {
            for (index in 0 until providerArray.length()) {
                val item = providerArray.getJSONObject(index)
                add(
                    AuthProviderInfo(
                        provider = item.getString("provider"),
                        label = item.getString("label"),
                        enabled = item.getBoolean("enabled"),
                    ),
                )
            }
        }
        return AuthProvidersResponse(
            providers = providers,
            devLoginAvailable = response.getBoolean("dev_login_available"),
            emailLoginEnabled = response.optBoolean("email_login_enabled", true),
        )
    }

    fun getCurrentUser(): AuthUser = execute("GET", "auth/me").toAuthUser()

    fun devLogin(): AuthSession {
        val response = execute("POST", "auth/dev-login")
        accessToken = response.getString("access_token")
        return AuthSession(
            accessToken = response.getString("access_token"),
            user = response.getJSONObject("user").toAuthUser(),
        )
    }

    fun loginWithEmail(email: String, password: String): AuthSession {
        val body = JSONObject().apply {
            put("email", email)
            put("password", password)
        }
        return emailSession(execute("POST", "auth/login", body))
    }

    fun registerWithEmail(
        email: String,
        password: String,
        confirmPassword: String,
        displayName: String?,
    ): AuthSession {
        val body = JSONObject().apply {
            put("email", email)
            put("password", password)
            put("confirm_password", confirmPassword)
            displayName?.takeIf { it.isNotBlank() }?.let { put("display_name", it) }
        }
        return emailSession(execute("POST", "auth/register", body))
    }

    fun logout(): Boolean = execute("POST", "auth/logout").getBoolean("revoked")

    private fun emailSession(response: JSONObject): AuthSession {
        accessToken = response.getString("access_token")
        return AuthSession(
            accessToken = response.getString("access_token"),
            user = response.getJSONObject("user").toAuthUser(),
        )
    }

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

    fun createMemo(memo: Memo, allowDuplicate: Boolean = false): Memo {
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
            if (allowDuplicate && memo.type == TYPE_WORD) {
                put("allow_duplicate", true)
            }
            put("tags", JSONArray(memo.tags))
            put("collections", JSONArray(memo.collections))
            memo.resourceKind?.let { put("resource_kind", it) }
            memo.resourceReadingStatus?.let { put("resource_reading_status", it) }
            put("starred", memo.starred)
        }
        return execute("POST", "memos", body).toMemo()
    }

    fun mergeWord(memo: Memo, incoming: Memo): Memo {
        val remoteId = requireNotNull(memo.id) { "合并前必须先完成单词同步" }
        val body = JSONObject().apply {
            put("expected_version", memo.version)
            incoming.wordPhonetic?.let { put("word_phonetic", it) }
            incoming.wordMeaning?.let { put("word_meaning", it) }
            incoming.wordExample?.let { put("word_example", it) }
            incoming.sourceUrl?.let { put("source_url", it) }
            incoming.sourceTitle?.let { put("source_title", it) }
        }
        return execute("POST", "words/$remoteId/merge", body).toMemo()
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

    fun skipReview(memo: Memo): Memo {
        val remoteId = requireNotNull(memo.id) { "跳过回顾前必须先完成同步" }
        val body = JSONObject().apply {
            put("expected_version", memo.version)
        }
        return execute("POST", "review-queue/$remoteId/skip", body).toMemo()
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
            accessToken?.let { token ->
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
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

    fun downloadAudio(memoId: String, target: Path): Path {
        val connection = URL(normalizedBaseUrl + "memos/$memoId/audio")
            .openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "GET"
            connection.connectTimeout = 10_000
            connection.readTimeout = 30_000
            connection.setRequestProperty("Accept", "*/*")
            accessToken?.let { token ->
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
            val statusCode = connection.responseCode
            if (statusCode !in 200..299) {
                val responseBody = connection.errorStream
                    ?.bufferedReader(Charsets.UTF_8)
                    ?.use { it.readText() }
                    .orEmpty()
                throw ApiException(statusCode, responseBody)
            }
            Files.createDirectories(target.parent)
            connection.inputStream.use { input ->
                Files.copy(input, target, StandardCopyOption.REPLACE_EXISTING)
            }
            target
        } finally {
            connection.disconnect()
        }
    }

    private fun execute(method: String, path: String, body: JSONObject? = null): JSONObject {
        val connection = URL(normalizedBaseUrl + path).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = method
            connection.connectTimeout = 8_000
            connection.readTimeout = 12_000
            connection.setRequestProperty("Accept", "application/json")
            accessToken?.let { token ->
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
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

private fun JSONObject.toAuthUser(): AuthUser {
    return AuthUser(
        id = getString("id"),
        email = if (isNull("email")) null else getString("email"),
        displayName = getString("display_name"),
    )
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
