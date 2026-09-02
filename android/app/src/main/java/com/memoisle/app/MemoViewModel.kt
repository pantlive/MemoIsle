package com.memoisle.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.Memo
import com.memoisle.app.data.MemoRepository
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.DuplicateLemmaException
import kotlinx.coroutines.launch

data class MemoUiState(
    val isRefreshing: Boolean = false,
    val isSaving: Boolean = false,
    val message: String? = null,
    val undoMemo: Memo? = null,
    val duplicateWord: Memo? = null,
)

class MemoViewModel(
    private val repository: MemoRepository,
) : ViewModel() {
    val memos = repository.memos

    var uiState by mutableStateOf(MemoUiState(isRefreshing = true))
        private set

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            uiState = uiState.copy(isRefreshing = true, message = null)
            uiState = runCatching { repository.refresh() }
                .fold(
                    onSuccess = {
                        uiState.copy(isRefreshing = false, message = "已与 Web 端同步")
                    },
                    onFailure = { error ->
                        uiState.copy(
                            isRefreshing = false,
                            message = "当前离线，已显示本地内容：${error.readableMessage()}",
                        )
                    },
                )
        }
    }

    fun createIdea(body: String, onSuccess: () -> Unit) {
        if (body.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.createIdea(body) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = "灵感已保存")
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
        onSuccess: () -> Unit,
    ) {
        if (url.isBlank() || uiState.isSaving) {
            return
        }
        viewModelScope.launch {
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.createSharedResource(url, title, note) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = "网页资料已保存")
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
            uiState = uiState.copy(isSaving = true, message = null, duplicateWord = null)
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
                        message = "已撤销刚才的保存",
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
            uiState = uiState.copy(isSaving = true, message = null)
            runCatching { repository.createVoiceIdea(body, audioPath, durationMs) }
                .onSuccess {
                    uiState = uiState.copy(isSaving = false, message = "语音灵感已保存")
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

    fun updateMemo(
        memo: Memo,
        title: String,
        body: String,
        sourceUrl: String?,
        wordPhonetic: String?,
        wordMeaning: String?,
        wordExample: String?,
        onSuccess: () -> Unit,
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
                    val conflictMessage = if (error is ApiException && error.statusCode == 409) {
                        "其他设备已更新这条灵感，请刷新后重新编辑。"
                    } else {
                        "修改已保存在本机，稍后重试同步：${error.readableMessage()}"
                    }
                    uiState = uiState.copy(isSaving = false, message = conflictMessage)
                    onSuccess()
                }
        }
    }

    fun clearMessage() {
        uiState = uiState.copy(message = null)
    }

    fun clearDuplicate() {
        uiState = uiState.copy(duplicateWord = null)
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

    fun audioUrl(memoId: String): String = repository.audioUrl(memoId)

    companion object {
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
