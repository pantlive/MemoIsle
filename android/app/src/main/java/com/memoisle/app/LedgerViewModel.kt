package com.memoisle.app

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.memoisle.app.data.ImageCompressor
import com.memoisle.app.data.LedgerCategoryUsage
import com.memoisle.app.data.LedgerEntry
import com.memoisle.app.data.LedgerEntryInput
import com.memoisle.app.data.LedgerImageDraft
import com.memoisle.app.data.LedgerQuickResult
import com.memoisle.app.data.LedgerSummary
import com.memoisle.app.data.currentLedgerMonth
import com.memoisle.app.data.formatLedgerMoney
import com.memoisle.app.data.imageMimeTypeFromFileName
import com.memoisle.app.data.normalizeImageMimeType
import com.memoisle.app.data.shiftLedgerMonth
import com.memoisle.app.network.ApiException
import com.memoisle.app.network.MemoApiClient
import com.memoisle.app.ui.HasUiText
import com.memoisle.app.ui.UiText
import com.memoisle.app.ui.UiTextException
import java.time.LocalDate
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class LedgerUiState(
    val month: String = currentLedgerMonth(),
    val kind: String = "",
    val category: String = "",
    val entries: List<LedgerEntry> = emptyList(),
    val summary: LedgerSummary? = null,
    val categories: List<LedgerCategoryUsage> = emptyList(),
    val loading: Boolean = false,
    val busy: Boolean = false,
    val hasMore: Boolean = false,
    val error: UiText? = null,
    val message: UiText? = null,
    /** 一句话刚记下的那一笔，提示旁边提供「编辑」入口。 */
    val quickEntry: LedgerEntry? = null,
)

/** 在线记账；取消旧请求，避免切月或退出登录后写回旧账号数据。 */
class LedgerViewModel(private val api: MemoApiClient) : ViewModel() {
    var uiState by mutableStateOf(LedgerUiState())
        private set
    private var loadJob: Job? = null
    private var mutationJob: Job? = null

    fun reset() {
        loadJob?.cancel()
        mutationJob?.cancel()
        uiState = LedgerUiState()
    }

    fun changeMonth(delta: Long) {
        if (uiState.busy) return
        val month = shiftLedgerMonth(uiState.month, delta)
        if (month < "1900-01" || month > "2100-12") return
        uiState = uiState.copy(month = month)
        load()
    }

    fun currentMonth() {
        if (uiState.busy) return
        uiState = uiState.copy(month = currentLedgerMonth())
        load()
    }

    fun filter(kind: String, category: String) {
        if (uiState.busy) return
        uiState = uiState.copy(kind = kind, category = category)
        load()
    }

    fun load() {
        if (uiState.busy) return
        loadJob?.cancel()
        uiState = uiState.copy(loading = true, error = null, message = null, quickEntry = null,
            entries = emptyList(), summary = null, hasMore = false)
        val snapshot = uiState
        loadJob = viewModelScope.launch {
            try {
                val loaded = read(snapshot)
                uiState = loaded.copy(loading = false)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(loading = false, error = describe(error))
            }
        }
    }

    fun loadMore() {
        if (uiState.busy || uiState.loading || !uiState.hasMore) return
        val snapshot = uiState
        uiState = uiState.copy(loading = true, error = null)
        loadJob = viewModelScope.launch {
            try {
                val rows = withContext(Dispatchers.IO) {
                    api.listLedgerEntries(snapshot.month, snapshot.kind, snapshot.category, snapshot.entries.size)
                }
                uiState = uiState.copy(loading = false,
                    entries = (snapshot.entries + rows).distinctBy { it.id }, hasMore = rows.size == PAGE_SIZE)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(loading = false, error = describe(error))
            }
        }
    }

    fun save(entry: LedgerEntry?, input: LedgerEntryInput, onDone: () -> Unit) {
        mutate(onDone) {
            if (entry == null) api.createLedgerEntry(input)
            else api.updateLedgerEntry(entry.id, input, entry.version)
        }
    }

    fun delete(entry: LedgerEntry, onDone: () -> Unit) {
        mutate(onDone) { api.deleteLedgerEntry(entry.id, entry.version) }
    }

    /**
     * 识别相册里的小票或支付截图。成功后只把草稿交给 [onDraft]，确认保存仍走 [save]。
     */
    fun recognizeImage(
        uri: Uri,
        contentResolver: ContentResolver,
        onDraft: (LedgerImageDraft) -> Unit,
    ) {
        if (uiState.busy || uiState.loading) return
        uiState = uiState.copy(busy = true, error = null, message = null)
        viewModelScope.launch {
            try {
                val draft = withContext(Dispatchers.IO) {
                    val displayName = queryDisplayName(contentResolver, uri)
                    val mimeType = normalizeImageMimeType(contentResolver.getType(uri))
                        ?: imageMimeTypeFromFileName(displayName)
                        ?: throw UiTextException(UiText.res(R.string.error_image_unsupported_type))
                    val prepared = ImageCompressor.compress(contentResolver, uri, mimeType)
                    api.recognizeLedgerImage(prepared.bytes, prepared.mimeType, LocalDate.now().toString())
                }
                uiState = uiState.copy(busy = false)
                onDraft(draft)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(busy = false, error = describe(error))
            }
        }
    }

    /** 一句话记一笔，由服务端识别后直接保存；识别失败时不写入，输入框保留原文。 */
    fun quickAdd(text: String, onDone: () -> Unit) {
        val sentence = text.trim()
        if (sentence.isEmpty() || uiState.busy || uiState.loading) return
        if (sentence.codePointCount(0, sentence.length) > QUICK_TEXT_MAX_LENGTH) {
            uiState = uiState.copy(error = UiText.res(R.string.ledger_error_quick_too_long, QUICK_TEXT_MAX_LENGTH), message = null)
            return
        }
        val today = LocalDate.now().toString()
        mutate(onDone, onSuccess = { result: LedgerQuickResult ->
            val entry = result.entry
            // 记到别的月份时切过去，刷新后能在列表里看到这一笔。
            uiState = uiState.copy(month = entry.data.occurredOn.take(7), quickEntry = entry)
            UiText.res(
                if (result.byLocalModel) R.string.ledger_msg_quick_saved_local else R.string.ledger_msg_quick_saved,
                describeQuickEntry(entry),
            )
        }) { api.quickCreateLedgerEntry(sentence, today) }
    }

    private fun <T> mutate(
        onDone: () -> Unit,
        onSuccess: (T) -> UiText = { UiText.res(R.string.ledger_msg_saved) },
        action: () -> T,
    ) {
        if (uiState.busy || uiState.loading) return
        loadJob?.cancel()
        uiState = uiState.copy(busy = true, error = null, message = null, quickEntry = null)
        mutationJob = viewModelScope.launch {
            var message: UiText
            try {
                val result = withContext(Dispatchers.IO) { action() }
                message = onSuccess(result)
                // 写入成功就关闭表单，刷新失败时不能让用户重复提交。
                onDone()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                if (error is ApiException && error.statusCode == 409) {
                    message = UiText.res(R.string.ledger_conflict_reloading)
                    onDone()
                } else {
                    uiState = uiState.copy(busy = false, error = describe(error))
                    return@launch
                }
            }
            uiState = uiState.copy(entries = emptyList(), summary = null, hasMore = false)
            try {
                uiState = read(uiState).copy(busy = false, message = message)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                uiState = uiState.copy(busy = false, message = message, error = describe(error))
            }
        }
    }

    private suspend fun read(snapshot: LedgerUiState): LedgerUiState = withContext(Dispatchers.IO) {
        val entries = api.listLedgerEntries(snapshot.month, snapshot.kind, snapshot.category)
        val summary = api.getLedgerSummary(snapshot.month)
        val categories = api.listLedgerCategories()
        snapshot.copy(entries = entries, summary = summary, categories = categories, hasMore = entries.size == PAGE_SIZE)
    }

    private fun describeQuickEntry(entry: LedgerEntry): String = listOfNotNull(
        "${entry.data.category} ${if (entry.data.kind == "income") "+" else "-"}" +
            formatLedgerMoney(entry.data.amountCents, entry.data.currency),
        entry.data.occurredOn,
        entry.data.account,
    ).joinToString(" · ")

    private fun queryDisplayName(contentResolver: ContentResolver, uri: Uri): String? {
        return runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    if (!cursor.moveToFirst()) return@use null
                    val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (index < 0 || cursor.isNull(index)) null else cursor.getString(index)
                }
        }.getOrNull()
    }

    private fun describe(error: Exception): UiText = when (error) {
        is HasUiText -> error.text
        is ApiException -> error.detailMessage?.let(UiText::plain)
            ?: UiText.res(R.string.error_operation_failed_retry, error.statusCode)
        is IllegalArgumentException -> error.message?.let(UiText::plain) ?: UiText.res(R.string.ledger_error_image_unusable)
        is java.io.IOException -> UiText.res(R.string.ledger_error_offline)
        else -> UiText.res(R.string.ledger_error_generic)
    }

    companion object {
        const val PAGE_SIZE = 500
        const val QUICK_TEXT_MAX_LENGTH = 200
        fun factory(api: MemoApiClient): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = LedgerViewModel(api) as T
        }
    }
}
