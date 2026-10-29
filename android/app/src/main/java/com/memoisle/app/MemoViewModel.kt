package com.memoisle.app

import android.content.ContentResolver
import android.net.Uri
import android.media.MediaPlayer
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
    val message: String? = null,
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
                                    message = "已同步，部分内容将在联网后自动重试",
                                )
                            }
                            else -> {
                                uiState.copy(isRefreshing = false, message = "已与 Web 端同步")
                            }
                        }
                    },
                    onFailure = { error ->
                        uiState.copy(
                            isRefreshing = false,
                            message = "当前离线，已显示本地内容：${error.readableMessage()}",
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
                        ?: error("无法打开导出文件")
                    output.use { repository.exportUserData(it) }
                }
            }.onSuccess {
                uiState = uiState.copy(
                    isExporting = false,
                    message = "个人数据已导出；录音二进制未打包进 JSON",
                )
            }.onFailure { error ->
                uiState = uiState.copy(
                    isExporting = false,
                    message = "数据导出失败：${error.readableMessage()}",
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
                        ?: error("无法打开保存文件")
                    output.use { Files.copy(audioFile, it) }
                }
            }.onSuccess {
                uiState = uiState.copy(
                    isDownloadingAudio = false,
                    message = "录音已保存到你选择的位置",
                )
            }.onFailure { error ->
                uiState = uiState.copy(
                    isDownloadingAudio = false,
                    message = "录音下载失败：${error.readableMessage()}",
                )
            }
        }
    }

    fun resolveConflictWithServer(memo: Memo): Unit {
        repository.resolveConflictWithServer(memo)
        uiState = uiState.copy(message = "已采用服务端版本")
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
                        message = "暂时无法读取服务端版本，请联网后再处理冲突：${error.readableMessage()}",
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
                            "同步完成，可以安全退出"
                        } else {
                            "仍有内容未同步，请保持登录后重试"
                        },
                    )
                },
                onFailure = { error ->
                    uiState.copy(
                        isRefreshing = false,
                        message = "同步未完成，请保持登录后重试：${error.readableMessage()}",
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
                        message = "灵感已保存",
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "已保存在本机，联网后可重试同步：${error.readableMessage()}",
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
                        message = "网页资料已保存",
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    if (error is DuplicateResourceException) {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = "已收藏相同网址，可以查看已有资料或仍然保存。",
                            duplicateResource = error.existing,
                        )
                        onDuplicate(error.existing)
                    } else {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = "已保存在本机，联网后可重试同步：${error.readableMessage()}",
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
                        message = "英语单词已收藏",
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    if (error is DuplicateLemmaException) {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = "已收藏相同词形，可以查看、合并例句或仍然保存。",
                            duplicateWord = error.existing,
                        )
                        onDuplicate(error.existing)
                    } else {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = "已保存在本机，联网后可重试同步：${error.readableMessage()}",
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
                        preview.senses.isEmpty() -> "词典没有返回中文释义，请手动填写"
                        else -> "已查到中文释义，可继续选择其他义项"
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
                            "查词失败：${error.readableMessage()}"
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
                        message = "已把新语境合并进已有单词",
                        duplicateWord = null,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "合并失败：${error.readableMessage()}",
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
                        message = "已移入回收站，可在 30 天内恢复",
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "移入回收站失败：${error.readableMessage()}",
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
                        message = "已从回收站恢复",
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "恢复失败：${error.readableMessage()}",
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
                        message = "已永久删除",
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "永久删除失败：${error.readableMessage()}",
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
                        message = "已撤销刚才的保存，可在回收站恢复",
                        undoMemo = null,
                    )
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "撤销失败：${error.readableMessage()}",
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
                        message = "语音灵感已保存",
                        undoMemo = created,
                    )
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "录音已保存在本机，稍后重试同步：${error.readableMessage()}",
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
                        ?: throw IllegalArgumentException("仅支持 PNG/JPEG/WebP/GIF 图片")
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
                            "图片已收藏"
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
                            "图片已自动压缩，但${imageFailureMessage(error)}"
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
                            message = "读取原图失败：${error.readableMessage()}",
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

    private fun imageFailureMessage(error: Throwable): String {
        return when {
            error is ApiException && error.statusCode == 413 -> "图片不能超过 20 MB"
            error is ApiException && error.statusCode == 422 ->
                error.detailMessage ?: "图片文件无效或已损坏"
            error is ApiException && error.statusCode == 409 ->
                "图片已在其他设备更新，请刷新后重新选择"
            error is IllegalArgumentException -> error.readableMessage()
            else -> "图片收藏失败，已保留本机副本，联网后可重试：${error.readableMessage()}"
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
            uiState = uiState.copy(message = "Android 端网页资料为只读，请在 Web 端整理")
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
                    uiState = uiState.copy(isSaving = false, message = "修改已同步")
                    onSuccess()
                }
                .onFailure { error ->
                    if (error is ApiException && error.statusCode == 409) {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = if (error.current == null) {
                                "其他设备已更新这条灵感，请刷新后重新编辑。"
                            } else {
                                "其他设备已更新这条灵感，已载入最新版本，请确认后重新保存。"
                            },
                        )
                        error.current?.let(onConflict)
                    } else {
                        uiState = uiState.copy(
                            isSaving = false,
                            message = "修改已保存在本机，稍后重试同步：${error.readableMessage()}",
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
                    uiState = uiState.copy(isSaving = false, message = "复习结果已记录")
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "复习结果提交失败：${error.readableMessage()}",
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
                    uiState = uiState.copy(isSaving = false, message = "已跳过，明天之前不会再出现")
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "跳过失败：${error.readableMessage()}",
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
                    message = "复习计划已更新",
                )
            }.onFailure { error ->
                uiState = uiState.copy(
                    isSaving = false,
                    message = "复习计划保存失败：${error.readableMessage()}",
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
                    uiState = uiState.copy(isSaving = false, message = "已打开原网页")
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "阅读状态同步失败：${error.readableMessage()}",
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
                        message = "星标同步失败：${error.readableMessage()}",
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
                    uiState = uiState.copy(isSaving = false, message = "灵感已整理")
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "整理已保存在本机：${error.readableMessage()}",
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
                    uiState = uiState.copy(isSaving = false, message = "灵感已归档")
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "归档已保存在本机：${error.readableMessage()}",
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
                    uiState = uiState.copy(isSaving = false, message = "内容已归档")
                    onSuccess()
                }
                .onFailure { error ->
                    uiState = uiState.copy(
                        isSaving = false,
                        message = "归档已保存在本机：${error.readableMessage()}",
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
                uiState = uiState.copy(message = "录音播放失败：${error.readableMessage()}")
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

private fun Throwable.readableMessage(): String {
    return message?.take(120) ?: "未知错误"
}
