package com.memoisle.app.data

import com.memoisle.app.network.ApiException
import com.memoisle.app.network.DuplicateLemmaException
import com.memoisle.app.network.DuplicateResourceException
import com.memoisle.app.network.MemoApiClient
import com.memoisle.app.network.QuickAccessEntry
import com.memoisle.app.network.ReviewSettings
import com.memoisle.app.network.WordLookupResponse
import java.io.OutputStream
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

data class SyncResult(
    val hasRetryableFailure: Boolean = false,
    val wasCancelledForUserSwitch: Boolean = false,
)

private const val SYNC_PAGE_SIZE = 100

class MemoRepository(
    private val database: MemoDatabaseHelper,
    private val api: MemoApiClient,
    private val cacheDirectory: Path,
    initialActiveUserId: String? = null,
    private val onSyncNeeded: () -> Unit = {},
) {
    private val mutableMemos = MutableStateFlow(database.loadMemos())
    val memos: StateFlow<List<Memo>> = mutableMemos.asStateFlow()
    @Volatile
    private var activeUserId: String? = initialActiveUserId
    private val syncMutex = Mutex()
    // 图片字节按需拉取：内存缓存保证滚动列表不重复请求，原图同时落到应用缓存目录。
    private val imageCacheLock = Any()
    private val imageBytesCache = mutableMapOf<String, ByteArray>()

    @Synchronized
    fun activateUser(userId: String): Unit {
        if (activeUserId == userId) {
            return
        }
        // 切换账号时清空本机缓存，避免不同用户的数据混在同一个资料库。
        activeUserId = userId
        clearImageCache()
        database.clearAll()
        mutableMemos.value = emptyList()
    }

    fun activeUserId(): String? = activeUserId

    // 快速访问只在线读取，不进本地缓存：打开次数由服务器统一累计。
    fun recordResourceOpen(remoteId: String) = api.recordResourceOpen(remoteId)

    fun listQuickAccess(limit: Int = 8): List<QuickAccessEntry> = api.listQuickAccess(limit)

    fun setQuickAccessHidden(remoteId: String, hidden: Boolean) = api.setQuickAccessHidden(remoteId, hidden)

    @Synchronized
    fun clearForLogout(): Unit {
        activeUserId = null
        clearImageCache()
        database.clearAll()
        mutableMemos.value = emptyList()
    }

    fun unsyncedCount(): Int {
        return database.loadMemos().count { memo -> memo.syncState != SyncState.SYNCED }
    }

    fun exportUserData(output: OutputStream): Unit {
        // 导出由系统文件选择器提供输出流，网络内容不落到应用缓存目录。
        api.downloadUserData(output)
    }

    fun resolveConflictWithServer(memo: Memo): Unit {
        database.upsert(memo.copy(syncState = SyncState.SYNCED))
        publishLocalSnapshot()
    }

    suspend fun loadConflictServer(memo: Memo): Memo {
        return withContext(Dispatchers.IO) {
            api.getMemo(requireNotNull(memo.id) { "冲突条目必须包含服务端标识" })
        }
    }

    suspend fun refresh(expectedUserId: String? = null): SyncResult {
        return withContext(Dispatchers.IO) {
            syncMutex.withLock {
                if (!isActiveFor(expectedUserId)) {
                    return@withLock SyncResult(wasCancelledForUserSwitch = true)
                }
                // 先上传本地失败或等待中的内容，再拉取服务端最新版本。
                val pendingResult = syncPendingInternal(expectedUserId)
                if (!isActiveFor(expectedUserId)) {
                    return@withLock SyncResult(
                        hasRetryableFailure = pendingResult.hasRetryableFailure,
                        wasCancelledForUserSwitch = true,
                    )
                }
                if (!pullRemoteChanges(expectedUserId)) {
                    return@withLock SyncResult(
                        hasRetryableFailure = pendingResult.hasRetryableFailure,
                        wasCancelledForUserSwitch = true,
                    )
                }
                publishLocalSnapshot()
                pendingResult
            }
        }
    }

    private fun pullRemoteChanges(expectedUserId: String?): Boolean {
        // 没有游标时通过增量接口完整遍历一次，建立后续刷新使用的本地游标。
        val initialCursor = database.loadSyncCursor()
        var cursor = initialCursor
        val remoteIds = if (initialCursor == null) mutableSetOf<String>() else null
        var hasMore: Boolean
        do {
            if (!isActiveFor(expectedUserId)) {
                return false
            }
            val response = api.syncChanges(cursor = cursor, limit = SYNC_PAGE_SIZE)
            response.items.forEach { memo ->
                memo.id?.let { remoteIds?.add(it) }
                writeIfActive(expectedUserId) { database.upsertRemote(memo) }
            }
            response.deletedItems.forEach { deletion ->
                database.loadMemos().filter { it.matchesDeletion(deletion) }.forEach { memo ->
                    writeIfActive(expectedUserId) { removeLocalMemo(memo) }
                }
            }
            cursor = response.cursor
            hasMore = response.hasMore ?: (response.items.size + response.deletedItems.size == SYNC_PAGE_SIZE)
        } while (hasMore)

        if (!isActiveFor(expectedUserId)) {
            return false
        }
        if (remoteIds != null) {
            // 仅清理已经同步过的远端条目，避免误删离线新建或失败待重试内容。
            database.loadMemos()
                .filter { memo -> memo.syncState == SyncState.SYNCED }
                .missingFromRemote(remoteIds)
                .forEach { memo ->
                    writeIfActive(expectedUserId) { removeLocalMemo(memo) }
                }
        }
        return writeIfActive(expectedUserId) { database.saveSyncCursor(requireNotNull(cursor)) }
    }

    suspend fun createIdea(body: String): Memo {
        return withContext(Dispatchers.IO) {
            val localMemo = newLocalIdea(body)
            database.upsert(localMemo)
            publishLocalSnapshot()
            try {
                val created = api.createMemo(localMemo)
                database.reconcileCreatedMemo(
                    localMemo.clientId,
                    created,
                )
                publishLocalSnapshot()
                created
            } catch (error: Exception) {
                database.updateSyncState(localMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    suspend fun createSharedResource(
        url: String,
        title: String,
        note: String,
        allowDuplicate: Boolean = false,
    ): Memo {
        return withContext(Dispatchers.IO) {
            val localMemo = newLocalResource(url, title, note)
            database.upsert(localMemo)
            publishLocalSnapshot()
            try {
                val created = api.createMemo(
                    localMemo,
                    allowDuplicate = allowDuplicate,
                )
                database.reconcileCreatedMemo(
                    localMemo.clientId,
                    created,
                )
                publishLocalSnapshot()
                created
            } catch (error: Exception) {
                if (error is ApiException &&
                    error.statusCode == 409 &&
                    error.code == "duplicate_resource" &&
                    error.current != null
                ) {
                    database.deleteByClientId(localMemo.clientId)
                    database.upsert(error.current)
                    publishLocalSnapshot()
                    throw DuplicateResourceException(error.current)
                }
                database.updateSyncState(localMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    suspend fun createWord(
        lemma: String,
        phonetic: String,
        meaning: String,
        example: String,
        sourceUrl: String? = null,
        allowDuplicate: Boolean = false,
    ): Memo {
        return withContext(Dispatchers.IO) {
            val localMemo = newLocalWord(lemma, phonetic, meaning, example)
                .copy(sourceUrl = sourceUrl)
            val duplicate = memos.value.findDuplicateWord(lemma, localMemo.clientId)
            if (duplicate != null && !allowDuplicate) {
                throw DuplicateLemmaException(duplicate)
            }
            database.upsert(localMemo)
            publishLocalSnapshot()
            try {
                val created = api.createMemo(localMemo, allowDuplicate = allowDuplicate)
                database.reconcileCreatedMemo(localMemo.clientId, created)
                publishLocalSnapshot()
                created
            } catch (error: ApiException) {
                if (error.statusCode == 409 && error.code == "duplicate_lemma" && error.current != null) {
                    database.deleteByClientId(localMemo.clientId)
                    database.upsert(error.current)
                    publishLocalSnapshot()
                    throw DuplicateLemmaException(error.current)
                }
                database.updateSyncState(localMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            } catch (error: Exception) {
                database.updateSyncState(localMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    suspend fun lookupWord(word: String): WordLookupResponse {
        return withContext(Dispatchers.IO) {
            api.lookupWord(word)
        }
    }

    suspend fun getReviewSettings(): ReviewSettings {
        return withContext(Dispatchers.IO) {
            api.getReviewSettings()
        }
    }

    suspend fun updateReviewSettings(
        dailyLimit: Int,
        intervalsDays: List<Int>,
    ): ReviewSettings {
        return withContext(Dispatchers.IO) {
            api.updateReviewSettings(dailyLimit, intervalsDays)
        }
    }

    suspend fun mergeWord(existing: Memo, incoming: Memo): Memo {
        return withContext(Dispatchers.IO) {
            val merged = if (existing.id != null) {
                api.mergeWord(existing, incoming)
            } else {
                existing.copy(
                    wordPhonetic = existing.wordPhonetic ?: incoming.wordPhonetic,
                    wordMeaning = listOfNotNull(existing.wordMeaning, incoming.wordMeaning)
                        .distinct()
                        .joinToString("\n"),
                    wordExample = listOfNotNull(existing.wordExample, incoming.wordExample)
                        .distinct()
                        .joinToString("\n"),
                    sourceUrl = existing.sourceUrl ?: incoming.sourceUrl,
                    updatedAt = Instant.now().toString(),
                    syncState = SyncState.PENDING,
                )
            }
            database.upsert(merged)
            publishLocalSnapshot()
            if (existing.id == null) {
                requestBackgroundSync()
            }
            merged
        }
    }

    suspend fun trashMemo(memo: Memo) {
        updateMemo(memo.copy(status = "trashed"), memo.title, memo.body.ifBlank { memo.title })
    }

    suspend fun restoreMemo(memo: Memo) {
        withContext(Dispatchers.IO) {
            try {
                val restored = api.restoreMemo(memo).copy(
                    localAudioPath = memo.localAudioPath,
                    syncState = SyncState.SYNCED,
                )
                database.upsert(restored)
            } catch (error: ApiException) {
                if (error.statusCode != 404) {
                    throw error
                }
                database.deleteByClientId(memo.clientId)
                memo.localAudioPath?.let { path ->
                    runCatching { java.io.File(path).delete() }
                }
                deleteCachedImages(memo)
            }
            publishLocalSnapshot()
        }
    }

    suspend fun permanentlyDeleteMemo(memo: Memo) {
        withContext(Dispatchers.IO) {
            try {
                api.permanentlyDeleteMemo(memo)
            } catch (error: ApiException) {
                if (error.statusCode != 404) {
                    throw error
                }
            }
            database.deleteByClientId(memo.clientId)
            memo.localAudioPath?.let { path ->
                runCatching { java.io.File(path).delete() }
            }
            deleteCachedImages(memo)
            publishLocalSnapshot()
        }
    }

    suspend fun createVoiceIdea(body: String, audioPath: String, durationMs: Int): Memo {
        return withContext(Dispatchers.IO) {
            val localMemo = newLocalVoiceIdea(body, audioPath, durationMs)
            database.upsert(localMemo)
            publishLocalSnapshot()
            var latestMemo = localMemo
            try {
                val created = api.createMemo(localMemo)
                latestMemo = created.copy(
                    audioMimeType = localMemo.audioMimeType,
                    audioDurationMs = localMemo.audioDurationMs,
                    transcript = localMemo.transcript,
                    transcriptStatus = localMemo.transcriptStatus,
                    localAudioPath = audioPath,
                    syncState = SyncState.PENDING,
                )
                database.reconcileCreatedMemo(localMemo.clientId, latestMemo)
                val uploaded = api.uploadAudio(
                    created,
                    Paths.get(audioPath),
                    durationMs,
                ).copy(localAudioPath = audioPath)
                database.upsert(uploaded)
                publishLocalSnapshot()
                uploaded
            } catch (error: Exception) {
                database.upsert(latestMemo.copy(syncState = SyncState.FAILED))
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    suspend fun updateMemo(memo: Memo, title: String, body: String) {
        withContext(Dispatchers.IO) {
            val pendingMemo = memo.copy(
                title = title.trim(),
                body = body.trim(),
                updatedAt = Instant.now().toString(),
                syncState = SyncState.PENDING,
            )
            database.upsert(pendingMemo)
            publishLocalSnapshot()
            try {
                database.upsert(api.updateMemo(pendingMemo))
                publishLocalSnapshot()
            } catch (error: Exception) {
                if (error is ApiException && error.statusCode == 409 && error.current != null) {
                    // 冲突草稿使用服务端版本号作为新基线，但保留本地正文等待用户选择。
                    database.upsert(buildConflictMemo(pendingMemo, error.current))
                } else {
                    database.updateSyncState(pendingMemo.clientId, SyncState.FAILED)
                    requestBackgroundSync()
                }
                publishLocalSnapshot()
                throw error
            }
        }
    }

    suspend fun reviewWord(memo: Memo, feedback: String) {
        withContext(Dispatchers.IO) {
            database.upsert(api.reviewWord(memo, feedback))
            publishLocalSnapshot()
        }
    }

    suspend fun skipReview(memo: Memo) {
        withContext(Dispatchers.IO) {
            if (memo.id != null) {
                database.upsert(api.skipReview(memo))
            } else {
                database.upsert(
                    memo.copy(
                        lastReviewAt = Instant.now().toString(),
                        updatedAt = Instant.now().toString(),
                    ),
                )
            }
            publishLocalSnapshot()
        }
    }

    suspend fun markResourceOpened(memo: Memo) {
        withContext(Dispatchers.IO) {
            val pendingMemo = memo.copy(
                resourceReadingStatus = "reading",
                lastReviewAt = Instant.now().toString(),
                updatedAt = Instant.now().toString(),
                syncState = SyncState.PENDING,
            )
            database.upsert(pendingMemo)
            publishLocalSnapshot()
            try {
                database.upsert(api.updateMemo(pendingMemo))
                publishLocalSnapshot()
            } catch (error: Exception) {
                database.updateSyncState(pendingMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    suspend fun organizeIdea(memo: Memo, title: String, body: String) {
        updateMemo(
            memo.copy(status = "active", lastReviewAt = Instant.now().toString()),
            title,
            body,
        )
    }

    suspend fun archiveMemo(memo: Memo) {
        updateMemo(memo.copy(status = "archived"), memo.title, memo.body)
    }

    suspend fun archiveIdea(memo: Memo) {
        archiveMemo(memo)
    }

    suspend fun toggleStar(memo: Memo) {
        withContext(Dispatchers.IO) {
            val pendingMemo = memo.copy(
                starred = !memo.starred,
                updatedAt = Instant.now().toString(),
                syncState = SyncState.PENDING,
            )
            database.upsert(pendingMemo)
            publishLocalSnapshot()
            try {
                database.upsert(api.updateMemo(pendingMemo))
                publishLocalSnapshot()
            } catch (error: Exception) {
                database.updateSyncState(pendingMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    fun audioFile(memo: Memo): Path {
        memo.localAudioPath
            ?.let(Paths::get)
            ?.takeIf(Files::exists)
            ?.let { return it }
        val memoId = requireNotNull(memo.id) { "播放录音前必须先完成同步" }
        val target = cacheDirectory.resolve("memoisle-$memoId.audio")
        return api.downloadAudio(memoId, target)
    }

    /**
     * 按需读取图片字节：优先内存缓存，其次是应用缓存目录里的本地副本，最后才请求服务端。
     * 缩略图接口不可用时回退到原图，避免旧条目在列表里一直显示占位图。
     */
    suspend fun loadMemoImage(memo: Memo, thumbnail: Boolean): ByteArray {
        return withContext(Dispatchers.IO) {
            val key = imageCacheKey(memo, thumbnail)
            synchronized(imageCacheLock) { imageBytesCache[key] }?.let { return@withContext it }
            val bytes = if (memo.id == null) {
                // 尚未上传的离线草稿直接用本机原图，联网后由后台同步补传。
                val pending = pendingImageFile(memo)
                    ?: throw IllegalStateException("图片收藏尚未同步，暂时无法查看原图")
                Files.readAllBytes(pending)
            } else {
                val cachedFile = imageCacheFile(memo, thumbnail)
                val cached = if (Files.isRegularFile(cachedFile)) {
                    runCatching { Files.readAllBytes(cachedFile) }.getOrNull()
                } else {
                    null
                }
                cached ?: downloadMemoImage(memo, thumbnail)
            }
            synchronized(imageCacheLock) { imageBytesCache[key] = bytes }
            bytes
        }
    }

    /**
     * 从相册选中的图片创建图片收藏：先写入本地缓存，再创建条目并上传原始字节。
     */
    suspend fun createImageMemo(
        title: String,
        body: String,
        bytes: ByteArray,
        mimeType: String,
    ): Memo {
        return withContext(Dispatchers.IO) {
            val localMemo = newLocalImage(title, body, mimeType, bytes.size)
            val pendingFile = pendingImageFileFor(localMemo, mimeType)
            runCatching {
                Files.createDirectories(pendingFile.parent)
                Files.write(pendingFile, bytes)
            }
            synchronized(imageCacheLock) {
                imageBytesCache["${localMemo.clientId}:f"] = bytes
                imageBytesCache["${localMemo.clientId}:t"] = bytes
            }
            database.upsert(localMemo)
            publishLocalSnapshot()
            try {
                val created = api.createImageMemo(localMemo)
                database.reconcileCreatedMemo(localMemo.clientId, created)
                publishLocalSnapshot()
                val uploaded = api.uploadMemoImage(
                    created,
                    bytes,
                    mimeType,
                    created.version,
                )
                database.upsert(uploaded)
                cacheUploadedImage(uploaded, bytes)
                removeFileQuietly(pendingFile)
                publishLocalSnapshot()
                uploaded
            } catch (error: Exception) {
                database.updateSyncState(localMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    private fun cacheUploadedImage(memo: Memo, bytes: ByteArray) {
        val target = imageCacheFile(memo, thumbnail = false)
        runCatching {
            Files.createDirectories(target.parent)
            Files.write(target, bytes)
        }
        synchronized(imageCacheLock) {
            imageBytesCache.remove("${memo.clientId}:f")
            imageBytesCache.remove("${memo.clientId}:t")
            imageBytesCache["${memo.id ?: memo.clientId}:f"] = bytes
            imageBytesCache["${memo.id ?: memo.clientId}:t"] = bytes
        }
    }

    private fun downloadMemoImage(memo: Memo, thumbnail: Boolean): ByteArray {
        val remoteId = requireNotNull(memo.id) { "查看图片前必须先完成同步" }
        val bytes = try {
            api.fetchMemoImage(remoteId, thumbnail)
        } catch (error: ApiException) {
            if (thumbnail && error.statusCode == 404) {
                api.fetchMemoImage(remoteId, thumbnail = false)
            } else {
                throw error
            }
        }
        if (!thumbnail) {
            val target = imageCacheFile(memo, thumbnail = false)
            runCatching {
                Files.createDirectories(target.parent)
                Files.write(target, bytes)
            }
        }
        return bytes
    }

    private fun imageCacheFile(memo: Memo, thumbnail: Boolean): Path {
        val key = memo.id ?: memo.clientId
        val suffix = if (thumbnail) "thumbnail.webp" else "image"
        return cacheDirectory.resolve("memoisle-$key.$suffix")
    }

    private fun imageCacheKey(memo: Memo, thumbnail: Boolean): String {
        val key = memo.id ?: memo.clientId
        return "$key:${if (thumbnail) "t" else "f"}"
    }

    private fun pendingImageFileFor(memo: Memo, mimeType: String): Path {
        val extension = imageFileExtensionForMimeType(mimeType) ?: "image"
        return cacheDirectory.resolve("memoisle-${memo.clientId}.pending.$extension")
    }

    /** 上传失败后保留的原图，客户端重新联网时继续补传。 */
    private fun pendingImageFile(memo: Memo): Path? {
        if (!Files.isDirectory(cacheDirectory)) {
            return null
        }
        val pattern = "memoisle-${memo.clientId}.pending.*"
        return runCatching {
            Files.newDirectoryStream(cacheDirectory, pattern).use { stream ->
                stream.firstOrNull()
            }
        }.getOrNull()
    }

    private fun deleteCachedImages(memo: Memo) {
        val key = memo.id ?: memo.clientId
        synchronized(imageCacheLock) {
            imageBytesCache.remove("$key:f")
            imageBytesCache.remove("$key:t")
            imageBytesCache.remove("${memo.clientId}:f")
            imageBytesCache.remove("${memo.clientId}:t")
        }
        removeFileQuietly(imageCacheFile(memo, thumbnail = false))
        removeFileQuietly(imageCacheFile(memo, thumbnail = true))
        pendingImageFile(memo)?.let(::removeFileQuietly)
    }

    /** 跨设备永久删除同时清理记录、录音、原图、缩略图及上传失败缓存。 */
    private fun removeLocalMemo(memo: Memo) {
        database.deleteByClientId(memo.clientId)
        memo.localAudioPath?.let { removeFileQuietly(Paths.get(it)) }
        deleteCachedImages(memo)
    }

    private fun clearImageCache() {
        synchronized(imageCacheLock) { imageBytesCache.clear() }
    }

    private fun removeFileQuietly(path: Path) {
        runCatching { Files.deleteIfExists(path) }
    }

    private fun syncPendingInternal(expectedUserId: String?): SyncResult {
        var hasRetryableFailure = false
        database.loadPending().forEach { memo ->
            if (!isActiveFor(expectedUserId)) {
                return SyncResult(
                    hasRetryableFailure = hasRetryableFailure,
                    wasCancelledForUserSwitch = true,
                )
            }
            runCatching {
                val isCreate = memo.id == null
                var remoteMemo = if (isCreate) {
                    api.createMemo(memo)
                } else {
                    api.updateMemo(memo)
                }
                val localAudioPath = memo.localAudioPath
                if (localAudioPath != null && remoteMemo.audioMimeType == null) {
                    val durationMs = memo.audioDurationMs ?: 0
                    remoteMemo = api.uploadAudio(
                        remoteMemo,
                        Paths.get(localAudioPath),
                        durationMs,
                    )
                }
                if (remoteMemo.type == TYPE_IMAGE && remoteMemo.imageMimeType == null) {
                    // 图片原图保存在缓存目录，联网后补传，避免离线收藏丢失图片。
                    val pendingImage = pendingImageFile(memo)
                    val imageMimeType = pendingImage?.let {
                        imageMimeTypeFromFileName(it.fileName.toString())
                    }
                    if (pendingImage != null && imageMimeType != null) {
                        remoteMemo = api.uploadMemoImage(
                            remoteMemo,
                            Files.readAllBytes(pendingImage),
                            imageMimeType,
                            remoteMemo.version,
                        )
                        removeFileQuietly(pendingImage)
                    }
                }
                val reconciledMemo = remoteMemo.copy(localAudioPath = localAudioPath)
                writeIfActive(expectedUserId) {
                    if (isCreate) {
                        database.reconcileCreatedMemo(memo.clientId, reconciledMemo)
                    } else {
                        database.upsert(reconciledMemo)
                    }
                }
            }.onFailure { error ->
                if (error is ApiException && (error.statusCode == 410 || (error.statusCode == 404 && memo.id != null))) {
                    // 远端已经删除的记录不能无限重试，也不能用旧标识重新创建。
                    writeIfActive(expectedUserId) { removeLocalMemo(memo) }
                } else if (error is ApiException && error.statusCode == 409 && error.current != null) {
                    writeIfActive(expectedUserId) {
                        // 后台同步遇到冲突时暂停自动覆盖，交给前台展示冲突选择。
                        database.upsert(buildConflictMemo(memo, error.current))
                    }
                } else if (writeIfActive(expectedUserId) {
                    database.updateSyncState(memo.clientId, SyncState.FAILED)
                }) {
                    hasRetryableFailure = hasRetryableFailure || isRetryable(error)
                }
            }
        }
        return SyncResult(hasRetryableFailure = hasRetryableFailure)
    }

    private fun buildConflictMemo(local: Memo, server: Memo): Memo {
        return server.copy(
            title = local.title,
            body = local.body,
            sourceUrl = local.sourceUrl ?: server.sourceUrl,
            sourceTitle = local.sourceTitle ?: server.sourceTitle,
            wordPhonetic = local.wordPhonetic ?: server.wordPhonetic,
            wordMeaning = local.wordMeaning ?: server.wordMeaning,
            wordExample = local.wordExample ?: server.wordExample,
            localAudioPath = local.localAudioPath ?: server.localAudioPath,
            updatedAt = local.updatedAt,
            syncState = SyncState.CONFLICT,
        )
    }

    private fun writeIfActive(expectedUserId: String?, operation: () -> Unit): Boolean {
        return synchronized(this) {
            if (!isActiveFor(expectedUserId)) {
                false
            } else {
                operation()
                true
            }
        }
    }

    private fun isActiveFor(expectedUserId: String?): Boolean {
        return expectedUserId == null || activeUserId == expectedUserId
    }

    private fun isRetryable(error: Throwable): Boolean {
        return when (error) {
            is ApiException -> error.statusCode == 408 ||
                error.statusCode == 429 ||
                error.statusCode >= 500
            else -> true
        }
    }

    private fun requestBackgroundSync(): Unit {
        runCatching { onSyncNeeded() }
    }

    private fun publishLocalSnapshot() {
        mutableMemos.value = database.loadMemos()
    }
}
