package com.memoisle.app.data

import com.memoisle.app.network.ApiException
import com.memoisle.app.network.DuplicateLemmaException
import com.memoisle.app.network.MemoApiClient
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

    @Synchronized
    fun activateUser(userId: String): Unit {
        if (activeUserId == userId) {
            return
        }
        // 切换账号时清空本机缓存，避免不同用户的数据混在同一个资料库。
        activeUserId = userId
        database.clearAll()
        mutableMemos.value = emptyList()
    }

    fun activeUserId(): String? = activeUserId

    @Synchronized
    fun clearForLogout(): Unit {
        activeUserId = null
        database.clearAll()
        mutableMemos.value = emptyList()
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
                api.listMemos().forEach { memo ->
                    writeIfActive(expectedUserId) { database.upsert(memo) }
                }
                // 单独拉取回收站墓碑，让 Web 删除能从 Android 可见列表消失。
                api.listMemos(status = "trashed").forEach { memo ->
                    writeIfActive(expectedUserId) { database.upsert(memo) }
                }
                if (!isActiveFor(expectedUserId)) {
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

    suspend fun createIdea(body: String) {
        withContext(Dispatchers.IO) {
            val localMemo = newLocalIdea(body)
            database.upsert(localMemo)
            publishLocalSnapshot()
            try {
                database.reconcileCreatedMemo(
                    localMemo.clientId,
                    api.createMemo(localMemo),
                )
                publishLocalSnapshot()
            } catch (error: Exception) {
                database.updateSyncState(localMemo.clientId, SyncState.FAILED)
                publishLocalSnapshot()
                requestBackgroundSync()
                throw error
            }
        }
    }

    suspend fun createSharedResource(url: String, title: String, note: String) {
        withContext(Dispatchers.IO) {
            val localMemo = newLocalResource(url, title, note)
            database.upsert(localMemo)
            publishLocalSnapshot()
            try {
                database.reconcileCreatedMemo(
                    localMemo.clientId,
                    api.createMemo(localMemo),
                )
                publishLocalSnapshot()
            } catch (error: Exception) {
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

    suspend fun createVoiceIdea(body: String, audioPath: String, durationMs: Int) {
        withContext(Dispatchers.IO) {
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
                    // 冲突时以服务端版本作为新的编辑基线，避免再次用旧版本提交。
                    database.upsert(error.current)
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

    suspend fun archiveIdea(memo: Memo) {
        updateMemo(memo.copy(status = "archived"), memo.title, memo.body)
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
                val reconciledMemo = remoteMemo.copy(localAudioPath = localAudioPath)
                writeIfActive(expectedUserId) {
                    if (isCreate) {
                        database.reconcileCreatedMemo(memo.clientId, reconciledMemo)
                    } else {
                        database.upsert(reconciledMemo)
                    }
                }
            }.onFailure { error ->
                if (writeIfActive(expectedUserId) {
                    database.updateSyncState(memo.clientId, SyncState.FAILED)
                }) {
                    hasRetryableFailure = hasRetryableFailure || isRetryable(error)
                }
            }
        }
        return SyncResult(hasRetryableFailure = hasRetryableFailure)
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
