package com.memoisle.app.data

import com.memoisle.app.network.MemoApiClient
import java.nio.file.Paths
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

class MemoRepository(
    private val database: MemoDatabaseHelper,
    private val api: MemoApiClient,
) {
    private val mutableMemos = MutableStateFlow(database.loadMemos())
    val memos: StateFlow<List<Memo>> = mutableMemos.asStateFlow()

    suspend fun refresh() {
        withContext(Dispatchers.IO) {
            // 先上传本地失败或等待中的内容，再拉取服务端最新版本。
            syncPendingInternal()
            api.listMemos().forEach(database::upsert)
            // 单独拉取回收站墓碑，让 Web 删除能从 Android 可见列表消失。
            api.listMemos(status = "trashed").forEach(database::upsert)
            publishLocalSnapshot()
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
                throw error
            }
        }
    }

    suspend fun createWord(
        lemma: String,
        phonetic: String,
        meaning: String,
        example: String,
    ) {
        withContext(Dispatchers.IO) {
            val localMemo = newLocalWord(lemma, phonetic, meaning, example)
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
                throw error
            }
        }
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
                database.updateSyncState(pendingMemo.clientId, SyncState.FAILED)
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

    fun audioUrl(memoId: String): String = api.audioUrl(memoId)

    private fun syncPendingInternal() {
        database.loadPending().forEach { memo ->
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
                if (isCreate) {
                    database.reconcileCreatedMemo(memo.clientId, reconciledMemo)
                } else {
                    database.upsert(reconciledMemo)
                }
            }.onFailure {
                database.updateSyncState(memo.clientId, SyncState.FAILED)
            }
        }
    }

    private fun publishLocalSnapshot() {
        mutableMemos.value = database.loadMemos()
    }
}
