package com.memoisle.app.network

import com.memoisle.app.data.Memo
import com.memoisle.app.data.MemoDeletion
import com.memoisle.app.data.MemoSyncCursor
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.normalizeImageMimeType
import java.io.OutputStream
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

class DuplicateResourceException(
    val existing: Memo,
) : RuntimeException("已收藏相同网址")

class ApiException(
    val statusCode: Int,
    responseBody: String,
) : RuntimeException("API 请求失败（$statusCode）：$responseBody") {
    val code: String?
    val current: Memo?

    /** 服务端返回的可读错误说明，用于展示图片上传等具体失败原因。 */
    val detailMessage: String?

    init {
        val detail = runCatching { JSONObject(responseBody).opt("detail") }.getOrNull()
        val detailObject = detail as? JSONObject
        code = detailObject?.optString("code")?.takeIf { it.isNotBlank() }
        current = runCatching { detailObject?.optJSONObject("current")?.toMemo() }.getOrNull()
        detailMessage = when (detail) {
            is String -> detail.takeIf { it.isNotBlank() }
            is JSONObject -> detail.optString("message").takeIf { it.isNotBlank() }
            else -> null
        }
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
    val emailVerified: Boolean,
    val displayName: String,
)

data class AuthSession(
    val accessToken: String,
    val user: AuthUser,
)

data class WordLookupSense(
    val index: Int,
    val partOfSpeech: String?,
    val definition: String,
    val example: String?,
)

data class WordLookupResponse(
    val word: String,
    val lemma: String,
    val phonetic: String?,
    val usAudioUrl: String?,
    val ukAudioUrl: String?,
    val senses: List<WordLookupSense>,
)

data class ReviewSettings(
    val dailyLimit: Int,
    val intervalsDays: List<Int>,
)

data class SyncChangesResponse(
    val items: List<Memo>,
    val cursor: MemoSyncCursor,
    val deletedItems: List<MemoDeletion> = emptyList(),
    val hasMore: Boolean? = null,
)

data class QuickAccessEntry(
    val memo: Memo,
    val openCount: Int,
)

data class VaultStatusResponse(
    val configured: Boolean,
    val kdf: String?,
    val kdfIterations: Int?,
    val kdfSalt: String?,
    val wrappedKey: String?,
    val wrapIv: String?,
    val itemCount: Int,
)

data class VaultItemRecord(
    val id: String,
    val iv: String,
    val ciphertext: String,
    val version: Int,
    val createdAt: String,
    val updatedAt: String,
)

data class EmailRegisterResponse(
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

    fun requestVerificationCode(email: String): Unit {
        val body = JSONObject().apply {
            put("email", email)
        }
        execute("POST", "auth/verification-code", body)
    }

    fun requestPasswordReset(email: String): Unit {
        val body = JSONObject().apply {
            put("email", email)
        }
        execute("POST", "auth/password-reset/request", body)
    }

    fun registerWithEmail(
        email: String,
        password: String,
        confirmPassword: String,
        verificationCode: String,
        displayName: String?,
    ): EmailRegisterResponse {
        val body = JSONObject().apply {
            put("email", email)
            put("password", password)
            put("confirm_password", confirmPassword)
            put("verification_code", verificationCode)
            displayName?.takeIf { it.isNotBlank() }?.let { put("display_name", it) }
        }
        val response = execute("POST", "auth/register", body)
        return EmailRegisterResponse(
            user = response.getJSONObject("user").toAuthUser(),
        )
    }

    fun logout(): Boolean = execute("POST", "auth/logout").getBoolean("revoked")

    fun downloadUserData(output: OutputStream): Unit {
        val connection = URL(normalizedBaseUrl + "exports/json")
            .openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "GET"
            connection.connectTimeout = 10_000
            connection.readTimeout = 60_000
            connection.setRequestProperty("Accept", "application/json")
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
            connection.inputStream.use { input -> input.copyTo(output) }
        } finally {
            connection.disconnect()
        }
    }

    private fun emailSession(response: JSONObject): AuthSession {
        accessToken = response.getString("access_token")
        return AuthSession(
            accessToken = response.getString("access_token"),
            user = response.getJSONObject("user").toAuthUser(),
        )
    }

    fun listMemos(status: String? = null): List<Memo> {
        val pageSize = 200
        val items = mutableListOf<Memo>()
        var offset = 0
        while (offset < 10_000) {
            val query = buildString {
                append("memos?limit=$pageSize&offset=$offset")
                if (status != null) {
                    append("&status=$status")
                }
            }
            val response = execute("GET", query)
            val page = response.getJSONArray("items")
            for (index in 0 until page.length()) {
                items.add(page.getJSONObject(index).toMemo())
            }
            if (page.length() < pageSize) {
                break
            }
            offset += pageSize
        }
        return items
    }

    fun syncChanges(
        cursor: MemoSyncCursor? = null,
        limit: Int = 100,
    ): SyncChangesResponse {
        val query = buildString {
            append("sync/changes?limit=$limit")
            cursor?.let { savedCursor ->
                append("&cursor=")
                append(URLEncoder.encode(savedCursor.timestamp, Charsets.UTF_8.name()))
                savedCursor.memoId?.let { memoId ->
                    append("&cursor_id=")
                    append(URLEncoder.encode(memoId, Charsets.UTF_8.name()))
                }
            }
        }
        val response = execute("GET", query)
        val page = response.getJSONArray("items")
        val items = buildList {
            for (index in 0 until page.length()) {
                add(page.getJSONObject(index).toMemo())
            }
        }
        val responseCursorId = if (response.isNull("cursor_id")) {
            null
        } else {
            response.optString("cursor_id").ifBlank { null }
        }
        return SyncChangesResponse(
            items = items,
            deletedItems = buildList {
                val deleted = response.optJSONArray("deleted_items") ?: JSONArray()
                for (index in 0 until deleted.length()) {
                    val item = deleted.getJSONObject(index)
                    add(MemoDeletion(item.getString("memo_id"), item.getString("client_id")))
                }
            },
            hasMore = if (response.has("has_more")) response.getBoolean("has_more") else null,
            cursor = MemoSyncCursor(
                timestamp = response.getString("cursor"),
                // 兼容尚未返回 cursor_id 的旧服务端；新服务端会返回权威值。
                memoId = responseCursorId ?: items.lastOrNull()?.id,
            ),
        )
    }

    fun getMemo(remoteId: String): Memo {
        return execute("GET", "memos/$remoteId").toMemo()
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
            if (allowDuplicate && memo.type in setOf(TYPE_WORD, TYPE_RESOURCE)) {
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

    fun lookupWord(word: String): WordLookupResponse {
        val response = execute(
            "POST",
            "words/lookup",
            JSONObject().put("word", word),
        )
        val sensesArray = response.optJSONArray("senses") ?: JSONArray()
        val senses = buildList {
            for (index in 0 until sensesArray.length()) {
                val item = sensesArray.getJSONObject(index)
                add(
                    WordLookupSense(
                        index = item.getInt("index"),
                        partOfSpeech = if (item.isNull("part_of_speech")) {
                            null
                        } else {
                            item.getString("part_of_speech")
                        },
                        definition = item.getString("definition"),
                        example = if (item.isNull("example")) {
                            null
                        } else {
                            item.getString("example")
                        },
                    ),
                )
            }
        }
        return WordLookupResponse(
            word = response.getString("word"),
            lemma = response.getString("lemma"),
            phonetic = if (response.isNull("phonetic")) null else response.getString("phonetic"),
            usAudioUrl = if (response.isNull("us_audio_url")) {
                null
            } else {
                response.getString("us_audio_url")
            },
            ukAudioUrl = if (response.isNull("uk_audio_url")) {
                null
            } else {
                response.getString("uk_audio_url")
            },
            senses = senses,
        )
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

    fun restoreMemo(memo: Memo): Memo {
        val remoteId = requireNotNull(memo.id) { "恢复前必须先完成同步" }
        return execute(
            "POST",
            "memos/$remoteId/restore?expected_version=${memo.version}",
        ).toMemo()
    }

    fun permanentlyDeleteMemo(memo: Memo) {
        val remoteId = requireNotNull(memo.id) { "永久删除前必须先完成同步" }
        execute(
            "DELETE",
            "memos/$remoteId/permanent?expected_version=${memo.version}",
        )
    }

    fun reviewWord(memo: Memo, feedback: String): Memo {
        val remoteId = requireNotNull(memo.id) { "复习前必须先完成单词同步" }
        val body = JSONObject().apply {
            put("expected_version", memo.version)
            put("feedback", feedback)
        }
        return execute("POST", "words/$remoteId/reviews", body).toMemo()
    }

    fun getReviewSettings(): ReviewSettings {
        return execute("GET", "review-settings").toReviewSettings()
    }

    fun updateReviewSettings(
        dailyLimit: Int,
        intervalsDays: List<Int>,
    ): ReviewSettings {
        val body = JSONObject().apply {
            put("daily_limit", dailyLimit)
            put("intervals_days", JSONArray(intervalsDays))
        }
        return execute("PATCH", "review-settings", body).toReviewSettings()
    }

    fun skipReview(memo: Memo): Memo {
        val remoteId = requireNotNull(memo.id) { "跳过回顾前必须先完成同步" }
        val body = JSONObject().apply {
            put("expected_version", memo.version)
        }
        return execute("POST", "review-queue/$remoteId/skip", body).toMemo()
    }

    fun synthesizeSpeech(text: String, voice: String? = null): ByteArray {
        val body = JSONObject().apply {
            put("text", text)
            voice?.takeIf { it.isNotBlank() }?.let { put("voice", it) }
        }
        val connection = URL(normalizedBaseUrl + "speech/tts")
            .openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 8_000
            connection.readTimeout = 60_000
            connection.doOutput = true
            connection.setRequestProperty("Accept", "audio/wav")
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            accessToken?.let { token ->
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
            connection.outputStream.bufferedWriter(Charsets.UTF_8).use { writer ->
                writer.write(body.toString())
            }
            val statusCode = connection.responseCode
            if (statusCode !in 200..299) {
                val responseBody = connection.errorStream
                    ?.bufferedReader(Charsets.UTF_8)
                    ?.use { it.readText() }
                    .orEmpty()
                throw ApiException(statusCode, responseBody)
            }
            connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
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

    /**
     * 创建图片收藏条目；图片字节随后通过 [uploadMemoImage] 以原始请求体上传。
     */
    fun createImageMemo(memo: Memo): Memo {
        require(memo.type == TYPE_IMAGE) { "创建图片收藏时类型必须为 image" }
        return createMemo(memo)
    }

    /**
     * 上传原始图片字节（非 multipart），成功时返回带图片元数据和递增版本号的条目。
     *
     * 服务端错误：413 图片超过 20 MB、422 格式或版本非法、409 并发版本冲突。
     */
    fun uploadMemoImage(
        memo: Memo,
        bytes: ByteArray,
        mimeType: String,
        expectedVersion: Int,
    ): Memo {
        val remoteId = requireNotNull(memo.id) { "上传图片前必须先创建图片收藏" }
        val normalizedMimeType = normalizeImageMimeType(mimeType)
        require(normalizedMimeType != null) { "仅支持 PNG/JPEG/WebP/GIF 图片" }
        require(bytes.isNotEmpty()) { "图片内容不能为空" }
        val connection = URL(
            normalizedBaseUrl + "memos/$remoteId/image?expected_version=$expectedVersion",
        ).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 10_000
            connection.readTimeout = 60_000
            connection.doOutput = true
            connection.setRequestProperty("Accept", "application/json")
            accessToken?.let { token ->
                connection.setRequestProperty("Authorization", "Bearer $token")
            }
            connection.setRequestProperty("Content-Type", normalizedMimeType)
            connection.setFixedLengthStreamingMode(bytes.size)
            connection.outputStream.use { output -> output.write(bytes) }
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

    /**
     * 读取原图或缩略图字节；两个接口都需要 Bearer 鉴权，不能直接把 URL 交给图片库。
     */
    fun fetchMemoImage(memoId: String, thumbnail: Boolean): ByteArray {
        val path = if (thumbnail) {
            "memos/$memoId/image/thumbnail"
        } else {
            "memos/$memoId/image"
        }
        val connection = URL(normalizedBaseUrl + path).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "GET"
            connection.connectTimeout = 10_000
            connection.readTimeout = 60_000
            connection.setRequestProperty("Accept", "image/*")
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
            connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    fun recordResourceOpen(remoteId: String) {
        execute("POST", "resources/$remoteId/open")
    }

    fun listQuickAccess(limit: Int = 8): List<QuickAccessEntry> {
        val array = JSONArray(executeText("GET", "resources/quick-access?limit=$limit"))
        return buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(QuickAccessEntry(item.toMemo(), item.optInt("resource_open_count", 0)))
            }
        }
    }

    fun setQuickAccessHidden(remoteId: String, hidden: Boolean) {
        execute("PUT", "resources/$remoteId/quick-access", JSONObject().put("hidden", hidden))
    }

    // 密码库接口只收发密文，主密码和库密钥从不出现在请求里。
    fun getVaultStatus(): VaultStatusResponse {
        val response = execute("GET", "vault")
        return VaultStatusResponse(
            configured = response.optBoolean("configured", false),
            kdf = response.optStringOrNull("kdf"),
            kdfIterations = if (response.isNull("kdf_iterations")) null else response.optInt("kdf_iterations"),
            kdfSalt = response.optStringOrNull("kdf_salt"),
            wrappedKey = response.optStringOrNull("wrapped_key"),
            wrapIv = response.optStringOrNull("wrap_iv"),
            itemCount = response.optInt("item_count", 0),
        )
    }

    fun listVaultItems(): List<VaultItemRecord> {
        val array = JSONArray(executeText("GET", "vault/items"))
        return buildList {
            for (index in 0 until array.length()) {
                add(array.getJSONObject(index).toVaultItemRecord())
            }
        }
    }

    fun createVaultItem(id: String, iv: String, ciphertext: String): VaultItemRecord {
        val body = JSONObject().put("id", id).put("iv", iv).put("ciphertext", ciphertext)
        return execute("POST", "vault/items", body).toVaultItemRecord()
    }

    fun updateVaultItem(
        id: String,
        iv: String,
        ciphertext: String,
        expectedVersion: Int,
    ): VaultItemRecord {
        val body = JSONObject()
            .put("iv", iv)
            .put("ciphertext", ciphertext)
            .put("expected_version", expectedVersion)
        return execute("PUT", "vault/items/$id", body).toVaultItemRecord()
    }

    fun deleteVaultItem(id: String, expectedVersion: Int) {
        executeText("DELETE", "vault/items/$id?expected_version=$expectedVersion")
    }

    private fun execute(method: String, path: String, body: JSONObject? = null): JSONObject {
        // 204 等空响应按空对象处理。
        return JSONObject(executeText(method, path, body).ifBlank { "{}" })
    }

    private fun executeText(method: String, path: String, body: JSONObject? = null): String {
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
            responseBody
        } finally {
            connection.disconnect()
        }
    }
}

private fun JSONObject.optStringOrNull(name: String): String? {
    return if (isNull(name)) null else optString(name).ifBlank { null }
}

private fun JSONObject.toVaultItemRecord(): VaultItemRecord {
    return VaultItemRecord(
        id = getString("id"),
        iv = getString("iv"),
        ciphertext = getString("ciphertext"),
        version = getInt("version"),
        createdAt = getString("created_at"),
        updatedAt = getString("updated_at"),
    )
}

private fun JSONObject.toAuthUser(): AuthUser {
    return AuthUser(
        id = getString("id"),
        email = if (isNull("email")) null else getString("email"),
        emailVerified = optBoolean("email_verified", false),
        displayName = getString("display_name"),
    )
}

private fun JSONObject.toReviewSettings(): ReviewSettings {
    val intervalsArray = getJSONArray("intervals_days")
    val intervals = buildList {
        for (index in 0 until intervalsArray.length()) {
            add(intervalsArray.getInt(index))
        }
    }
    return ReviewSettings(
        dailyLimit = getInt("daily_limit"),
        intervalsDays = intervals,
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
    val resourceCategories = optJSONArray("resource_categories").let { values ->
        if (values == null) {
            emptyList()
        } else {
            buildList {
                for (index in 0 until values.length()) {
                    add(values.getString(index))
                }
            }
        }
    }
    val imageAutoTags = optJSONArray("image_auto_tags").let { values ->
        if (values == null) {
            emptyList()
        } else {
            buildList {
                for (index in 0 until values.length()) {
                    add(values.getString(index))
                }
            }
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
        // 旧服务端没有这个字段，isNull 对缺失字段同样返回 true。
        resourceAiSummary = if (isNull("resource_ai_summary")) {
            null
        } else {
            getString("resource_ai_summary").takeIf { it.isNotBlank() }
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
        resourceCategories = resourceCategories,
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
        imageMimeType = if (isNull("image_mime_type")) null else getString("image_mime_type"),
        imageSizeBytes = if (isNull("image_size_bytes")) null else getInt("image_size_bytes"),
        imageWidth = if (isNull("image_width")) null else getInt("image_width"),
        imageHeight = if (isNull("image_height")) null else getInt("image_height"),
        imageHash = if (isNull("image_hash")) null else getString("image_hash"),
        imageOcrText = if (isNull("image_ocr_text")) null else getString("image_ocr_text"),
        imageOcrStatus = if (isNull("image_ocr_status")) {
            "none"
        } else {
            optString("image_ocr_status", "none").ifBlank { "none" }
        },
        imageOcrError = if (isNull("image_ocr_error")) null else getString("image_ocr_error"),
        imageOcrSource = if (isNull("image_ocr_source")) null else getString("image_ocr_source"),
        imageAutoTags = imageAutoTags,
        imageOcrUpdatedAt = if (isNull("image_ocr_updated_at")) {
            null
        } else {
            getString("image_ocr_updated_at")
        },
        tags = tags,
        collections = collections,
        starred = optBoolean("starred", false),
        status = getString("status"),
        version = getInt("version"),
        createdAt = getString("created_at"),
        updatedAt = getString("updated_at"),
        syncState = SyncState.SYNCED,
        deletedAt = if (isNull("deleted_at")) null else optString("deleted_at").ifBlank { null },
    )
}
