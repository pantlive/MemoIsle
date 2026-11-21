package com.memoisle.app

import android.content.ContentResolver
import android.media.MediaPlayer
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.ImageCompressionResult
import com.memoisle.app.data.ImageCompressor
import com.memoisle.app.data.Memo
import com.memoisle.app.data.MemoRepository
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.imageMemoTitleFromFileName
import com.memoisle.app.data.imageMimeTypeFromFileName
import com.memoisle.app.data.normalizeImageMimeType
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.DuplicateLemmaException
import com.memoisle.app.network.DuplicateResourceException
import com.memoisle.app.network.QuickAccessEntry
import com.memoisle.app.network.ReviewSettings
import com.memoisle.app.network.WordLookupResponse
import com.memoisle.app.ui.UiText
import com.memoisle.app.ui.UiTextException
import com.memoisle.app.ui.toUiText
import java.nio.file.Files
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class MemoUiState(
    val isRefreshing: Boolean = false,
    val isSaving: Boolean = false,
    val isExporting: Boolean = false,
    val message: UiText? = null,
    val undoMemo: Memo? = null,
    val duplicateWord: Memo? = null,
    val duplicateResource: Memo? = null,
    val isLookingUpWord: Boolean = false,
    val wordLookup: WordLookupResponse? = null,
    val isUploadingImage: Boolean = false,
    val isDownloadingAudio: Boolean = false,
    val reviewSettings: ReviewSettings = ReviewSettings(
        dailyLimit = 10,
        intervalsDays = listOf(1, 3, 7, 14, 30, 60),
    ),
)

class MemoViewModel(
    private val repository: MemoRepository,
) : ViewModel() {
    val memos = repository.memos

    var uiState by mutableStateOf(MemoUiState(isRefreshing = true))
        private set
    private var mediaPlayer: MediaPlayer? = null
    private var refreshJob: Job? = null
    private var wordLookupJob: Job? = null
    private var wordLookupGeneration = 0

    // 图片按需加载：列表用缩略图，详情页在点击后再取原图。
    var imageThumbnails by mutableStateOf<Map<String, ByteArray>>(emptyMap())
        private set
    var fullImages by mutableStateOf<Map<String, ByteArray>>(emptyMap())
        private set
    var loadingImageKeys by mutableStateOf<Set<String>>(emptySet())
        private set
    private val failedImageKeys = mutableSetOf<String>()

    var quickAccess by mutableStateOf<List<QuickAccessEntry>>(emptyList())
        private set
    // 首次读取完成前不显示，避免空状态一闪而过。
    var quickAccessLoaded by mutableStateOf(false)
        private set

    init {
        refresh()
    }

    fun refresh() {
        if (refreshJob?.isActive == true) {
            return
        }
        val expectedUserId = repository.activeUserId()
        if (expectedUserId == null) {
            uiState = uiState.copy(isRefreshing = false)
            return
        }
        refreshJob = viewModelScope.launch {
            uiState = uiState.copy(isRefreshing = true, message = null)
            // 刷新后允许重新尝试之前失败的图片加载。
            failedImageKeys.clear()
            val syncResult = runCatching { repository.refresh(expectedUserId) }
            if (syncResult.isSuccess) {
                // 复习计划与内容一起刷新，确保离线恢复后 Android 使用服务端配置。
                runCatching { repository.getReviewSettings() }
                    .onSuccess { settings ->
                        uiState = uiState.copy(reviewSettings = settings)
                    }
            }
            uiState = syncResult
                .fold(
                    onSuccess = { result ->
                        when {
                            result.wasCancelledForUserSwitch -> {
                                uiState.copy(isRefreshing = false, message = null)
                            }
                            result.hasRetryableFailure -> {
                                uiState.copy(
                                    isRefreshing = false,
                                    message = UiText.res(R.string.memo_msg_synced_partial),
                                )
                            }
                            else -> {
                                uiState.copy(isRefreshing = false, message = UiText.res(R.string.memo_msg_synced_with_web))
                            }
                        }
                    },
                    onFailure = { error ->
                        uiState.copy(
                            isRefreshing = false,
                            message = UiText.res(R.string.memo_msg_offline, error.toUiText()),
                        )
                    },
                )
            refreshJob = null
        }
    }

    fun unsyncedCount(): Int = repository.unsyncedCount()

    fun exportUserData(uri: Uri, contentResolver: ContentResolver): Unit {
        if (uiState.isSaving || uiState.isExporting) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isExporting = true, message = null)
            runCatching {
                withContext(Dispatchers.IO) {
                    val output = contentResolver.openOutputStream(uri)
                        ?: error(UiText.res(R.string.memo_msg_export_open_failed))
                    output.use { repository.exportUserData(it) }
                }
            }.onSuccess {
                uiState = uiState.copy(
                    isExporting = false,
                    message = UiText.res(R.string.memo_msg_exported),
                )
            }.onFailure { error ->
                uiState = uiState.copy(
                    isExporting = false,
                    message = UiText.res(R.string.memo_msg_export_failed, error.toUiText()),
                )
            }
        }
    }

    /**
     * 下载当前条目的原始录音到用户通过系统文件选择器指定的位置。
     * 已在本机的录音直接复制，未同步的离线录音也无需先上传。
     */
    fun downloadAudio(memo: Memo, uri: Uri, contentResolver: ContentResolver): Unit {
        if (uiState.isDownloadingAudio) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isDownloadingAudio = true, message = null)
            runCatching {
                withContext(Dispatchers.IO) {
                    val audioFile = repository.audioFile(memo)
                    val output = contentResolver.openOutputStream(uri)
                        ?: error(UiText.res(R.string.memo_msg_save_file_open_failed))
                    output.use { Files.copy(audioFile, it) }
                }
            }.onSuccess {
                uiState = uiState.copy(
                    isDownloadingAudio = false,
                    message = UiText.res(R.string.memo_msg_audio_saved),
                )
            }.onFailure { error ->
                uiState = uiState.copy(
                    isDownloadingAudio = false,
                    message = UiText.res(R.string.memo_msg_audio_download_failed, error.toUiText()),
                )
            }
        }
    }

    fun resolveConflictWithServer(memo: Memo): Unit {
        repository.resolveConflictWithServer(memo)
        uiState = uiState.copy(message = UiText.res(R.string.memo_msg_used_server_version))
    }

    fun loadConflictServer(memo: Memo, onResult: (Memo) -> Unit): Unit {
        if (memo.id == null || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            runCatching { repository.loadConflictServer(memo) }
                .onSuccess(onResult)
                .onFailure { error ->
                    uiState = uiState.copy(
                        message = UiText.res(R.string.memo_msg_conflict_server_unavailable, error.toUiText()),
                    )
                }
        }
    }

    fun syncBeforeLogout(onResult: (Boolean) -> Unit): Unit {
        if (refreshJob?.isActive == true || uiState.isSaving) {
            return
        }
        val expectedUserId = repository.activeUserId()
        if (expectedUserId == null) {
            onResult(false)
            return
        }
        refreshJob = viewModelScope.launch {
            uiState = uiState.copy(isRefreshing = true, message = null)
            val syncResult = runCatching { repository.refresh(expectedUserId) }
            val completed = syncResult.getOrNull()?.let { result ->
                !result.wasCancelledForUserSwitch &&
                    !result.hasRetryableFailure &&
                    repository.unsyncedCount() == 0
            } == true
            uiState = syncResult.fold(
                onSuccess = {
                    uiState.copy(
                        isRefreshing = false,
                        message = if (completed) {
                            UiText.res(R.string.memo_msg_sync_complete_safe)
                        } else {
                            UiText.res(R.string.memo_msg_sync_incomplete)
                        },
                    )
                },
                onFailure = { error ->
                    uiState.copy(
                        isRefreshing = false,
                        message = UiText.res(R.string.memo_msg_sync_failed_stay, error.toUiText()),
                    )
                },
            )
            onResult(completed)
            refreshJob = null
        }
    }

    fun createIdea(body: String, onSuccess: () -> Unit) {
        if (body.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null, undoMemo = null)
            runCatching { repository.createIdea(body) }
                .onSuccess { created ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_idea_saved),
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_saved_locally_retry, error.toUiText()),
                    )
                    onSuccess()
                }
        }
    }

    fun createSharedResource(
        url: String,
        title: String,
        note: String,
        allowDuplicate: Boolean = false,
        onDuplicate: (Memo) -> Unit = {},
        onSuccess: () -> Unit,
    ) {
        if (url.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(
                isSaving = true,
                message = null,
                duplicateResource = null,
                undoMemo = null,
            )
            runCatching {
                repository.createSharedResource(url, title, note, allowDuplicate)
            }
                .onSuccess { created ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_resource_saved),
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    if (error is DuplicateResourceException) {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = UiText.res(R.string.memo_msg_duplicate_url),
                            duplicateResource = error.existing,
                        )
                        onDuplicate(error.existing)
                    } else {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = UiText.res(R.string.memo_msg_saved_locally_retry, error.toUiText()),
                        )
                        onSuccess()
                    }
                }
        }
    }

    fun createWord(
        lemma: String,
        phonetic: String,
        meaning: String,
        example: String,
        sourceUrl: String? = null,
        allowDuplicate: Boolean = false,
        onDuplicate: (Memo) -> Unit = {},
        onSuccess: () -> Unit,
    ) {
        if (lemma.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(
                isSaving = true,
                message = null,
                duplicateWord = null,
                undoMemo = null,
            )
            runCatching {
                repository.createWord(
                    lemma,
                    phonetic,
                    meaning,
                    example,
                    sourceUrl,
                    allowDuplicate,
                )
            }
                .onSuccess { created ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_word_saved),
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    if (error is DuplicateLemmaException) {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = UiText.res(R.string.memo_msg_duplicate_word),
                            duplicateWord = error.existing,
                        )
                        onDuplicate(error.existing)
                    } else {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = UiText.res(R.string.memo_msg_saved_locally_retry, error.toUiText()),
                        )
                        onSuccess()
                    }
                }
        }
    }

    fun lookupWord(
        word: String,
        silent: Boolean = false,
        showPreview: Boolean = true,
        onResult: ((WordLookupResponse) -> Unit)? = null,
    ) {
        val cleanedWord = word.trim()
        if (cleanedWord.isBlank()) {
            return
        }
        val generation = ++wordLookupGeneration
        wordLookupJob?.cancel()
        wordLookupJob = viewModelScope.launch {
            uiState = uiState.copy(
                isLookingUpWord = true,
                wordLookup = if (showPreview) null else uiState.wordLookup,
                message = if (silent) uiState.message else null,
            )
            try {
                val preview = withContext(Dispatchers.IO) {
                    repository.lookupWord(cleanedWord)
                }
                if (generation != wordLookupGeneration) {
                    return@launch
                }
                uiState = uiState.copy(
                    isLookingUpWord = false,
                    wordLookup = if (showPreview) preview else uiState.wordLookup,
                    message = when {
                        silent -> uiState.message
                        preview.senses.isEmpty() -> UiText.res(R.string.memo_msg_lookup_no_meaning)
                        else -> UiText.res(R.string.memo_msg_lookup_found)
                    },
                )
                if (preview.senses.isNotEmpty()) {
                    onResult?.invoke(preview)
                }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                if (generation == wordLookupGeneration) {
                    uiState = uiState.copy(
                        isLookingUpWord = false,
                        message = if (silent) {
                            uiState.message
                        } else {
                            UiText.res(R.string.memo_msg_lookup_failed, error.toUiText())
                        },
                    )
                }
            }
        }
    }

    fun clearWordLookup() {
        wordLookupGeneration += 1
        wordLookupJob?.cancel()
        wordLookupJob = null
        uiState = uiState.copy(isLookingUpWord = false, wordLookup = null)
    }

    fun mergeWord(existing: Memo, incoming: Memo, onSuccess: () -> Unit) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.mergeWord(existing, incoming) }
                .onSuccess {
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_merged),
                        duplicateWord = null,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_merge_failed, error.toUiText()),
                    )
                }
        }
    }

    fun moveToTrash(memo: Memo, onSuccess: () -> Unit = {}) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.trashMemo(memo) }
                .onSuccess {
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_trashed),
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_trash_failed, error.toUiText()),
                    )
                }
        }
    }

    fun restoreMemo(memo: Memo, onSuccess: () -> Unit = {}) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.restoreMemo(memo) }
                .onSuccess {
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_restored),
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_restore_failed, error.toUiText()),
                    )
                }
        }
    }

    fun permanentlyDeleteMemo(memo: Memo, onSuccess: () -> Unit = {}) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.permanentlyDeleteMemo(memo) }
                .onSuccess {
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_purged),
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_purge_failed, error.toUiText()),
                    )
                }
        }
    }

    fun undoLastSave() {
        val memo = uiState.undoMemo ?: return
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.trashMemo(memo) }
                .onSuccess {
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_undo_done),
                        undoMemo = null,
                    )
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_undo_failed, error.toUiText()),
                    )
                }
        }
    }

    fun createVoiceIdea(
        body: String,
        audioPath: String,
        durationMs: Int,
        onSuccess: () -> Unit,
    ) {
        if (audioPath.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null, undoMemo = null)
            runCatching { repository.createVoiceIdea(body, audioPath, durationMs) }
                .onSuccess { created ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_voice_saved),
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_voice_saved_locally, error.toUiText()),
                    )
                    onSuccess()
                }
        }
    }

    /**
     * 从相册选中的图片创建图片收藏：读取图片、必要时自动压缩，再创建条目并上传。
     * 只有真正不支持的文件格式才会被拒绝；超过 20 MB / 12000 像素 / 5000 万像素的图片
     * 会先压缩，压缩后通过 snackbar 告知用户体积、尺寸和格式的变化。
     */
    fun createImageMemo(
        uri: Uri,
        contentResolver: ContentResolver,
        onSuccess: (Memo) -> Unit,
    ) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(
                isSaving = true,
                isUploadingImage = true,
                message = null,
                undoMemo = null,
            )
            var compression: ImageCompressionResult? = null
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val displayName = queryDisplayName(contentResolver, uri)
                    val mimeType = normalizeImageMimeType(contentResolver.getType(uri))
                        ?: imageMimeTypeFromFileName(displayName)
                        ?: throw UiTextException(UiText.res(R.string.error_image_unsupported_type))
                    // 超出服务端限制的图片在这里压缩；限制内的图片原样上传。
                    val prepared = ImageCompressor.compress(contentResolver, uri, mimeType)
                    compression = prepared
                    val created = repository.createImageMemo(
                        title = imageMemoTitleFromFileName(displayName),
                        body = "",
                        bytes = prepared.bytes,
                        mimeType = prepared.mimeType,
                    )
                    created to prepared
                }
            }
            val prepared = compression
            result
                .onSuccess { (created, compressed) ->
                    // 上传成功后立即用本地字节填充缩略图，避免列表再次请求服务端。
                    cacheThumbnail(created.clientId, compressed.bytes)
                    cacheFullImage(created.clientId, compressed.bytes)
                    uiState = uiState.copy(
                        isSaving = false,
                        isUploadingImage = false,
                        message = if (compressed.compressed) {
                            compressed.reminderMessage()
                        } else {
                            UiText.res(R.string.memo_msg_image_saved)
                        },
                        undoMemo = created,
                    )
                    onSuccess(created)
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        isUploadingImage = false,
                        message = if (prepared?.compressed == true) {
                            UiText.res(R.string.memo_msg_image_compressed_but, imageFailureMessage(error))
                        } else {
                            imageFailureMessage(error)
                        },
                    )
                }
        }
    }

    /**
     * 写入缓存并按字节预算淘汰最早加入的条目。
     *
     * 以前缩略图只增不减，原图只在关闭详情时释放，浏览越久占用越大。
     * Kotlin 的 Map 加法保留插入顺序，最先加入的就是最久未加入的。
     * 重新访问已淘汰的图片会再走 repository（它有磁盘缓存），不会出错。
     */
    private fun Map<String, ByteArray>.withBounded(
        key: String,
        bytes: ByteArray,
        maxBytes: Int,
        maxEntries: Int,
    ): Map<String, ByteArray> {
        val next = LinkedHashMap(this)
        next.remove(key)
        next[key] = bytes
        var total = next.values.sumOf { it.size.toLong() }
        val iterator = next.entries.iterator()
        while ((total > maxBytes || next.size > maxEntries) && next.size > 1 && iterator.hasNext()) {
            val oldest = iterator.next()
            if (oldest.key == key) {
                continue
            }
            total -= oldest.value.size
            iterator.remove()
        }
        return next
    }

    private fun cacheThumbnail(key: String, bytes: ByteArray) {
        imageThumbnails = imageThumbnails.withBounded(
            key,
            bytes,
            maxBytes = THUMBNAIL_CACHE_MAX_BYTES,
            maxEntries = THUMBNAIL_CACHE_MAX_ENTRIES,
        )
    }

    private fun cacheFullImage(key: String, bytes: ByteArray) {
        fullImages = fullImages.withBounded(
            key,
            bytes,
            maxBytes = FULL_IMAGE_CACHE_MAX_BYTES,
            maxEntries = FULL_IMAGE_CACHE_MAX_ENTRIES,
        )
    }

    fun imageThumbnail(memo: Memo): ByteArray? = imageThumbnails[memo.clientId]

    fun imageFullImage(memo: Memo): ByteArray? = fullImages[memo.clientId]

    fun isImageLoading(memo: Memo, thumbnail: Boolean): Boolean =
        imageKey(memo, thumbnail) in loadingImageKeys

    fun requestImageThumbnail(memo: Memo) {
        loadMemoImage(memo, thumbnail = true)
    }

    fun requestFullImage(memo: Memo) {
        loadMemoImage(memo, thumbnail = false)
    }

    fun releaseFullImage(memo: Memo) {
        fullImages = fullImages - memo.clientId
    }

    private fun loadMemoImage(memo: Memo, thumbnail: Boolean) {
        val key = imageKey(memo, thumbnail)
        if (key in loadingImageKeys || key in failedImageKeys) {
            return
        }
        val cached = if (thumbnail) imageThumbnails[memo.clientId] else fullImages[memo.clientId]
        if (cached != null) {
            return
        }
        loadingImageKeys = loadingImageKeys + key
        viewModelScope.launch {
            runCatching { repository.loadMemoImage(memo, thumbnail) }
                .onSuccess { bytes ->
                    if (thumbnail) {
                        cacheThumbnail(memo.clientId, bytes)
                    } else {
                        cacheFullImage(memo.clientId, bytes)
                    }
                }
                .onFailure { error ->
                    failedImageKeys.add(key)
                    if (!thumbnail) {
                        uiState = uiState.copy(
                            message = UiText.res(R.string.memo_msg_original_image_failed, error.toUiText()),
                        )
                    }
                }
            loadingImageKeys = loadingImageKeys - key
        }
    }

    private fun imageKey(memo: Memo, thumbnail: Boolean): String =
        "${memo.clientId}:${if (thumbnail) "t" else "f"}"

    private fun queryDisplayName(contentResolver: ContentResolver, uri: Uri): String? {
        return runCatching {
            contentResolver.query(
                uri,
                arrayOf(OpenableColumns.DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { cursor ->
                if (!cursor.moveToFirst()) {
                    return@use null
                }
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index < 0 || cursor.isNull(index)) null else cursor.getString(index)
            }
        }.getOrNull()
    }

    private fun imageFailureMessage(error: Throwable): UiText {
        return when {
            error is ApiException && error.statusCode == 413 -> UiText.res(R.string.memo_msg_image_too_large)
            error is ApiException && error.statusCode == 422 ->
                error.detailMessage?.let(UiText::plain) ?: UiText.res(R.string.memo_msg_image_invalid)
            error is ApiException && error.statusCode == 409 ->
                UiText.res(R.string.memo_msg_image_conflict)
            error is IllegalArgumentException -> error.toUiText()
            else -> UiText.res(R.string.memo_msg_image_failed_kept, error.toUiText())
        }
    }

    fun updateMemo(
        memo: Memo,
        title: String,
        body: String,
        sourceUrl: String?,
        wordPhonetic: String?,
        wordMeaning: String?,
        wordExample: String?,
        onSuccess: () -> Unit,
        onConflict: (Memo) -> Unit = {},
    ) {
        if (memo.type == TYPE_RESOURCE) {
            uiState = uiState.copy(message = UiText.res(R.string.memo_msg_resource_read_only))
            return
        }
        if (title.isBlank() || body.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            val updatedMemo = memo.copy(
                sourceUrl = sourceUrl ?: memo.sourceUrl,
                sourceTitle = if (memo.type == "resource") title.trim() else memo.sourceTitle,
                wordPhonetic = wordPhonetic ?: memo.wordPhonetic,
                wordMeaning = wordMeaning ?: memo.wordMeaning,
                wordExample = wordExample ?: memo.wordExample,
            )
            runCatching { repository.updateMemo(updatedMemo, title, body) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = UiText.res(R.string.memo_msg_edit_synced))
                    onSuccess()
                }
                .onFailure { error ->
                    if (error is ApiException && error.statusCode == 409) {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = if (error.current == null) {
                                UiText.res(R.string.memo_msg_edit_conflict_refresh)
                            } else {
                                UiText.res(R.string.memo_msg_edit_conflict_loaded)
                            },
                        )
                        error.current?.let(onConflict)
                    } else {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = UiText.res(R.string.memo_msg_edit_saved_locally, error.toUiText()),
                        )
                        onSuccess()
                    }
                }
        }
    }

    fun clearMessage() {
        uiState = uiState.copy(message = null)
    }

    fun clearDuplicate() {
        uiState = uiState.copy(duplicateWord = null)
    }

    fun clearDuplicateResource() {
        uiState = uiState.copy(duplicateResource = null)
    }

    fun reviewWord(memo: Memo, feedback: String, onSuccess: () -> Unit) {
        if (memo.id == null || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.reviewWord(memo, feedback) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = UiText.res(R.string.memo_msg_review_recorded))
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_review_failed, error.toUiText()),
                    )
                }
        }
    }

    fun skipReview(memo: Memo, onSuccess: () -> Unit = {}) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.skipReview(memo) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = UiText.res(R.string.memo_msg_review_skipped))
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_skip_failed, error.toUiText()),
                    )
                }
        }
    }

    fun saveReviewSettings(
        dailyLimit: Int,
        intervalsDays: List<Int>,
    ) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching {
                repository.updateReviewSettings(dailyLimit, intervalsDays)
            }.onSuccess { settings ->
                uiState = uiState.copy(
                    isSaving = false,
                    reviewSettings = settings,
                    message = UiText.res(R.string.memo_msg_review_plan_updated),
                )
            }.onFailure { error ->
                uiState = uiState.copy(
                    isSaving = false,
                    message = UiText.res(R.string.memo_msg_review_plan_failed, error.toUiText()),
                )
            }
        }
    }

    /** 打开原网页时计一次数，常用网页按次数出现在快速访问。离线时不计数。 */
    fun recordResourceOpen(memo: Memo) {
        val remoteId = memo.id ?: return
        viewModelScope.launch {
            val recorded = runCatching {
                withContext(Dispatchers.IO) { repository.recordResourceOpen(remoteId) }
            }.isSuccess
            if (recorded) loadQuickAccess()
        }
    }

    fun loadQuickAccess() {
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { repository.listQuickAccess() } }
                .onSuccess { entries ->
                    quickAccess = entries
                    quickAccessLoaded = true
                }
        }
    }

    fun setQuickAccessHidden(memo: Memo, hidden: Boolean, onDone: (Boolean) -> Unit = {}) {
        val remoteId = memo.id ?: return
        if (hidden) {
            // 先从界面移除，失败再放回。
            quickAccess = quickAccess.filter { it.memo.id != remoteId }
        }
        viewModelScope.launch {
            val succeeded = runCatching {
                withContext(Dispatchers.IO) { repository.setQuickAccessHidden(remoteId, hidden) }
            }.isSuccess
            loadQuickAccess()
            onDone(succeeded)
        }
    }

    fun markResourceOpened(memo: Memo, onSuccess: () -> Unit = {}) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.markResourceOpened(memo) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = UiText.res(R.string.memo_msg_opened_source))
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_reading_sync_failed, error.toUiText()),
                    )
                    onSuccess()
                }
        }
    }

    fun toggleStar(memo: Memo) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.toggleStar(memo) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false)
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_star_sync_failed, error.toUiText()),
                    )
                }
        }
    }

    fun organizeIdea(memo: Memo, title: String, body: String, onSuccess: () -> Unit) {
        if (body.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.organizeIdea(memo, title, body) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = UiText.res(R.string.memo_msg_idea_sorted))
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_sort_saved_locally, error.toUiText()),
                    )
                    onSuccess()
                }
        }
    }

    fun archiveIdea(memo: Memo, onSuccess: () -> Unit) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.archiveIdea(memo) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = UiText.res(R.string.memo_msg_idea_archived))
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_archive_saved_locally, error.toUiText()),
                    )
                    onSuccess()
                }
        }
    }

    fun archiveMemo(memo: Memo, onSuccess: () -> Unit) {
        if (uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.archiveMemo(memo) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = UiText.res(R.string.memo_msg_item_archived))
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = UiText.res(R.string.memo_msg_archive_saved_locally, error.toUiText()),
                    )
                    onSuccess()
                }
        }
    }

    fun playAudio(memo: Memo) {
        viewModelScope.launch {
            runCatching {
                val audioFile = withContext(Dispatchers.IO) { repository.audioFile(memo) }
                withContext(Dispatchers.Main) {
                    mediaPlayer?.release()
                    mediaPlayer = MediaPlayer().apply {
                        setDataSource(audioFile.toString())
                        setOnPreparedListener { player -> player.start() }
                        prepareAsync()
                    }
                }
            }.onFailure { error ->
                uiState = uiState.copy(message = UiText.res(R.string.memo_msg_audio_play_failed, error.toUiText()))
            }
        }
    }

    override fun onCleared() {
        mediaPlayer?.release()
        mediaPlayer = null
        super.onCleared()
    }

    companion object {
        // ViewModel 层的显示缓存：缩略图小而多，原图大而少。
        private const val THUMBNAIL_CACHE_MAX_BYTES = 16 * 1024 * 1024
        private const val THUMBNAIL_CACHE_MAX_ENTRIES = 300
        private const val FULL_IMAGE_CACHE_MAX_BYTES = 32 * 1024 * 1024
        private const val FULL_IMAGE_CACHE_MAX_ENTRIES = 6

        fun factory(repository: MemoRepository): ViewModelProvider.Factory {
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    require(modelClass.isAssignableFrom(MemoViewModel::class.java))
                    return MemoViewModel(repository) as T
                }
            }
        }
    }
}



/**
 * 保存类提示：Snackbar 在有 [MemoUiState.undoMemo] 时为这些提示提供「撤销」。
 * 以前按中文文案里是否含「已保存 / 已收藏」判断，改成按文案资源判断，与界面语言无关。
 */
private val UNDOABLE_SAVE_MESSAGES = setOf(
    R.string.memo_msg_idea_saved,
    R.string.memo_msg_saved_locally_retry,
    R.string.memo_msg_resource_saved,
    R.string.memo_msg_duplicate_url,
    R.string.memo_msg_word_saved,
    R.string.memo_msg_duplicate_word,
    R.string.memo_msg_voice_saved,
    R.string.memo_msg_voice_saved_locally,
    R.string.memo_msg_image_saved,
    R.string.memo_msg_edit_saved_locally,
    R.string.memo_msg_sort_saved_locally,
    R.string.memo_msg_archive_saved_locally,
    R.string.memo_msg_audio_saved,
)

fun UiText.isUndoableSaveMessage(): Boolean = this is UiText.Res && id in UNDOABLE_SAVE_MESSAGES
